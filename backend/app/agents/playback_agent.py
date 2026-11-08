"""Agent 6 - Playback Management: position resolution, navigation and progress persistence.

Audio plays in the browser; this agent is the server-side source of truth for *where* the reader is,
so a session can resume from the last completed sentence on any device.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audio_segment import AudioSegment
from app.models.document import DocumentPage
from app.models.reading_progress import ReadingProgress


def _sentence_counts(db: Session, document_id: uuid.UUID) -> dict[int, int]:
    """{page_number: number_of_sentences} computed from chunks (cheap, no JSON loading)."""
    rows = db.execute(
        select(AudioSegment.page_number, func.max(AudioSegment.sentence_end) + 1)
        .where(AudioSegment.document_id == document_id)
        .group_by(AudioSegment.page_number)
    ).all()
    return {p: int(n) for p, n in rows}


def compute_percentage(db: Session, document_id: uuid.UUID, page: int, sentence: int) -> float:
    counts = _sentence_counts(db, document_id)
    total = sum(counts.values())
    if total == 0:
        return 0.0
    done = sum(n for p, n in counts.items() if p < page) + max(0, min(sentence, counts.get(page, 0)))
    return round(100.0 * done / total, 2)


def segment_for(db: Session, document_id: uuid.UUID, page: int, sentence: int) -> AudioSegment | None:
    return db.scalar(
        select(AudioSegment).where(
            AudioSegment.document_id == document_id,
            AudioSegment.page_number == page,
            AudioSegment.sentence_start <= sentence,
            AudioSegment.sentence_end >= sentence,
        )
    )


def clamp_position(db: Session, document_id: uuid.UUID, page: int, sentence: int) -> tuple[int, int]:
    """Snap to a position that exists. Pages without sentences are skipped forward."""
    counts = _sentence_counts(db, document_id)
    pages = sorted(counts)
    if not pages:
        return 1, 0
    if page < pages[0]:
        return pages[0], 0
    if page > pages[-1]:
        return pages[-1], max(counts[pages[-1]] - 1, 0)
    if page not in counts:  # empty / image-only page: move to the next readable one
        nxt = next((p for p in pages if p > page), pages[-1])
        return nxt, 0
    return page, max(0, min(sentence, counts[page] - 1))


def navigate(db: Session, document_id: uuid.UUID, page: int, sentence: int, direction: str) -> tuple[int, int]:
    counts = _sentence_counts(db, document_id)
    pages = sorted(counts)
    if not pages:
        return 1, 0
    if direction == "next_sentence":
        if sentence + 1 < counts.get(page, 0):
            return page, sentence + 1
        nxt = next((p for p in pages if p > page), None)
        return (nxt, 0) if nxt else (page, max(counts.get(page, 1) - 1, 0))
    if direction == "prev_sentence":
        if sentence > 0:
            return page, sentence - 1
        prv = next((p for p in reversed(pages) if p < page), None)
        return (prv, counts[prv] - 1) if prv else (page, 0)
    if direction == "next_page":
        nxt = next((p for p in pages if p > page), None)
        return (nxt, 0) if nxt else (page, sentence)
    if direction == "prev_page":
        prv = next((p for p in reversed(pages) if p < page), None)
        return (prv, 0) if prv else (page, 0)
    raise ValueError(f"Unknown direction '{direction}'")


def get_or_create_progress(db: Session, user_id: int, document_id: uuid.UUID) -> ReadingProgress:
    prog = db.scalar(select(ReadingProgress).where(ReadingProgress.user_id == user_id, ReadingProgress.document_id == document_id))
    if prog is None:
        prog = ReadingProgress(user_id=user_id, document_id=document_id)
        db.add(prog)
        db.flush()
    return prog


def save_position(db: Session, user_id: int, document_id: uuid.UUID, page: int, sentence: int, state: str | None = None) -> ReadingProgress:
    page, sentence = clamp_position(db, document_id, page, sentence)
    prog = get_or_create_progress(db, user_id, document_id)
    seg = segment_for(db, document_id, page, sentence)
    prog.current_page, prog.current_sentence = page, sentence
    prog.current_segment = seg.id if seg else None
    prog.progress_percentage = compute_percentage(db, document_id, page, sentence)
    if state:
        prog.playback_state = state
    db.commit()
    return prog


def total_sentences(db: Session, document_id: uuid.UUID) -> int:
    return sum(_sentence_counts(db, document_id).values())
