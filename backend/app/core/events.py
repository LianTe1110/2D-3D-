"""LeiaPix AI - 应用生命周期事件

管理启动 / 关闭时的资源初始化与清理。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话（依赖注入用）"""
    settings = get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
            await engine.dispose()
