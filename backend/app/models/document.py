import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.database import Base
from app.models.user import utcnow


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)  # legacy storage key
    pdf_data: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    # uploaded | queued | processing | completed | failed
    processing_status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    progress_stage: Mapped[str] = mapped_column(String(40), default="uploaded")
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="documents")
    pages = relationship(
        "DocumentPage", back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )
    segments = relationship(
        "AudioSegment",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="(AudioSegment.page_number, AudioSegment.chunk_index)",
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_page_doc_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)  # 1-based
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    extraction_method: Mapped[str] = mapped_column(String(20), default="text")  # text | ocr | none
    validation_status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | warning | empty | failed
    validation_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    width: Mapped[float] = mapped_column(Float, default=0.0)  # PDF points
    height: Mapped[float] = mapped_column(Float, default=0.0)
    sentences: Mapped[list | None] = mapped_column(JSON, nullable=True)

    document = relationship("Document", back_populates="pages")
