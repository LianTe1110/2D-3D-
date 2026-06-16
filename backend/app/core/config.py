"""LeiaPix AI - 核心配置模块

利用 pydantic-settings 从环境变量 / .env 文件读取所有配置项。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置，支持 .env 文件和环境变量"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --------------- 应用 ---------------
    APP_NAME: str = "LeiaPix AI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --------------- PostgreSQL ---------------
    DATABASE_URL: str = "postgresql+asyncpg://leiapix:leiapix@localhost:5432/leiapix"
    DATABASE_URL_SYNC: str = "postgresql://leiapix:leiapix@localhost:5432/leiapix"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    # --------------- Redis ---------------
    REDIS_URL: str = "redis://localhost:6379/0"

    # --------------- MinIO ---------------
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "leiapix"
    MINIO_SECRET_KEY: str = "leiapix123"
    MINIO_BUCKET: str = "leiapix-storage"
    MINIO_SECURE: bool = False

    # --------------- MongoDB ---------------
    MONGO_URI: str = "mongodb://leiapix:leiapix123@localhost:27017"
    MONGO_DB: str = "leiapix_share"

    # --------------- JWT ---------------
    JWT_SECRET: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --------------- AI 模型 ---------------
    GPU_ENABLED: bool = True
    MODEL_PATH: str = "./ai-models"

    # --------------- GPU 显存保护 ---------------
    # 每个 Worker 容器通过环境变量配置, 超过阈值则拒绝新任务
    GPU_DEPTH_MAX_MEMORY_MB: int = 8192     # 深度估计最大显存 (MB)
    GPU_ENHANCE_MAX_MEMORY_MB: int = 10240  # 图像增强最大显存 (MB)

    # --------------- 上传 ---------------
    MAX_UPLOAD_SIZE_MB: int = 20
    UPLOAD_ALLOWED_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp", "image/bmp"]

    # --------------- CORS ---------------
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"]

    # --------------- Celery ---------------
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings()
