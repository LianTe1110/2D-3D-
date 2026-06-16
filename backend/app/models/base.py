"""LeiaPix AI - SQLAlchemy 2.0 Base & 数据库引擎配置"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 命名约定：用于 Alembic 自动生成索引/约束名称
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


class TimestampMixin:
    """通用时间戳混入"""

    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, server_default="NOW()"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        default=None, onupdate=datetime.utcnow
    )
