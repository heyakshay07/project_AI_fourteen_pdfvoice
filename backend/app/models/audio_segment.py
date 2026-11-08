import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import utcnow


class AudioSegment(Base):
    """One chunk of consecutive sentences on a single page. Audio is generated lazily."""

    __tablename__ = "audio_segments"
    __table_args__ = (UniqueConstraint("document_id", "page_number", "chunk_index", name="uq_segment_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    sentence_start: Mapped[int] = mapped_column(Integer)  # inclusive index into the page's sentences
    sentence_end: Mapped[int] = mapped_column(Integer)  # inclusive
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    audio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)  # storage KEY
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    timings: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{sentence, start, end}] in seconds
    voice_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # hash of engine+voice+language
    generation_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ready|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document = relationship("Document", back_populates="segments")
