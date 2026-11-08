import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class ReadingProgress(Base):
    __tablename__ = "reading_progress"
    __table_args__ = (UniqueConstraint("user_id", "document_id", name="uq_progress_user_doc"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    current_page: Mapped[int] = mapped_column(Integer, default=1)
    current_segment: Mapped[int | None] = mapped_column(Integer, nullable=True)  # AudioSegment.id
    current_sentence: Mapped[int] = mapped_column(Integer, default=0)  # index within current_page
    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    playback_state: Mapped[str] = mapped_column(String(12), default="stopped")  # playing|paused|stopped
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
