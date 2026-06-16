"""LeiaPix AI - 深度估计异步任务

完整生命周期:
    前端传入 image_id → 从 MinIO 下载原图 → 调用推理引擎生成深度图
    → 双边滤波后处理 → 将结果 PNG 上传至 MinIO depth_maps/
    → 更新 PostgreSQL 状态 → 写入 Redis 进度
"""

import asyncio
import logging
import sys
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
    name="app.tasks.depth_task.estimate_depth",
    max_retries=3,
    time_limit=60,
    soft_time_limit=55,
)
def estimate_depth(
    self,
    image_id: str,
    user_id: str,
    storage_key: str,
    model_name: str = "depth_anything_v2",
    task_id: str | None = None,
):
    """异步深度估计任务

    Args:
        image_id: 图片 ID
        user_id: 用户 ID
        storage_key: MinIO 原图存储路径 (如 images/original/{user_id}/{image_id}.jpg)
        model_name: 使用的深度估计模型名称
        task_id: DB 中的 task_id (由 API 层传入，用于状态同步)
    """
    # 优先使用 API 层传入的 DB task_id，回退到 Celery request.id
    if not task_id:
        task_id = self.request.id

    async def _run():
        # ========== 0. GPU 显存检查 ==========
        from app.core.celery_app import check_gpu_memory, GPU_MAX_MEMORY_MB
        max_mem = GPU_MAX_MEMORY_MB.get("gpu_depth", 8192)
        if not check_gpu_memory(max_mem):
            raise RuntimeError(f"GPU 显存不足, 当前任务需要至少 {max_mem}MB 可用显存")

        # ========== 1. 初始化任务状态 ==========
        await redis_client.set_task_progress(
            task_id=task_id, status="processing", progress=0,
            task_type="depth", user_id=user_id,
        )
        await _update_task_status(task_id, "processing")

        try:
            # ========== 2. 从 MinIO 下载原图 ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=10,
                task_type="depth", user_id=user_id,
            )

            from app.services.storage_service import download_image
            image = download_image(storage_key)
            logger.info(f"Downloaded original image: {storage_key}, size={image.size}")

            # ========== 3. 加载推理引擎 ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=30,
                task_type="depth", user_id=user_id,
            )

            from model_manager import ModelManager
            manager = ModelManager()
            engine = manager.get_engine(model_name)

            # ========== 4. 执行深度估计推理 ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=50,
                task_type="depth", user_id=user_id,
            )

            import time
            start = time.time()
            depth_map_image = engine.predict_depth_as_image(image)
            elapsed_ms = (time.time() - start) * 1000

            logger.info(
                f"Depth estimation completed: model={model_name}, "
                f"time={elapsed_ms:.0f}ms, output_size={depth_map_image.size}"
            )

            # ========== 5. 上传深度图 PNG 到 MinIO ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=80,
                task_type="depth", user_id=user_id,
            )

            from app.services.storage_service import upload_depth_map, get_depth_map_url
            depth_storage_key = upload_depth_map(user_id, image_id, depth_map_image)
            depth_url = get_depth_map_url(depth_storage_key)

            logger.info(f"Depth map uploaded: {depth_storage_key}")

            # ========== 6. 更新 PostgreSQL 数据库状态 ==========
            await redis_client.set_task_progress(
                task_id=task_id, status="processing", progress=90,
                task_type="depth", user_id=user_id,
            )

            depth_map_id = await _update_database(
                image_id=image_id,
                user_id=user_id,
                depth_storage_key=depth_storage_key,
                depth_url=depth_url,
                model_name=model_name,
                elapsed_ms=elapsed_ms,
            )

            # ========== 7. 任务完成 ==========
            result_data = {
                "image_id": image_id,
                "depth_map_id": depth_map_id,
                "depth_storage_key": depth_storage_key,
                "depth_url": depth_url,
                "model_used": model_name,
                "processing_time_ms": round(elapsed_ms, 1),
            }
            await redis_client.set_task_progress(
                task_id=task_id,
                status="completed",
                progress=100,
                task_type="depth",
                user_id=user_id,
                result=result_data,
            )
            await _update_task_status(
                task_id, "completed",
                result=result_data,
            )

        except Exception as e:
            logger.error(f"Depth estimation failed for image {image_id}: {e}")
            await redis_client.set_task_progress(
                task_id=task_id,
                status="failed",
                progress=0,
                task_type="depth",
                user_id=user_id,
                error_message=str(e),
            )
            await _update_task_status(task_id, "failed", error_message=str(e))
            raise self.retry(exc=e, countdown=30)

    # 在同步 Celery 任务中运行异步代码
    # 每次任务创建新 event loop，并重置 redis_client 连接池
    # (aioredis 连接池绑定到创建时的 loop，loop.close() 后连接池失效)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    redis_client._pool = None  # 重置连接池，让下次调用时在新 loop 上创建
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
    user_id: str,
    depth_storage_key: str,
    depth_url: str,
    model_name: str,
    elapsed_ms: float,
) -> str:
    """更新 PostgreSQL 数据库: depth_maps 表 + images 表状态

    Returns:
        depth_map_id: 新创建的 depth_map 记录 ID
    """
    import uuid
    from app.core.config import get_settings
    from app.models.depth_map import DepthMap
    from app.models.image import Image as ImageModel

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. 创建 depth_maps 记录
        depth_map = DepthMap(
            image_id=uuid.UUID(image_id),
            model_used=model_name,
            storage_key=depth_storage_key,
            depth_map_url=depth_url,
            processing_time_ms=round(elapsed_ms, 1),
            params={"bilateral_filter": {"d": 9, "sigma_color": 75, "sigma_space": 75}},
            status="ready",
        )
        session.add(depth_map)

        # 2. 更新 images 表处理状态
        image_record = await session.get(ImageModel, uuid.UUID(image_id))
        if image_record:
            image_record.status = "depth_completed"

        await session.commit()
        depth_map_id = str(depth_map.id)
    await engine.dispose()
    return depth_map_id
