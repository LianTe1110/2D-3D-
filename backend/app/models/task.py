"""LeiaPix AI - 任务表模型"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # depth / render / enhance / export
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending / processing / completed / failed / cancelled
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    input_params: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default="NOW()")

    __table_args__ = (
        Index("ix_tasks_user_id", "user_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_type_status", "type", "status"),
    )

    def __repr__(self) -> str:
        return f"<Task {self.id} type={self.type} status={self.status}>"
