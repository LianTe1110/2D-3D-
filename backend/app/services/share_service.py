"""LeiaPix AI - MongoDB 分享服务

使用 motor (异步 MongoDB 驱动) + Beanie ODM 操作 shares 集合。
"""

import logging
import secrets
import string
from datetime import datetime
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.models.share import Share

logger = logging.getLogger(__name__)

# ============ MongoDB 客户端单例 ============

_client: AsyncIOMotorClient | None = None
_beanie_initialized = False


async def get_mongo_client() -> AsyncIOMotorClient:
    """获取 MongoDB 异步客户端"""
    global _client, _beanie_initialized
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.MONGO_URI)
        logger.info(f"MongoDB client created: {settings.MONGO_URI}")

    if not _beanie_initialized:
        settings = get_settings()
        db = _client[settings.MONGO_DB]
        await init_beanie(database=db, document_models=[Share])
        _beanie_initialized = True
        logger.info(f"Beanie ODM initialized: db={settings.MONGO_DB}")

    return _client


async def close_mongo_client():
    """关闭 MongoDB 连接"""
    global _client, _beanie_initialized
    if _client:
        _client.close()
        _client = None
        _beanie_initialized = False
        logger.info("MongoDB client closed")


# ============ share_id 生成 ============

ALPHABET = string.ascii_lowercase + string.digits


def generate_share_id() -> str:
    """生成随机加密的 share_id, 格式: shr_xxxxxx (8 位随机字符)"""
    random_part = ''.join(secrets.choice(ALPHABET) for _ in range(8))
    return f"shr_{random_part}"


# ============ 分享 CRUD 操作 ============

async def create_share(
    scene_id: str,
    user_id: str,
    title: str = "我的 3D 照片",
    is_public: bool = True,
    allow_download: bool = True,
    expires_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> Share:
    """创建分享记录

    Args:
        scene_id: 关联场景 ID
        user_id: 创建者用户 ID
        title: 分享标题
        is_public: 是否公开
        allow_download: 是否允许下载
        expires_at: 过期时间
        metadata: 附加元数据 (动画参数等)

    Returns:
        Share 文档对象
    """
    await get_mongo_client()

    share_id = generate_share_id()

    # 确保 share_id 唯一
    while await Share.find_one(Share.share_id == share_id):
        share_id = generate_share_id()

    share = Share(
        share_id=share_id,
        scene_id=scene_id,
        user_id=user_id,
        title=title,
        is_public=is_public,
        allow_download=allow_download,
        expires_at=expires_at,
        metadata=metadata or {},
    )

    await share.insert()
    logger.info(f"Share created: share_id={share_id}, scene_id={scene_id}")
    return share


async def get_share_by_id(share_id: str) -> Share | None:
    """根据 share_id 查询分享记录"""
    await get_mongo_client()
    return await Share.find_one(Share.share_id == share_id)


async def increment_view_count(share_id: str) -> None:
    """增加浏览次数"""
    await get_mongo_client()
    share = await Share.find_one(Share.share_id == share_id)
    if share:
        share.view_count += 1
        await share.save()


async def increment_download_count(share_id: str) -> None:
    """增加下载次数"""
    await get_mongo_client()
    share = await Share.find_one(Share.share_id == share_id)
    if share:
        share.download_count += 1
        await share.save()


async def list_user_shares(user_id: str, limit: int = 20, offset: int = 0) -> list[Share]:
    """查询用户的分享列表"""
    await get_mongo_client()
    return await Share.find(Share.user_id == user_id).sort("-created_at").skip(offset).limit(limit).to_list()


async def delete_share(share_id: str, user_id: str) -> bool:
    """删除分享记录 (仅创建者可删)"""
    await get_mongo_client()
    share = await Share.find_one(Share.share_id == share_id)
    if share and share.user_id == user_id:
        await share.delete()
        logger.info(f"Share deleted: share_id={share_id}")
        return True
    return False
