"""LeiaPix AI - 深度估计 API

POST /api/v1/depth/estimate
- 从 PostgreSQL 查询 image 记录，获取 storage_key
- 向 tasks 表插入 status='pending' 记录
- 通过 .delay() 异步唤起 Celery 深度估计任务
- 立即响应 200 OK + task_id

GET /api/v1/depth/task/{task_id}
- 从 Redis 查询任务进度

POST /api/v1/depth/estimate-mpi
- 同步: 上传 → 深度+分割+分层 → 返回 MPI 数据 (个人使用简化版)
"""

import logging
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.image import Image as ImageModel
from app.models.task import Task
from app.tasks.depth_task import estimate_depth
from app.api.deps import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter()

# 默认用户 ID (开发阶段)
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class DepthEstimateRequest(BaseModel):
    image_id: str
    model: str = "depth_anything_v2"


class DepthEstimateResponse(BaseModel):
    task_id: str
    image_id: str
    status: str
    estimated_time_seconds: int = 8


@router.post("/depth/estimate", summary="触发深度估计", response_model=DepthEstimateResponse, dependencies=[Depends(RateLimiter("depth_estimate"))])
async def create_depth_estimate(req: DepthEstimateRequest):
    """触发 AI 深度估计异步任务"""
    settings = get_settings()

    # ---- 1. 查询 image 记录，获取 storage_key ----
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        image_id_uuid = uuid.UUID(req.image_id)
        result = await session.execute(
            select(ImageModel).where(ImageModel.id == image_id_uuid)
        )
        image_record = result.scalar_one_or_none()

    await engine.dispose()

    if image_record is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "IMAGE_NOT_FOUND", "message": f"Image {req.image_id} not found"},
        )

    if image_record.status not in ("uploaded", "depth_completed"):
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "IMAGE_BUSY",
                "message": f"Image is currently in status '{image_record.status}', cannot start depth estimation",
            },
        )

    storage_key = image_record.storage_key
    user_id = image_record.user_id
    logger.info(f"Depth estimate: image={req.image_id}, storage_key={storage_key}, model={req.model}")

    # ---- 2. 向 tasks 表插入 pending 记录 ----
    task_id = uuid.uuid4()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        task_record = Task(
            id=task_id,
            user_id=user_id,
            type="depth",
            status="pending",
            progress=0,
            input_params={
                "image_id": req.image_id,
                "model": req.model,
                "storage_key": storage_key,
            },
        )
        session.add(task_record)
        await session.commit()

    await engine.dispose()

    logger.info(f"Task record created: {task_id}, status=pending")

    # ---- 3. 异步唤起 Celery 任务 ----
    try:
        result = estimate_depth.delay(
            image_id=req.image_id,
            user_id=str(user_id),
            storage_key=storage_key,
            model_name=req.model,
            task_id=str(task_id),
        )
        celery_task_id = result.id
        logger.info(f"Celery task dispatched: celery_id={celery_task_id}, db_task_id={task_id}")
    except Exception as e:
        # Celery 调度失败，更新 tasks 表状态
        logger.error(f"Failed to dispatch Celery task: {e}")
        engine = create_async_engine(settings.DATABASE_URL)
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = "failed"
                task.error_message = f"Celery dispatch failed: {e}"
                await session.commit()
        await engine.dispose()

        raise HTTPException(
            status_code=500,
            detail={"error_code": "TASK_DISPATCH_FAILED", "message": str(e)},
        )

    # ---- 4. 立即响应 200 OK + task_id ----
    return DepthEstimateResponse(
        task_id=str(task_id),
        image_id=req.image_id,
        status="pending",
        estimated_time_seconds=8,
    )


@router.get("/depth/task/{task_id}", summary="查询任务状态")
async def get_task_status(task_id: str):
    """查询深度估计任务状态（优先从 Redis 缓存读取，回退到 PostgreSQL）"""
    from app.core.redis import redis_client

    # 优先从 Redis 缓存读取
    progress = await redis_client.get_task_progress(task_id)
    if progress:
        return progress

    # Redis 无缓存，回退到 PostgreSQL tasks 表
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        task_uuid = uuid.UUID(task_id)
        task = await session.get(Task, task_uuid)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        result = {
            "task_id": str(task.id),
            "status": task.status,
            "progress": float(task.progress),
            "type": task.type,
            "error_message": task.error_message,
            "result": task.result,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }

    await engine.dispose()
    return result


@router.post("/depth/estimate-mpi", summary="同步 MPI 场景生成 (个人使用)")
async def estimate_depth_mpi(file: UploadFile = File(...)):
    """同步: 上传图片 → 深度+分割+分层 → 返回 MPI 数据

    个人使用简化版: 不走 Celery 队列, 直接同步处理返回。
    """
    import sys
    import time
    import numpy as np
    from pathlib import Path
    from PIL import Image
    from fastapi.responses import FileResponse

    # ai-models 目录加入 Python 路径
    ai_models_path = str(Path(__file__).resolve().parents[3] / "ai-models")
    if ai_models_path not in sys.path:
        sys.path.insert(0, ai_models_path)

    start_time = time.time()

    try:
        # 1. 读取上传图片
        image = Image.open(file.file)
        if image.mode != "RGB":
            image = image.convert("RGB")

        # 2. 加载深度引擎
        from model_manager import ModelManager
        manager = ModelManager()
        depth_engine = manager.get_engine("depth_anything_v2")
        depth_time_start = time.time()

        # 3. 带置信度的深度估计
        depth_result = depth_engine.predict_with_confidence(image)
        depth_time = time.time() - depth_time_start

        # 4. 尝试 SAM2 分割
        seg_time = 0
        seg_result = {"seg_mask": None, "num_layers": 3}
        try:
            available = [m["name"] for m in manager.list_available()]
            if "sam2" in available:
                seg_time_start = time.time()
                sam_engine = manager.get_engine("sam2")
                seg_result = sam_engine.predict(image)
                seg_time = time.time() - seg_time_start
        except Exception:
            pass

        # 5. 融合 + 分解
        layer_time_start = time.time()
        fused = depth_engine.fuse_with_segmentation(depth_result, seg_result)
        n_layers = min(seg_result.get("num_layers", 3), 5)
        scene_layers = depth_engine.decompose_scene(fused, image, n_layers=n_layers)

        # 6. 可选 Inpainting
        try:
            from inpaint.lama.engine import LaMaInpaintEngine
            inpaint_engine = LaMaInpaintEngine(None)  # OpenCV fallback
            for i, layer_data in enumerate(scene_layers):
                if layer_data["occlusion_mask"].sum() > 1000:
                    layer_data["texture"] = inpaint_engine.inpaint_layer(
                        layer_texture=layer_data["texture"],
                        occlusion_mask=layer_data["occlusion_mask"],
                        original_image=image,
                    )
        except Exception:
            pass

        # 7. 保存层纹理到本地磁盘
        mpi_dir = Path("data/mpi")
        mpi_dir.mkdir(parents=True, exist_ok=True)

        layer_urls = []
        for i, layer_data in enumerate(scene_layers):
            layer_path = mpi_dir / f"layer_{i}.png"
            layer_data["texture"].save(str(layer_path))
            layer_urls.append({
                "id": f"layer_{i}",
                "textureUrl": f"/api/v1/depth/mpi-file/layer_{i}.png",
                "zIndex": layer_data["z_position"],
                "motionScale": layer_data["motion_scale"],
                "parallaxDirection": "both",
                "blendMode": "premultiplied",
            })

        layer_time = time.time() - layer_time_start
        elapsed = time.time() - start_time

        return {
            "mpi_layers": layer_urls,
            "metadata": {
                "width": image.width,
                "height": image.height,
                "layerCount": len(scene_layers),
                "modelUsed": "depth_anything_v2",
                "processingTimeMs": round(elapsed * 1000, 1),
                "depthTimeMs": round(depth_time * 1000, 1),
                "segTimeMs": round(seg_time * 1000, 1),
                "layerTimeMs": round(layer_time * 1000, 1),
            },
        }

    except Exception as e:
        logger.error(f"MPI estimation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/depth/mpi-file/{filename}", summary="MPI 层纹理文件服务")
async def serve_mpi_file(filename: str):
    """提供 MPI 层纹理文件 (个人使用, 直接从磁盘读取)"""
    from fastapi.responses import FileResponse
    from pathlib import Path

    file_path = Path("data/mpi") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path), media_type="image/png")
