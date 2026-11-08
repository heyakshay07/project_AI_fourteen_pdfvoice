import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents import playback_agent as agent
from app.api.deps import ApiError, require_completed
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.document import Document
from app.models.user import User
from app.schemas.playback import PlaybackState, PositionRequest, SeekRequest, StartRequest

router = APIRouter(prefix="/api/v1/playback", tags=["playback"])


def _doc(db: Session, user: User, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise ApiError(404, "document_not_found", "Document not found")
    return require_completed(doc)


def _state(prog, state: str) -> PlaybackState:
    return PlaybackState(document_id=prog.document_id, state=state, page=prog.current_page, sentence=prog.current_sentence,
                         segment_id=prog.current_segment, progress_percentage=prog.progress_percentage)


@router.post("/start", response_model=PlaybackState)
def start(body: StartRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Start reading. Without page/sentence the saved position is used (resume from the last sentence)."""
    doc = _doc(db, user, body.document_id)
    prog = agent.get_or_create_progress(db, user.id, doc.id)
    page = body.page if body.page is not None else (prog.current_page or 1)
    sentence = body.sentence if body.sentence is not None else (prog.current_sentence if body.page is None else 0)
    return _state(agent.save_position(db, user.id, doc.id, page, sentence, "playing"), "playing")


def _persist(body: PositionRequest, state: str, db: Session, user: User) -> PlaybackState:
    doc = _doc(db, user, body.document_id)
    return _state(agent.save_position(db, user.id, doc.id, body.page, body.sentence, state), state)


@router.post("/pause", response_model=PlaybackState)
def pause(body: PositionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _persist(body, "paused", db, user)


@router.post("/resume", response_model=PlaybackState)
def resume(body: PositionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _persist(body, "playing", db, user)


@router.post("/stop", response_model=PlaybackState)
def stop(body: PositionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _persist(body, "stopped", db, user)


@router.post("/seek", response_model=PlaybackState)
def seek(body: SeekRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Jump to an explicit page/sentence, or move relative to it (next/prev sentence or page)."""
    doc = _doc(db, user, body.document_id)
    prog = agent.get_or_create_progress(db, user.id, doc.id)
    page = body.page if body.page is not None else prog.current_page
    sentence = body.sentence if body.sentence is not None else prog.current_sentence
    if body.direction:
        page, sentence = agent.navigate(db, doc.id, page, sentence, body.direction)
    elif body.page is None and body.sentence is None:
        raise ApiError(422, "invalid_seek", "Provide page/sentence or a direction")
    prog = agent.save_position(db, user.id, doc.id, page, sentence)
    return _state(prog, prog.playback_state)
