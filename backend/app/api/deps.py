import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.document import Document
from app.models.user import User


class ApiError(HTTPException):
    """HTTPException with a machine-readable code; rendered as {"error": {"code", "message"}}."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


def get_owned_document(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:  # same 404 for "missing" and "not yours": no existence leak
        raise ApiError(404, "document_not_found", "Document not found")
    return doc


def require_completed(doc: Document) -> Document:
    if doc.processing_status != "completed":
        raise ApiError(409, "not_processed", f"Document is not ready (status: {doc.processing_status}). Process it first.")
    return doc
