"""LeiaPix AI - MongoDB shares 集合 Schema

使用 Beanie ODM 进行文档建模（基于 motor + pydantic）。
"""

from datetime import datetime
from typing import Any

from beanie import Document, Indexed
from pydantic import Field


class Share(Document):
    """分享集合 — 存储免登录 3D 分享数据"""

    share_id: Indexed(str, unique=True) = Field(..., description="分享唯一标识")
    scene_id: Indexed(str) = Field(..., description="关联场景 ID")
    user_id: Indexed(str) = Field(..., description="创建者用户 ID")
    title: str = Field(default="我的 3D 照片", description="分享标题")
    is_public: bool = Field(default=True, description="是否公开")
    allow_download: bool = Field(default=True, description="是否允许下载")
    view_count: int = Field(default=0, description="浏览次数")
    download_count: int = Field(default=0, description="下载次数")
    expires_at: datetime | None = Field(default=None, description="过期时间")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    password_hash: str | None = Field(default=None, description="访问密码哈希")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="附加元数据（动画类型、时长等）",
    )

    class Settings:
        name = "shares"
        indexes = [
            "share_id",
            "scene_id",
            "user_id",
            "expires_at",
        ]
