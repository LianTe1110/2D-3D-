"""LeiaPix AI - 场景表模型 (含 MPI 扩展)"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Integer, Float
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Scene(Base, TimestampMixin):
    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id"), nullable=False
    )
    depth_map_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("depth_maps.id"), nullable=False
    )
    scene_data_url: Mapped[str | None] = mapped_column(String(512))
    texture_url: Mapped[str | None] = mapped_column(String(512))
    render_params: Mapped[dict | None] = mapped_column(JSONB)
    animation_params: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(20), default="processing"
    )  # processing / ready / failed

    # Phase 2: MPI 扩展
    layer_count: Mapped[int | None] = mapped_column(Integer, default=3)
    layers: Mapped[dict | None] = mapped_column(JSONB, default=None)  # MPILayer 列表
    models_used: Mapped[dict | None] = mapped_column(JSONB, default=None)  # {"depth": "dav2", "seg": "sam2"}
    processing_time_ms: Mapped[float | None] = mapped_column(Float, default=None)
    camera_config: Mapped[dict | None] = mapped_column(JSONB, default=None)
    scene_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, default=None)

    __table_args__ = (
        Index("ix_scenes_user_id", "user_id"),
        Index("ix_scenes_image_id", "image_id"),
    )

    def __repr__(self) -> str:
        return f"<Scene {self.id}>"
