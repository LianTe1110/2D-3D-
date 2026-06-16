"""LeiaPix AI - FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import close_mongo_client, init_mongo_indexes
from app.core.logging import log_request_response, setup_logging
from app.core.redis import redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = get_settings()
    # 初始化日志
    setup_logging(debug=settings.DEBUG)
    logger = __import__("logging").getLogger("app")

    logger.info(f"=== {settings.APP_NAME} v{settings.APP_VERSION} starting ===")
    logger.info(f"    Database: {settings.DATABASE_URL.split('@')[-1]}")
    logger.info(f"    Redis:    {settings.REDIS_URL}")
    logger.info(f"    MinIO:    {settings.MINIO_ENDPOINT}")
    logger.info(f"    MongoDB:  {settings.MONGO_URI}")
    logger.info(f"    GPU:      {'enabled' if settings.GPU_ENABLED else 'disabled'}")
    await init_mongo_indexes()
    yield
    # 关闭时清理
    await redis_client.close()
    await close_mongo_client()
    logger.info(f"=== {settings.APP_NAME} shutting down ===")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="2D → 3D 图片转换工具 API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 请求/响应日志中间件 (必须在 CORS 之前)
    app.middleware("http")(log_request_response)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 路由注册
    from app.api.v1 import auth, depth, enhance, export, render, share, upload, ws

    api_prefix = settings.API_V1_PREFIX
    app.include_router(upload.router, prefix=api_prefix, tags=["upload"])
    app.include_router(depth.router, prefix=api_prefix, tags=["depth"])
    app.include_router(render.router, prefix=api_prefix, tags=["render"])
    app.include_router(enhance.router, prefix=api_prefix, tags=["enhance"])
    app.include_router(export.router, prefix=api_prefix, tags=["export"])
    app.include_router(share.router, prefix=api_prefix, tags=["share"])
    app.include_router(auth.router, prefix=api_prefix, tags=["auth"])
    app.include_router(ws.router, prefix=api_prefix, tags=["websocket"])

    @app.get("/health", tags=["health"])
    async def health_check():
        return {"status": "ok", "version": settings.APP_VERSION}

    return app


app = create_app()
