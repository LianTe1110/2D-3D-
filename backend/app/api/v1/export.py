"""LeiaPix AI - 媒体导出 API

POST /api/v1/export
- 校验 scene 记录存在且状态为 ready
- 向 exports 表插入记录 (status=processing)
- 向 tasks 表插入记录 (type=export, status=pending)
- 通过 .delay() 异步唤起 Celery 导出任务至 export 队列
- 立即响应 200 OK + task_id

GET /api/v1/export/task/{task_id}
- Redis 优先 → PostgreSQL 回退
"""

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import RateLimiter
from app.core.config import get_settings
from app.models.scene import Scene
from app.models.export import Export
from app.models.task import Task

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# 默认用户 ID (开发阶段)
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ============ 请求/响应模型 ============

class AnimationConfig(BaseModel):
    """动画参数配置"""
    type: str = Field(default="swing", description="动画类型: swing/zoom/rotate/parallax/dolly")
    amplitude: float = Field(default=0.5, ge=0.1, le=2.0, description="振幅")
    speed: float = Field(default=1.0, ge=0.1, le=5.0, description="速度倍率")


class ExportRequest(BaseModel):
    """导出请求"""
    scene_id: str = Field(..., description="场景 ID")
    format: str = Field(default="mp4", description="导出格式: mp4 / gif / depth_png")
    params: dict = Field(
        default_factory=lambda: {
            "resolution": "1080p",
            "fps": 30,
            "duration_seconds": 5,
            "animation": {
                "type": "swing",
                "amplitude": 0.5,
                "speed": 1.0,
            },
        },
        description="导出参数",
    )


class ExportResponse(BaseModel):
    """导出响应"""
    task_id: str
    export_id: str
    scene_id: str
    format: str
    status: str
    estimated_time_seconds: int


# ============ 分辨率映射 ============

RESOLUTION_MAP = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}

GIF_SIZE_MAP = {
    "320": 320,
    "480": 480,
    "640": 640,
}


# ============ API 端点 ============

@router.post("/export", response_model=ExportResponse, summary="导出视频/GIF/深度图", dependencies=[Depends(RateLimiter("export"))])
async def create_export(req: ExportRequest):
    """触发媒体导出异步任务

    流程:
    1. 校验 scene 存在且状态为 ready
    2. 校验导出参数合法性
    3. 向 exports 表插入记录 (status=processing)
    4. 向 tasks 表插入记录 (type=export, status=pending)
    5. 投递 Celery 任务至 export 队列
    6. 返回 task_id + export_id
    """
    # ---- 1. 校验 scene ----
    scene_uuid = uuid.UUID(req.scene_id)
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            select(Scene).where(Scene.id == scene_uuid)
        )
        scene_record = result.scalar_one_or_none()

    if scene_record is None:
        await engine.dispose()
        raise HTTPException(
            status_code=404,
            detail={"error_code": "SCENE_NOT_FOUND", "message": f"Scene {req.scene_id} not found"},
        )

    if scene_record.status != "ready":
        await engine.dispose()
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SCENE_NOT_READY",
                "message": f"Scene status is '{scene_record.status}', must be 'ready' to export",
            },
        )

    user_id = scene_record.user_id
    image_id = scene_record.image_id
    depth_map_id = scene_record.depth_map_id
    render_params = scene_record.render_params or {}
    animation_params = scene_record.animation_params or {}

    await engine.dispose()

    # ---- 2. 校验导出参数 ----
    export_format = req.format.lower()
    if export_format not in ("mp4", "gif", "depth_png"):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_FORMAT", "message": f"Unsupported format: {export_format}"},
        )

    params = req.params
    resolution = params.get("resolution", "1080p")
    fps = params.get("fps", 30)
    duration_seconds = params.get("duration_seconds", 5)
    animation = params.get("animation", {})

    # 参数范围校验
    if export_format == "mp4":
        if resolution not in RESOLUTION_MAP:
            raise HTTPException(status_code=400, detail=f"Invalid resolution: {resolution}")
        if fps not in (24, 30, 60):
            raise HTTPException(status_code=400, detail=f"Invalid fps: {fps}")
        if not (1 <= duration_seconds <= 30):
            raise HTTPException(status_code=400, detail="duration_seconds must be 1-30")
    elif export_format == "gif":
        gif_width = params.get("gif_width", "480")
        if str(gif_width) not in GIF_SIZE_MAP:
            raise HTTPException(status_code=400, detail=f"Invalid gif_width: {gif_width}")
        if fps not in (10, 15, 24):
            raise HTTPException(status_code=400, detail=f"Invalid gif fps: {fps}")
        if not (1 <= duration_seconds <= 15):
            raise HTTPException(status_code=400, detail="GIF duration_seconds must be 1-15")

    # ---- 3. 插入 exports 表 ----
    export_id = uuid.uuid4()
    task_id = uuid.uuid4()

    # 导出文件过期时间: MP4/GIF 7天, depth_png 30天
    if export_format == "depth_png":
        expires_at = datetime.utcnow() + timedelta(days=30)
    else:
        expires_at = datetime.utcnow() + timedelta(days=7)

    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        export_record = Export(
            id=export_id,
            scene_id=scene_uuid,
            user_id=user_id,
            format=export_format,
            resolution=resolution,
            duration_seconds=duration_seconds,
            status="processing",
            expires_at=expires_at,
        )
        session.add(export_record)

        # ---- 4. 插入 tasks 表 ----
        task_record = Task(
            id=task_id,
            user_id=user_id,
            type="export",
            status="pending",
            progress=0,
            input_params={
                "export_id": str(export_id),
                "scene_id": req.scene_id,
                "format": export_format,
                "resolution": resolution,
                "fps": fps,
                "duration_seconds": duration_seconds,
                "animation": animation,
                "image_id": str(image_id),
                "depth_map_id": str(depth_map_id),
                "render_params": render_params,
                "animation_params": animation_params,
            },
        )
        session.add(task_record)
        await session.commit()

    await engine.dispose()

    logger.info(f"Export record created: export_id={export_id}, task_id={task_id}, format={export_format}")

    # ---- 5. 投递 Celery 任务 ----
    try:
        from app.tasks.export_task import export_video
        export_video.delay(
            export_id=str(export_id),
            task_id=str(task_id),
            scene_id=req.scene_id,
            user_id=str(user_id),
            export_format=export_format,
            resolution=resolution,
            fps=fps,
            duration_seconds=duration_seconds,
            animation=animation,
            image_id=str(image_id),
            depth_map_id=str(depth_map_id),
            render_params=render_params,
            animation_params=animation_params,
        )
        logger.info(f"Celery export task dispatched: task_id={task_id}")
    except Exception as e:
        logger.error(f"Failed to dispatch Celery export task: {e}")
        # 更新任务状态为失败
        engine = create_async_engine(settings.DATABASE_URL)
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = "failed"
                task.error_message = f"Celery dispatch failed: {e}"
                await session.commit()
            export = await session.get(Export, export_id)
            if export:
                export.status = "failed"
                await session.commit()
        await engine.dispose()

        raise HTTPException(
            status_code=500,
            detail={"error_code": "TASK_DISPATCH_FAILED", "message": str(e)},
        )

    # ---- 6. 返回响应 ----
    estimated_time = {
        "mp4": 20,
        "gif": 30,
        "depth_png": 5,
    }.get(export_format, 20)

    return ExportResponse(
        task_id=str(task_id),
        export_id=str(export_id),
        scene_id=req.scene_id,
        format=export_format,
        status="processing",
        estimated_time_seconds=estimated_time,
    )


@router.get("/export/task/{task_id}", summary="查询导出任务状态")
async def get_export_task_status(task_id: str):
    """查询导出任务进度 (Redis 优先 → PostgreSQL 回退)"""
    from app.core.redis import redis_client

    # 优先从 Redis 缓存读取
    cached = await redis_client.get_task_progress(task_id)
    if cached:
        # 补充 export 记录信息
        export_id = cached.get("export_id")
        if export_id:
            engine = create_async_engine(settings.DATABASE_URL)
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as session:
                export = await session.get(Export, uuid.UUID(export_id))
                if export:
                    cached["download_url"] = export.download_url
                    cached["file_size_bytes"] = export.file_size_bytes
                    cached["expires_at"] = export.expires_at.isoformat() if export.expires_at else None
                    cached["format"] = export.format
            await engine.dispose()
        return cached

    # Redis 无缓存，回退到 PostgreSQL
    task_uuid = uuid.UUID(task_id)
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        task = await session.get(Task, task_uuid)
        if task is None:
            await engine.dispose()
            raise HTTPException(status_code=404, detail="Task not found")

        result = {
            "task_id": str(task.id),
            "status": task.status,
            "progress": float(task.progress or 0),
            "type": task.type,
            "error_message": task.error_message,
            "result": task.result,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }

        # 补充 export 记录信息
        if task.result and "export_id" in task.result:
            export = await session.get(Export, uuid.UUID(task.result["export_id"]))
            if export:
                result["download_url"] = export.download_url
                result["file_size_bytes"] = export.file_size_bytes
                result["expires_at"] = export.expires_at.isoformat() if export.expires_at else None
                result["format"] = export.format
        elif task.input_params and "export_id" in task.input_params:
            export = await session.get(Export, uuid.UUID(task.input_params["export_id"]))
            if export:
                result["download_url"] = export.download_url
                result["file_size_bytes"] = export.file_size_bytes
                result["expires_at"] = export.expires_at.isoformat() if export.expires_at else None
                result["format"] = export.format

    await engine.dispose()
    return result


@router.get("/export/{export_id}", summary="查询导出记录")
async def get_export(export_id: str):
    """查询导出记录详情"""
    export_uuid = uuid.UUID(export_id)
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        export = await session.get(Export, export_uuid)
        if export is None:
            await engine.dispose()
            raise HTTPException(status_code=404, detail="Export not found")

        result = {
            "export_id": str(export.id),
            "scene_id": str(export.scene_id),
            "user_id": str(export.user_id),
            "format": export.format,
            "resolution": export.resolution,
            "duration_seconds": export.duration_seconds,
            "file_size_bytes": export.file_size_bytes,
            "download_url": export.download_url,
            "storage_key": export.storage_key,
            "expires_at": export.expires_at.isoformat() if export.expires_at else None,
            "status": export.status,
            "created_at": export.created_at.isoformat() if export.created_at else None,
        }

    await engine.dispose()
    return result
