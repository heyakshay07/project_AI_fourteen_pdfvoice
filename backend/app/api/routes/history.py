import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import playback_agent as agent
from app.api.deps import ApiError
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.document import Document
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from app.schemas.playback import HistoryItem, PlaybackState, ProgressUpdate

router = APIRouter(prefix="/api/v1/history", tags=["history"])


def _item(doc: Document, prog: ReadingProgress | None) -> HistoryItem:
    return HistoryItem(
        document_id=doc.id, filename=doc.filename, total_pages=doc.total_pages, file_size=doc.file_size, processing_status=doc.processing_status,
        created_at=doc.created_at.isoformat(),
        current_page=prog.current_page if prog else None, current_sentence=prog.current_sentence if prog else None,
        progress_percentage=prog.progress_percentage if prog else 0.0,
        last_read_at=prog.updated_at.isoformat() if prog else None,
    )


@router.get("", response_model=list[HistoryItem])
def list_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs = db.scalars(select(Document).where(Document.user_id == user.id)).all()
    progs = {p.document_id: p for p in db.scalars(select(ReadingProgress).where(ReadingProgress.user_id == user.id))}
    items = [_item(d, progs.get(d.id)) for d in docs]
    items.sort(key=lambda i: i.last_read_at or i.created_at, reverse=True)
    return items


def _owned(db: Session, user: User, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise ApiError(404, "document_not_found", "Document not found")
    return doc


@router.get("/{document_id}", response_model=HistoryItem)
def get_history(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _owned(db, user, document_id)
    prog = db.scalar(select(ReadingProgress).where(ReadingProgress.user_id == user.id, ReadingProgress.document_id == doc.id))
    return _item(doc, prog)


@router.put("/{document_id}/progress", response_model=PlaybackState)
def update_progress(document_id: uuid.UUID, body: ProgressUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _owned(db, user, document_id)
    if doc.processing_status != "completed":
        raise ApiError(409, "not_processed", "Document has not been processed yet")
    prog = agent.save_position(db, user.id, doc.id, body.page, body.sentence)
    return PlaybackState(document_id=doc.id, state=prog.playback_state, page=prog.current_page, sentence=prog.current_sentence,
                         segment_id=prog.current_segment, progress_percentage=prog.progress_percentage)


@router.delete("/{document_id}", status_code=204)
def clear_history(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Clears reading progress for a document (the document itself is deleted via DELETE /api/v1/pdf/{id})."""
    doc = _owned(db, user, document_id)
    prog = db.scalar(select(ReadingProgress).where(ReadingProgress.user_id == user.id, ReadingProgress.document_id == doc.id))
    if prog:
        db.delete(prog)
        db.commit()
    return Response(status_code=204)
