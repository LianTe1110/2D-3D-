"""LeiaPix AI - 分享 API

POST /api/v1/share         — 创建分享链接
GET  /api/v1/share/{id}    — 获取分享详情 (公开, 无需登录)
GET  /api/v1/share/list    — 查询用户分享列表
DELETE /api/v1/share/{id}  — 删除分享
POST /api/v1/share/{id}/embed — 获取嵌入代码
"""

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import RateLimiter
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# 默认用户 ID (开发阶段)
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ============ 请求/响应模型 ============

class CreateShareRequest(BaseModel):
    """创建分享请求"""
    scene_id: str = Field(..., description="场景 ID")
    title: str = Field(default="我的 3D 照片", description="分享标题")
    is_public: bool = Field(default=True, description="是否公开")
    allow_download: bool = Field(default=True, description="是否允许下载")
    expires_days: int | None = Field(default=None, description="过期天数 (None=永不过期)")
    animation: dict | None = Field(default=None, description="动画参数")


class ShareResponse(BaseModel):
    """分享响应"""
    share_id: str
    scene_id: str
    user_id: str
    title: str
    is_public: bool
    allow_download: bool
    view_count: int
    download_count: int
    expires_at: str | None
    created_at: str
    share_url: str
    embed_code: str
    # 场景渲染数据 (公开分享时返回, 供前端渲染)
    scene_data: dict | None = None


class ShareListResponse(BaseModel):
    """分享列表响应"""
    shares: list[ShareResponse]
    total: int


# ============ API 端点 ============

@router.post("/share", response_model=ShareResponse, summary="创建分享链接", dependencies=[Depends(RateLimiter("share_create"))])
async def create_share(req: CreateShareRequest):
    """创建公开分享链接

    流程:
    1. 校验 scene 存在且状态为 ready
    2. 从 PostgreSQL 读取场景渲染数据 (render_params, animation_params, texture_url 等)
    3. 写入 MongoDB shares 集合
    4. 返回 share_url + embed_code
    """
    from app.services.share_service import create_share as mongo_create_share

    # ---- 1. 校验 scene ----
    scene_uuid = uuid.UUID(req.scene_id)
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    scene_data = {}
    user_id = str(DEFAULT_USER_ID)

    async with async_session() as session:
        from app.models.scene import Scene
        from app.models.image import Image as ImageModel
        from app.models.depth_map import DepthMap

        result = await session.execute(
            select(Scene).where(Scene.id == scene_uuid)
        )
        scene_record = result.scalar_one_or_none()

        if scene_record is None:
            await engine.dispose()
            raise HTTPException(status_code=404, detail="场景不存在")

        if scene_record.status != "ready":
            await engine.dispose()
            raise HTTPException(status_code=409, detail=f"场景状态为 '{scene_record.status}', 需为 'ready'")

        user_id = str(scene_record.user_id)

        # ---- 2. 读取场景渲染数据 ----
        # 获取原图 URL
        image_result = await session.execute(
            select(ImageModel).where(ImageModel.id == scene_record.image_id)
        )
        image_record = image_result.scalar_one_or_none()

        # 获取深度图 URL
        depth_result = await session.execute(
            select(DepthMap).where(DepthMap.id == scene_record.depth_map_id)
        )
        depth_record = depth_result.scalar_one_or_none()

        # 组装场景数据 (供前端分享页面渲染)
        scene_data = {
            "scene_id": str(scene_record.id),
            "image_id": str(scene_record.image_id),
            "depth_map_id": str(scene_record.depth_map_id),
            "texture_url": scene_record.texture_url or (image_record.original_url if image_record else None),
            "depth_map_url": depth_record.depth_map_url if depth_record else None,
            "render_params": scene_record.render_params or {},
            "animation_params": scene_record.animation_params or {},
        }

    await engine.dispose()

    # ---- 3. 计算过期时间 ----
    expires_at = None
    if req.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=req.expires_days)

    # ---- 4. 写入 MongoDB ----
    animation_meta = req.animation or scene_data.get("animation_params", {})

    share = await mongo_create_share(
        scene_id=req.scene_id,
        user_id=user_id,
        title=req.title,
        is_public=req.is_public,
        allow_download=req.allow_download,
        expires_at=expires_at,
        metadata={
            "animation": animation_meta,
            "render_params": scene_data.get("render_params", {}),
        },
    )

    # ---- 5. 生成分享 URL 和嵌入代码 ----
    base_url = "http://localhost:3000"  # TODO: 从配置读取
    share_url = f"{base_url}/share/{share.share_id}"
    embed_code = _generate_embed_code(share.share_id, share.title)

    logger.info(f"Share created: share_id={share.share_id}, url={share_url}")

    return ShareResponse(
        share_id=share.share_id,
        scene_id=share.scene_id,
        user_id=share.user_id,
        title=share.title,
        is_public=share.is_public,
        allow_download=share.allow_download,
        view_count=share.view_count,
        download_count=share.download_count,
        expires_at=share.expires_at.isoformat() if share.expires_at else None,
        created_at=share.created_at.isoformat(),
        share_url=share_url,
        embed_code=embed_code,
        scene_data=scene_data if share.is_public else None,
    )


@router.get("/share/{share_id}", summary="获取分享详情 (公开, 无需登录)")
async def get_share(share_id: str):
    """获取分享详情 — 供 /share/:id 页面使用

    返回场景渲染数据, 前端直接挂载 Three.js 画布
    """
    from app.services.share_service import get_share_by_id, increment_view_count

    share = await get_share_by_id(share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="分享不存在或已过期")

    # 检查是否过期
    if share.expires_at and share.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="分享链接已过期")

    # 增加浏览次数
    await increment_view_count(share_id)

    # 从 PostgreSQL 读取场景渲染数据
    scene_data = await _get_scene_data(share.scene_id)

    base_url = "http://localhost:3000"
    share_url = f"{base_url}/share/{share.share_id}"

    return {
        "share_id": share.share_id,
        "scene_id": share.scene_id,
        "user_id": share.user_id,
        "title": share.title,
        "is_public": share.is_public,
        "allow_download": share.allow_download,
        "view_count": share.view_count,
        "download_count": share.download_count,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "created_at": share.created_at.isoformat(),
        "share_url": share_url,
        "scene_data": scene_data if share.is_public else None,
    }


@router.get("/share/list", summary="查询用户分享列表")
async def list_shares(user_id: str = Query(...), limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    """查询用户的分享列表"""
    from app.services.share_service import list_user_shares

    shares = await list_user_shares(user_id, limit=limit, offset=offset)

    base_url = "http://localhost:3000"
    result = []
    for share in shares:
        result.append({
            "share_id": share.share_id,
            "scene_id": share.scene_id,
            "title": share.title,
            "is_public": share.is_public,
            "allow_download": share.allow_download,
            "view_count": share.view_count,
            "download_count": share.download_count,
            "expires_at": share.expires_at.isoformat() if share.expires_at else None,
            "created_at": share.created_at.isoformat(),
            "share_url": f"{base_url}/share/{share.share_id}",
        })

    return {"shares": result, "total": len(result)}


@router.delete("/share/{share_id}", summary="删除分享")
async def delete_share(share_id: str, user_id: str = Query(...)):
    """删除分享记录 (仅创建者可删)"""
    from app.services.share_service import delete_share as mongo_delete_share

    deleted = await mongo_delete_share(share_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="分享不存在或无权删除")

    return {"message": "分享已删除"}


# ============ 工具函数 ============

def _generate_embed_code(share_id: str, title: str = "3D 照片") -> str:
    """生成 iframe 嵌入代码"""
    base_url = "http://localhost:3000"
    return (
        f'<iframe src="{base_url}/share/{share_id}" '
        f'width="640" height="480" '
        f'frameborder="0" allowfullscreen '
        f'title="{title}"></iframe>'
    )


async def _get_scene_data(scene_id: str) -> dict | None:
    """从 PostgreSQL 读取场景渲染数据"""
    try:
        scene_uuid = uuid.UUID(scene_id)
        engine = create_async_engine(settings.DATABASE_URL)
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from app.models.scene import Scene
            from app.models.image import Image as ImageModel
            from app.models.depth_map import DepthMap

            result = await session.execute(
                select(Scene).where(Scene.id == scene_uuid)
            )
            scene_record = result.scalar_one_or_none()
            if not scene_record:
                await engine.dispose()
                return None

            # 获取原图 URL
            image_result = await session.execute(
                select(ImageModel).where(ImageModel.id == scene_record.image_id)
            )
            image_record = image_result.scalar_one_or_none()

            # 获取深度图 URL
            depth_result = await session.execute(
                select(DepthMap).where(DepthMap.id == scene_record.depth_map_id)
            )
            depth_record = depth_result.scalar_one_or_none()

            scene_data = {
                "scene_id": str(scene_record.id),
                "image_id": str(scene_record.image_id),
                "depth_map_id": str(scene_record.depth_map_id),
                "texture_url": scene_record.texture_url or (image_record.original_url if image_record else None),
                "depth_map_url": depth_record.depth_map_url if depth_record else None,
                "render_params": scene_record.render_params or {},
                "animation_params": scene_record.animation_params or {},
            }

        await engine.dispose()
        return scene_data

    except Exception as e:
        logger.error(f"Failed to get scene data: {e}")
        return None
