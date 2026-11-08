import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import voice_agent
from app.api.deps import ApiError, get_owned_document, require_completed
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.audio_segment import AudioSegment
from app.models.document import Document
from app.models.user import User, UserVoiceSettings
from app.schemas.voice import (GenerateRequest, GenerateResponse, SegmentDetail, SegmentOut, VoiceSettingsIn,
                               VoiceSettingsOut)
from app.services import audio_service, tts_service
from app.services.storage_service import get_storage
from app.services.tts_service import TTSError
from app.tasks.processing_tasks import dispatch

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


def _user_settings(db: Session, user: User) -> UserVoiceSettings:
    s = db.scalar(select(UserVoiceSettings).where(UserVoiceSettings.user_id == user.id))
    if s is None:
        s = UserVoiceSettings(user_id=user.id, voice_engine=settings.default_tts_engine, voice_name=settings.default_voice,
                              language=settings.default_language, speaking_speed=1.0)
        db.add(s)
        db.commit()
    return s


def resolve_voice(db: Session, user: User, engine: str | None, voice: str | None, language: str | None) -> tuple[str, str, str]:
    s = _user_settings(db, user)
    engine, voice, language = engine or s.voice_engine, voice or s.voice_name, language or s.language
    try:
        tts_service.resolve_voice(engine, voice, language)
        ok, reason = tts_service.get_provider(engine).is_available()
    except TTSError as exc:
        raise ApiError(422, "invalid_voice", str(exc))
    if not ok:
        raise ApiError(503, "engine_unavailable", reason)
    return engine, voice, language


@router.get("/available-voices")
def available_voices():
    return {"default": {"engine": settings.default_tts_engine, "voice": settings.default_voice, "language": settings.default_language},
            "languages": [{"code": "en", "label": "English"}, {"code": "hi", "label": "Hindi"}, {"code": "mr", "label": "Marathi"}],
            "engines": tts_service.list_engines()}


@router.get("/settings", response_model=VoiceSettingsOut)
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _user_settings(db, user)


@router.put("/settings", response_model=VoiceSettingsOut)
def put_settings(body: VoiceSettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        tts_service.resolve_voice(body.voice_engine, body.voice_name, body.language)
    except TTSError as exc:
        raise ApiError(422, "invalid_voice", str(exc))
    s = _user_settings(db, user)
    s.voice_engine, s.voice_name, s.language, s.speaking_speed = body.voice_engine, body.voice_name, body.language, body.speaking_speed
    db.commit()
    return s


@router.post("/generate", response_model=GenerateResponse, status_code=202)
def generate(body: GenerateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, body.document_id)
    if doc is None or doc.user_id != user.id:
        raise ApiError(404, "document_not_found", "Document not found")
    require_completed(doc)
    engine, voice, language = resolve_voice(db, user, body.voice_engine, body.voice_name, body.language)
    dispatch(background_tasks, "generate_audio", str(doc.id), engine, voice, language, body.from_page, body.to_page)
    return GenerateResponse(document_id=doc.id, detail="Audio generation started", voice_engine=engine, voice_name=voice, language=language)


@router.get("/{document_id}/segments", response_model=list[SegmentOut])
def list_segments(doc: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    segs = db.scalars(select(AudioSegment).where(AudioSegment.document_id == doc.id)
                      .order_by(AudioSegment.page_number, AudioSegment.chunk_index)).all()
    return [SegmentOut(id=s.id, page_number=s.page_number, chunk_index=s.chunk_index, sentence_start=s.sentence_start,
                       sentence_end=s.sentence_end, generation_status=s.generation_status, duration=s.duration) for s in segs]


def _segment_or_404(db: Session, doc: Document, segment_id: int) -> AudioSegment:
    seg = db.get(AudioSegment, segment_id)
    if seg is None or seg.document_id != doc.id:
        raise ApiError(404, "segment_not_found", "Audio segment not found")
    return seg


def _ensure(db, user, doc, seg, engine, voice, language) -> tuple[AudioSegment, tuple[str, str, str]]:
    require_completed(doc)
    triple = resolve_voice(db, user, engine, voice, language)
    try:
        return voice_agent.ensure_segment_audio(db, seg, *triple), triple
    except TTSError as exc:
        raise ApiError(502, "tts_failed", str(exc))


@router.get("/{document_id}/segments/{segment_id}", response_model=SegmentDetail)
def segment_detail(segment_id: int, engine: str | None = Query(None), voice: str | None = Query(None), language: str | None = Query(None),
                   doc: Document = Depends(get_owned_document), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Generates the segment's audio if needed and returns its sentence timings (used for highlight sync)."""
    seg, (e, v, l) = _ensure(db, user, doc, _segment_or_404(db, doc, segment_id), engine, voice, language)
    return SegmentDetail(id=seg.id, page_number=seg.page_number, chunk_index=seg.chunk_index, sentence_start=seg.sentence_start,
                         sentence_end=seg.sentence_end, generation_status=seg.generation_status, duration=seg.duration,
                         timings=seg.timings or [], voice_engine=e, voice_name=v, language=l)


@router.get("/{document_id}/audio/{segment_id}")
def segment_audio(segment_id: int, engine: str | None = Query(None), voice: str | None = Query(None), language: str | None = Query(None),
                  doc: Document = Depends(get_owned_document), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    seg, _ = _ensure(db, user, doc, _segment_or_404(db, doc, segment_id), engine, voice, language)
    data = get_storage().get_bytes(seg.audio_path)
    return Response(content=data, media_type=audio_service.media_type_for(seg.audio_path),
                    headers={"Cache-Control": "private, max-age=86400", "Accept-Ranges": "none"})
