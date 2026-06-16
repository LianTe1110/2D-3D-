"""LeiaPix AI - 图像增强 API

提供超分辨率 / 前景增强等图像增强服务。
"""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import RateLimiter
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


class EnhanceRequest(BaseModel):
    """图像增强请求"""
    image_id: str = Field(..., description="图片 ID")
    enhance_type: str = Field(
        default="super_resolution",
        description="增强类型: super_resolution / denoise",
    )
    model: str = Field(
        default="real_esrgan_x4plus",
        description="增强模型: real_esrgan_x4plus",
    )
    scale: int = Field(default=4, description="超分倍率 (2/4)")


class EnhanceResponse(BaseModel):
    """图像增强响应"""
    task_id: str
    image_id: str
    status: str
    enhance_type: str
    estimated_time_seconds: int


@router.post("/enhance", response_model=EnhanceResponse, summary="图像增强")
async def enhance_image(req: EnhanceRequest):
    """触发图像增强任务 (超分辨率 / 去噪)

    将任务投递至 gpu_enhance 队列 (并发上限 1)
    """
    from sqlalchemy import select
    from app.core.database import get_async_session
    from app.models.image import Image as ImageModel
    from app.models.task import Task

    image_uuid = uuid.UUID(req.image_id)

    async for session in get_async_session():
        # 1. 校验图片存在
        result = await session.execute(
            select(ImageModel).where(ImageModel.id == image_uuid)
        )
        image_record = result.scalar_one_or_none()
        if not image_record:
            raise HTTPException(status_code=404, detail="图片不存在")

        # 2. 校验图片状态 (uploaded / depth_completed / enhanced 均可)
        if image_record.status not in ("uploaded", "depth_completed", "enhanced"):
            raise HTTPException(
                status_code=409,
                detail=f"图片状态 {image_record.status} 不可执行增强",
            )

        # 3. 插入 tasks 表
        task = Task(
            user_id=image_record.user_id,
            task_type="enhance",
            status="pending",
            input_params={
                "image_id": req.image_id,
                "enhance_type": req.enhance_type,
                "model": req.model,
                "scale": req.scale,
                "storage_key": image_record.storage_key,
            },
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        task_id = str(task.id)

        # 4. 投递 Celery 异步任务至 gpu_enhance 队列
        try:
            from app.tasks.enhance_task import enhance_image as enhance_celery_task
            enhance_celery_task.delay(
                image_id=req.image_id,
                user_id=str(image_record.user_id),
                storage_key=image_record.storage_key,
                enhance_type=req.enhance_type,
                model_name=req.model,
                scale=req.scale,
            )
        except Exception as e:
            task.status = "failed"
            task.error_message = f"Celery 调度失败: {str(e)}"
            await session.commit()
            raise HTTPException(status_code=500, detail=f"任务调度失败: {str(e)}")

        return EnhanceResponse(
            task_id=task_id,
            image_id=req.image_id,
            status="pending",
            enhance_type=req.enhance_type,
            estimated_time_seconds=30,
        )


@router.get("/enhance/task/{task_id}", summary="查询增强任务状态")
async def get_enhance_task_status(task_id: str):
    """查询增强任务进度"""
    from app.core.redis import redis_client

    # 优先从 Redis 缓存读取
    cached = await redis_client.get_task_progress(task_id)
    if cached:
        return cached

    # 回退到数据库
    from sqlalchemy import select
    from app.core.database import get_async_session
    from app.models.task import Task

    task_uuid = uuid.UUID(task_id)
    async for session in get_async_session():
        result = await session.execute(
            select(Task).where(Task.id == task_uuid)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        return {
            "task_id": task_id,
            "status": task.status,
            "progress": task.progress or 0,
            "type": task.task_type,
            "error_message": task.error_message,
            "result": task.result,
            "started_at": str(task.started_at) if task.started_at else None,
            "completed_at": str(task.completed_at) if task.completed_at else None,
        }
