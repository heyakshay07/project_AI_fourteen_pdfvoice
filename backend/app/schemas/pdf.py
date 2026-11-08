import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    file_size: int
    total_pages: int
    processing_status: str
    progress_stage: str
    progress_percent: float
    error_message: str | None = None
    pdf_type: str | None = None
    ocr_page_count: int = 0
    created_at: datetime


class PageSummary(BaseModel):
    page_number: int
    extraction_method: str
    validation_status: str
    validation_notes: list[str] = []
    char_count: int
    sentence_count: int


class SentenceOut(BaseModel):
    i: int
    text: str
    bbox: list[float]
    heading: bool
    para_end: bool


class PageText(BaseModel):
    page_number: int
    width: float
    height: float
    extraction_method: str
    validation_status: str
    validation_notes: list[str] = []
    text: str
    sentences: list[SentenceOut]


class TextResponse(BaseModel):
    document_id: uuid.UUID
    pages: list[PageText]


class StatusOut(BaseModel):
    document_id: uuid.UUID
    processing_status: str
    stage: str
    percent: float
    error_message: str | None = None


class ProgressOut(StatusOut):
    total_pages: int
    pages_extracted: int
    pages_with_warnings: int
    pages_empty: int
    pages_failed: int
    chunks_total: int
    chunks_audio_ready: int
    chunks_audio_failed: int


class ProcessResponse(BaseModel):
    document_id: uuid.UUID
    processing_status: str
    detail: str = Field(default="Processing started")
