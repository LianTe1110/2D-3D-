"""LeiaPix AI - MongoDB 客户端连接配置 (motor 异步驱动)"""

from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings


@lru_cache
def get_mongo_client() -> AsyncIOMotorClient:
    """获取 MongoDB 客户端单例"""
    settings = get_settings()
    return AsyncIOMotorClient(settings.MONGO_URI)


def get_mongo_db() -> AsyncIOMotorDatabase:
    """获取 MongoDB 数据库实例"""
    settings = get_settings()
    return get_mongo_client()[settings.MONGO_DB]


async def init_mongo_indexes() -> None:
    """初始化 MongoDB 集合索引（应用启动时调用）"""
    db = get_mongo_db()

    # shares 集合索引
    await db.shares.create_index("share_id", unique=True)
    await db.shares.create_index("scene_id")
    await db.shares.create_index("user_id")
    await db.shares.create_index("expires_at", expireAfterSeconds=0)  # TTL 索引

    print("  MongoDB indexes created")


async def close_mongo_client() -> None:
    """关闭 MongoDB 连接（应用关闭时调用）"""
    client = get_mongo_client()
    client.close()
