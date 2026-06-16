"""LeiaPix AI - 深度图表模型"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DepthMap(Base):
    __tablename__ = "depth_maps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    model_used: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # depth_anything_v2 / midas / leres / ensemble
    depth_map_url: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict | None] = mapped_column(JSONB)  # 模型参数
    status: Mapped[str] = mapped_column(
        String(20), default="processing"
    )  # processing / ready / failed
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default="NOW()")

    __table_args__ = (
        Index("ix_depth_maps_image_id", "image_id"),
    )

    def __repr__(self) -> str:
        return f"<DepthMap {self.id} model={self.model_used}>"
