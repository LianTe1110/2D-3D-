"""LeiaPix AI - 导出记录表模型"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # mp4 / gif / depth_png
    resolution: Mapped[str | None] = mapped_column(String(10))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    download_url: Mapped[str | None] = mapped_column(String(512))
    storage_key: Mapped[str | None] = mapped_column(String(512))
    expires_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(
        String(20), default="processing"
    )  # processing / ready / expired / failed
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default="NOW()")

    __table_args__ = (
        Index("ix_exports_scene_id", "scene_id"),
        Index("ix_exports_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<Export {self.id} format={self.format}>"
