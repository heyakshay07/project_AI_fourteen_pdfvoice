import uuid
from typing import Literal

from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    document_id: uuid.UUID
    page: int | None = Field(default=None, ge=1)  # omit to resume from the saved position
    sentence: int | None = Field(default=None, ge=0)


class PositionRequest(BaseModel):
    document_id: uuid.UUID
    page: int = Field(ge=1)
    sentence: int = Field(ge=0)
    position_seconds: float | None = None


class SeekRequest(BaseModel):
    document_id: uuid.UUID
    page: int | None = Field(default=None, ge=1)
    sentence: int | None = Field(default=None, ge=0)
    direction: Literal["next_sentence", "prev_sentence", "next_page", "prev_page"] | None = None


class PlaybackState(BaseModel):
    document_id: uuid.UUID
    state: str
    page: int
    sentence: int
    segment_id: int | None
    progress_percentage: float


class ProgressUpdate(BaseModel):
    page: int = Field(ge=1)
    sentence: int = Field(ge=0)


class HistoryItem(BaseModel):
    document_id: uuid.UUID
    filename: str
    total_pages: int
    file_size: int = 0
    processing_status: str
    created_at: str
    current_page: int | None = None
    current_sentence: int | None = None
    progress_percentage: float = 0.0
    last_read_at: str | None = None
