import uuid

from pydantic import BaseModel, Field


class VoiceSettingsIn(BaseModel):
    voice_engine: str = Field(max_length=32)
    voice_name: str = Field(max_length=64)
    language: str = Field(max_length=16)
    speaking_speed: float = Field(default=1.0, ge=0.5, le=2.5)


class VoiceSettingsOut(VoiceSettingsIn):
    model_config = {"from_attributes": True}


class GenerateRequest(BaseModel):
    document_id: uuid.UUID
    from_page: int = Field(default=1, ge=1)
    to_page: int | None = Field(default=None, ge=1)
    voice_engine: str | None = None
    voice_name: str | None = None
    language: str | None = None


class GenerateResponse(BaseModel):
    document_id: uuid.UUID
    detail: str
    voice_engine: str
    voice_name: str
    language: str


class SegmentOut(BaseModel):
    id: int
    page_number: int
    chunk_index: int
    sentence_start: int
    sentence_end: int
    generation_status: str
    duration: float | None = None


class SentenceTiming(BaseModel):
    sentence: int
    start: float
    end: float


class SegmentDetail(SegmentOut):
    timings: list[SentenceTiming] = []
    voice_engine: str
    voice_name: str
    language: str
