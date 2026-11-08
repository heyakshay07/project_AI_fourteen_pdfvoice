"""Agent 5 - Voice Generation: turns a stored chunk into audio, with caching and retries."""
import json
import threading
import time
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audio_segment import AudioSegment
from app.models.document import DocumentPage
from app.services import audio_service, tts_service
from app.services.storage_service import get_storage
from app.services.tts_service import TTSError

MAX_ATTEMPTS = 3
_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)  # one generation per segment per process


def _base_key(document_id: uuid.UUID, seg: AudioSegment, vkey: str) -> str:
    return f"audio/{document_id}/p{seg.page_number:05d}_c{seg.chunk_index:03d}_{vkey}"


def _apply_ready(seg: AudioSegment, key: str, duration: float, timings: list, vkey: str) -> None:
    seg.audio_path, seg.duration, seg.timings, seg.voice_key = key, duration, timings, vkey
    seg.generation_status, seg.error_message = "ready", None


def _find_cached(document_id: uuid.UUID, seg: AudioSegment, vkey: str) -> tuple[str, dict] | None:
    storage = get_storage()
    base = _base_key(document_id, seg, vkey)
    meta_key = base + ".json"
    if not storage.exists(meta_key):
        return None
    meta = json.loads(storage.get_bytes(meta_key))
    if storage.exists(meta["audio_key"]):
        return meta["audio_key"], meta
    return None


def ensure_segment_audio(db: Session, seg: AudioSegment, engine: str, voice: str, language: str, speed: float = 1.0) -> AudioSegment:
    """Make sure `seg` has audio for this voice. Idempotent: re-running never duplicates content."""
    vkey = audio_service.voice_key(engine, voice, language)
    if seg.generation_status == "ready" and seg.voice_key == vkey and seg.audio_path and get_storage().exists(seg.audio_path):
        return seg

    with _locks[seg.id]:
        db.refresh(seg)
        if seg.generation_status == "ready" and seg.voice_key == vkey and seg.audio_path and get_storage().exists(seg.audio_path):
            return seg

        cached = _find_cached(seg.document_id, seg, vkey)  # e.g. user switched voice back and forth
        if cached:
            key, meta = cached
            _apply_ready(seg, key, meta["duration"], meta["timings"], vkey)
            db.commit()
            return seg

        page = db.scalar(
            select(DocumentPage).where(DocumentPage.document_id == seg.document_id, DocumentPage.page_number == seg.page_number)
        )
        sentences = (page.sentences or [])[seg.sentence_start : seg.sentence_end + 1] if page else []
        if not sentences:
            seg.generation_status, seg.error_message = "failed", "Segment has no source sentences"
            db.commit()
            raise TTSError(seg.error_message)

        provider = tts_service.get_provider(engine)
        tts_service.resolve_voice(engine, voice, language)  # validates the combination
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            seg.attempts += 1
            try:
                clips = [provider.synthesize(s["text"], voice, language, speed) for s in sentences]
                audio, sr, timings = audio_service.assemble(
                    clips, [s["i"] for s in sentences], [s["heading"] for s in sentences], [s["para_end"] for s in sentences]
                )
                base = _base_key(seg.document_id, seg, vkey)
                key, duration = audio_service.store_audio(base, audio, sr)
                get_storage().put_bytes(
                    base + ".json", json.dumps({"audio_key": key, "duration": duration, "timings": timings}).encode()
                )
                _apply_ready(seg, key, duration, timings, vkey)
                db.commit()
                return seg
            except Exception as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS:
                    time.sleep(0.5 * attempt)
        seg.generation_status, seg.error_message = "failed", str(last_error)[:1000]
        db.commit()
        raise TTSError(f"Audio generation failed after {MAX_ATTEMPTS} attempts: {last_error}")


def generate_range(db: Session, document_id: uuid.UUID, engine: str, voice: str, language: str, from_page: int = 1, to_page: int | None = None, speed: float = 1.0) -> dict:
    """Pre-generate audio for a page range (used by the background task). Failures are counted, not fatal."""
    q = select(AudioSegment).where(AudioSegment.document_id == document_id, AudioSegment.page_number >= from_page)
    if to_page:
        q = q.where(AudioSegment.page_number <= to_page)
    segs = db.scalars(q.order_by(AudioSegment.page_number, AudioSegment.chunk_index)).all()
    ok = failed = 0
    for seg in segs:
        try:
            ensure_segment_audio(db, seg, engine, voice, language, speed)
            ok += 1
        except Exception:
            failed += 1
    return {"generated": ok, "failed": failed, "total": len(segs)}
