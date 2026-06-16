"""LeiaPix AI - 深度估计 API

POST /api/v1/depth/estimate
- 从 PostgreSQL 查询 image 记录，获取 storage_key
- 向 tasks 表插入 status='pending' 记录
- 通过 .delay() 异步唤起 Celery 深度估计任务
- 立即响应 200 OK + task_id

GET /api/v1/depth/task/{task_id}
- 从 Redis 查询任务进度
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
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
