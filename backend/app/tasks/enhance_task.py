"""LeiaPix AI - 图像增强异步任务

完整生命周期:
    前端传入 image_id → 从 MinIO 下载原图 → 调用 Real-ESRGAN 推理
    → 将增强图上传至 MinIO enhanced/ → 更新 PostgreSQL images.enhanced_url
    → 写入 Redis 进度 → WebSocket 推送

队列: gpu_enhance (并发上限 1, 超分极其消耗显存)
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.celery_app import celery_app
from app.core.redis import redis_client

logger = logging.getLogger(__name__)

# ai-models 目录加入 Python 路径
AI_MODELS_PATH = str(Path(__file__).resolve().parents[3] / "ai-models")
if AI_MODELS_PATH not in sys.path:
    sys.path.insert(0, AI_MODELS_PATH)


@celery_app.task(
    bind=True,
    name="app.tasks.enhance_task.enhance_image",
    max_retries=2,
    time_limit=120,
    soft_time_limit=110,
    queue="gpu_enhance",
)
def enhance_image(
    self,
    image_id: str,
    user_id: str,
    storage_key: str,
    enhance_type: str = "super_resolution",
    model_name: str = "real_esrgan_x4plus",
    scale: int = 4,
):
    """异步图像增强任务

    Args:
        image_id: 图片 ID
        user_id: 用户 ID
        storage_key: MinIO 原图存储路径
        enhance_type: 增强类型 (super_resolution / denoise)
        model_name: 增强模型名称
        scale: 超分倍率
    """
    task_id = self.request.id

    async def _run():
        # ========== 0. GPU 显存检查 ==========
        from app.core.celery_app import check_gpu_memory, GPU_MAX_MEMORY_MB
        max_mem = GPU_MAX_MEMORY_MB.get("gpu_enhance", 10240)
        if not check_gpu_memory(max_mem):
            raise RuntimeError(f"GPU 显存不足, 当前增强任务需要至少 {max_mem}MB 可用显存")

        # ========== 1. 初始化任务状态 ==========
        await redis_client.set_task_progress(
            task_id=task_id, status="processing", progress=0,
            task_type="enhance", user_id=user_id,
        )
        await _update_task_status(task_id, "processing")

        try:
            # ========== 2. 从 MinIO 下载原图 ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=10,
                task_type="enhance", user_id=user_id,
                message="下载原图中...",
            )

            from app.services.storage_service import download_image
            image = download_image(storage_key)
            logger.info(f"Downloaded image for enhance: {storage_key}, size={image.size}")

            # ========== 3. 加载推理引擎 ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=20,
                task_type="enhance", user_id=user_id,
                message="加载超分模型...",
            )

            from model_manager import ModelManager
            manager = ModelManager()
            engine = manager.get_engine(model_name)

            # ========== 4. 执行超分辨率推理 ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=40,
                task_type="enhance", user_id=user_id,
                message="超分辨率推理中...",
            )

            start = time.time()
            enhanced_image = engine.enhance(image)
            elapsed_ms = (time.time() - start) * 1000

            logger.info(
                f"Enhance completed: model={model_name}, "
                f"time={elapsed_ms:.0f}ms, "
                f"input={image.size}, output={enhanced_image.size}"
            )

            # ========== 5. 上传增强图到 MinIO ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=80,
                task_type="enhance", user_id=user_id,
                message="上传增强图...",
            )

            from app.services.storage_service import upload_enhanced_image, get_enhanced_url
            enhanced_storage_key = upload_enhanced_image(user_id, image_id, enhanced_image)
            enhanced_url = get_enhanced_url(enhanced_storage_key)

            logger.info(f"Enhanced image uploaded: {enhanced_storage_key}")

            # ========== 6. 更新 PostgreSQL images.enhanced_url ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=90,
                task_type="enhance", user_id=user_id,
                message="更新数据库...",
            )

            await _update_database(
                image_id=image_id,
                enhanced_url=enhanced_url,
                enhanced_width=enhanced_image.size[0],
                enhanced_height=enhanced_image.size[1],
            )

            # ========== 7. 任务完成 ==========
            await redis_client.set_task_progress(
                task_id=task_id,
                status="completed",
                progress=100,
                task_type="enhance",
                user_id=user_id,
                message="增强完成",
                result={
                    "image_id": image_id,
                    "enhanced_url": enhanced_url,
                    "enhanced_storage_key": enhanced_storage_key,
                    "enhance_type": enhance_type,
                    "model_used": model_name,
                    "scale": scale,
                    "original_size": list(image.size),
                    "enhanced_size": list(enhanced_image.size),
                    "processing_time_ms": round(elapsed_ms, 1),
                },
            )
            await _update_task_status(
                task_id, "completed",
                result={
                    "image_id": image_id,
                    "enhanced_url": enhanced_url,
                    "enhanced_storage_key": enhanced_storage_key,
                    "enhance_type": enhance_type,
                    "model_used": model_name,
                    "scale": scale,
                    "original_size": list(image.size),
                    "enhanced_size": list(enhanced_image.size),
                    "processing_time_ms": round(elapsed_ms, 1),
                },
            )

        except Exception as e:
            logger.error(f"Enhance failed for image {image_id}: {e}")
            await redis_client.set_task_progress(
                task_id=task_id,
                status="failed",
                progress=0,
                task_type="enhance",
                user_id=user_id,
                error_message=str(e),
            )
            await _update_task_status(task_id, "failed", error_message=str(e))
            raise self.retry(exc=e, countdown=60)

    # 在同步 Celery 任务中运行异步代码
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


async def _update_task_status(
    task_id: str,
    status: str,
    result: dict | None = None,
    error_message: str | None = None,
):
    """更新 PostgreSQL tasks 表状态"""
    import uuid
    from datetime import datetime
    from app.core.config import get_settings
    from app.models.task import Task as TaskModel

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        task = await session.get(TaskModel, uuid.UUID(task_id))
        if task is None:
            logger.warning(f"Task {task_id} not found in DB, skip status update")
            await engine.dispose()
            return

        task.status = status
        if status == "processing" and task.started_at is None:
            task.started_at = datetime.utcnow()
        if status == "completed":
            task.progress = 100
            task.completed_at = datetime.utcnow()
        if result:
            task.result = result
        if error_message:
            task.error_message = error_message
        await session.commit()

    await engine.dispose()


async def _update_database(
    image_id: str,
    enhanced_url: str,
    enhanced_width: int,
    enhanced_height: int,
):
    """更新 PostgreSQL images 表: enhanced_url + status"""
    import uuid
    from app.core.config import get_settings
    from app.models.image import Image as ImageModel

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        image_record = await session.get(ImageModel, uuid.UUID(image_id))
        if image_record:
            image_record.enhanced_url = enhanced_url
            image_record.status = "enhanced"
        await session.commit()

    await engine.dispose()
