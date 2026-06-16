"""LeiaPix AI - 3D 场景数据初始化 API

POST /api/v1/render/3d
- 接收 image_id 和 depth_map_id
- 校验原图和深度图均已生成完毕
- 组装基础 3D 渲染元数据 (fov, parallax_scale, etc.)
- 序列化为 JSON 写入 MinIO scenes/ 目录
- 在 PostgreSQL scenes 表插入记录
"""

import io
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.depth_map import DepthMap
from app.models.image import Image as ImageModel
from app.models.scene import Scene
from app.services.storage_service import get_minio_client
from app.api.deps import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- 默认 3D 渲染参数 ----
DEFAULT_RENDER_PARAMS = {
    "fov": 60,                    # 视场角 (度)
    "parallax_scale": 1.0,        # 视差缩放倍率
    "near_plane": 0.1,            # 近裁剪面
    "far_plane": 100.0,           # 远裁剪面
    "camera_distance": 2.0,       # 相机距离
    "mesh_subdivision": 1,        # 网格细分级别
}

DEFAULT_ANIMATION_PARAMS = {
    "type": "none",               # none / sway / breathe / orbit / dolly
    "amplitude": 0.02,            # 振幅
    "speed": 1.0,                 # 速度
    "duration": 5.0,              # 时长 (秒)
    "direction": "horizontal",    # horizontal / vertical / both
}


class Render3DRequest(BaseModel):
    image_id: str
    depth_map_id: str


class Render3DResponse(BaseModel):
    scene_id: str
    status: str
    scene_data_url: str
    render_params: dict
    animation_params: dict


@router.post("/render/3d", summary="3D 场景数据初始化", response_model=Render3DResponse, dependencies=[Depends(RateLimiter("render"))])
async def init_3d_scene(req: Render3DRequest):
    """基于原图 + 深度图初始化 3D 场景元数据"""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    image_id_uuid = uuid.UUID(req.image_id)
    depth_map_id_uuid = uuid.UUID(req.depth_map_id)

    async with async_session() as session:
        # ---- 1. 校验原图存在且状态正确 ----
        image_result = await session.execute(
            select(ImageModel).where(ImageModel.id == image_id_uuid)
        )
        image_record = image_result.scalar_one_or_none()
        if image_record is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "IMAGE_NOT_FOUND", "message": f"Image {req.image_id} not found"},
            )

        # ---- 2. 校验深度图存在且状态为 ready ----
        depth_result = await session.execute(
            select(DepthMap).where(DepthMap.id == depth_map_id_uuid)
        )
        depth_record = depth_result.scalar_one_or_none()
        if depth_record is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "DEPTH_MAP_NOT_FOUND",
                    "message": f"Depth map {req.depth_map_id} not found",
                },
            )

        if depth_record.status != "ready":
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "DEPTH_MAP_NOT_READY",
                    "message": f"Depth map status is '{depth_record.status}', expected 'ready'",
                },
            )

        # ---- 3. 校验深度图属于该图片 ----
        if depth_record.image_id != image_id_uuid:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "MISMATCH",
                    "message": "Depth map does not belong to the specified image",
                },
            )

        user_id = image_record.user_id

    await engine.dispose()

    logger.info(
        f"Init 3D scene: image={req.image_id}, depth_map={req.depth_map_id}, user={user_id}"
    )

    # ---- 4. 组装 3D 渲染元数据 ----
    scene_id = uuid.uuid4()
    scene_metadata = {
        "scene_id": str(scene_id),
        "image": {
            "id": str(image_id_uuid),
            "width": image_record.width,
            "height": image_record.height,
            "format": image_record.format,
            "original_url": image_record.original_url,
            "storage_key": image_record.storage_key,
        },
        "depth_map": {
            "id": str(depth_map_id_uuid),
            "storage_key": depth_record.storage_key,
            "depth_map_url": depth_record.depth_map_url,
            "model_used": depth_record.model_used,
            "processing_time_ms": depth_record.processing_time_ms,
        },
        "render": DEFAULT_RENDER_PARAMS,
        "animation": DEFAULT_ANIMATION_PARAMS,
    }

    # ---- 5. 序列化为 JSON 写入 MinIO scenes/ 目录 ----
    scene_json = json.dumps(scene_metadata, ensure_ascii=False, indent=2)
    scene_bytes = scene_json.encode("utf-8")
    scene_storage_key = f"scenes/{user_id}/{scene_id}/scene.json"

    client = get_minio_client()
    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=scene_storage_key,
        data=io.BytesIO(scene_bytes),
        length=len(scene_bytes),
        content_type="application/json",
    )

    scene_data_url = f"/api/v1/files/{scene_storage_key}"
    logger.info(f"Scene metadata uploaded: {scene_storage_key} ({len(scene_bytes)} bytes)")

    # ---- 6. 在 PostgreSQL scenes 表插入记录 ----
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        scene_record = Scene(
            id=scene_id,
            user_id=user_id,
            image_id=image_id_uuid,
            depth_map_id=depth_map_id_uuid,
            scene_data_url=scene_data_url,
            texture_url=image_record.original_url,
            render_params=DEFAULT_RENDER_PARAMS,
            animation_params=DEFAULT_ANIMATION_PARAMS,
            status="ready",
        )
        session.add(scene_record)
        await session.commit()

    await engine.dispose()

    logger.info(f"Scene created: {scene_id}, status=ready")

    return Render3DResponse(
        scene_id=str(scene_id),
        status="ready",
        scene_data_url=scene_data_url,
        render_params=DEFAULT_RENDER_PARAMS,
        animation_params=DEFAULT_ANIMATION_PARAMS,
    )


@router.get("/render/scene/{scene_id}", summary="查询场景详情")
async def get_scene(scene_id: str):
    """查询 3D 场景详情"""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        scene_uuid = uuid.UUID(scene_id)
        scene = await session.get(Scene, scene_uuid)
        if scene is None:
            raise HTTPException(status_code=404, detail="Scene not found")

        result = {
            "scene_id": str(scene.id),
            "user_id": str(scene.user_id),
            "image_id": str(scene.image_id),
            "depth_map_id": str(scene.depth_map_id),
            "scene_data_url": scene.scene_data_url,
            "texture_url": scene.texture_url,
            "render_params": scene.render_params,
            "animation_params": scene.animation_params,
            "status": scene.status,
            "created_at": scene.created_at.isoformat() if scene.created_at else None,
            "updated_at": scene.updated_at.isoformat() if scene.updated_at else None,
        }

    await engine.dispose()
    return result
