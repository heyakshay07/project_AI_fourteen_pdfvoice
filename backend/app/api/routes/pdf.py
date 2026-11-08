import asyncio
import json
import re
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.chunk_manager import chunk_progress
from app.api.deps import ApiError, get_owned_document
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.security import get_current_user
from app.models.document import Document, DocumentPage
from app.models.user import User
from app.schemas.pdf import (DocumentOut, PageSummary, PageText, ProcessResponse, ProgressOut, StatusOut,
                             TextResponse)
from app.services.pdf_service import PdfError
from app.agents.pdf_analyzer import analyze_pdf
from app.services.storage_service import get_storage
from app.tasks.processing_tasks import dispatch

router = APIRouter(prefix="/api/v1/pdf", tags=["pdf"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ \-()\u0900-\u097F]")


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]  # strip any path
    name = _SAFE_NAME.sub("_", name).strip(" .") or "document.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:200]


def to_document_out(doc: Document) -> DocumentOut:
    a = doc.analysis or {}
    return DocumentOut(
        id=doc.id, filename=doc.filename, file_size=doc.file_size, total_pages=doc.total_pages,
        processing_status=doc.processing_status, progress_stage=doc.progress_stage,
        progress_percent=doc.progress_percent, error_message=doc.error_message,
        pdf_type=a.get("pdf_type") or (doc.analysis or {}).get("pdf_type"),
        ocr_page_count=len(a.get("ocr_pages", [])), created_at=doc.created_at,
    )


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    filename = sanitize_filename(file.filename or "document.pdf")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise ApiError(415, "invalid_file_type", "Only .pdf files are accepted")

    # stream the body with a hard size cap (never trust Content-Length)
    chunks, size = [], 0
    while True:
        part = await file.read(1024 * 1024)
        if not part:
            break
        size += len(part)
        if size > settings.max_upload_bytes:
            raise ApiError(413, "file_too_large", f"File exceeds the {settings.max_upload_mb} MB limit")
        chunks.append(part)
    data = b"".join(chunks)
    if size == 0:
        raise ApiError(422, "empty_file", "The uploaded file is empty")
    if not data.lstrip()[:5] == b"%PDF-":  # magic-byte check; extension/content-type alone are not trusted
        raise ApiError(415, "invalid_file_type", "The file is not a valid PDF")

    doc_id = uuid.uuid4()
    key = f"uploads/{user.id}/{doc_id}.pdf"
    storage = get_storage()
    storage.put_bytes(key, data)
    try:
        with storage.local_copy(key) as path:
            analysis = analyze_pdf(path)  # fast: detects corrupted / encrypted / too-long PDFs
    except PdfError as exc:
        storage.delete(key)
        raise ApiError(422, exc.code, exc.message)
    except Exception as exc:
        storage.delete(key)
        raise ApiError(422, "corrupted", f"The PDF could not be read: {exc}")

    doc = Document(
        id=doc_id, user_id=user.id, filename=filename, file_path=key, file_size=size,
        total_pages=analysis["page_count"], processing_status="uploaded",
        analysis={k: analysis[k] for k in ("pdf_type", "ocr_pages", "metadata")},
    )
    db.add(doc)
    db.commit()
    return to_document_out(doc)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(doc: Document = Depends(get_owned_document)):
    return to_document_out(doc)


@router.get("/{document_id}/file")
def download_original(doc: Document = Depends(get_owned_document)):
    """Serves the original PDF to its owner (used by PDF.js). Storage paths are never revealed."""
    data = get_storage().get_bytes(doc.file_path)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{doc.id}.pdf"', "Cache-Control": "private, max-age=3600"})


@router.get("/{document_id}/pages", response_model=list[PageSummary])
def list_pages(doc: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    pages = db.scalars(select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_number)).all()
    return [
        PageSummary(page_number=p.page_number, extraction_method=p.extraction_method, validation_status=p.validation_status,
                    validation_notes=p.validation_notes or [], char_count=len(p.extracted_text or ""),
                    sentence_count=len(p.sentences or []))
        for p in pages
    ]


@router.get("/{document_id}/text", response_model=TextResponse)
def get_text(
    page: int | None = Query(default=None, ge=1, description="Return only this page"),
    start: int = Query(default=1, ge=1), limit: int = Query(default=20, ge=1, le=100),
    doc: Document = Depends(get_owned_document), db: Session = Depends(get_db),
):
    q = select(DocumentPage).where(DocumentPage.document_id == doc.id)
    if page is not None:
        q = q.where(DocumentPage.page_number == page)
    else:
        q = q.where(DocumentPage.page_number >= start)
    rows = db.scalars(q.order_by(DocumentPage.page_number).limit(1 if page else limit)).all()
    if page is not None and not rows:
        raise ApiError(404, "page_not_found", f"Page {page} has not been extracted")
    return TextResponse(
        document_id=doc.id,
        pages=[
            PageText(page_number=p.page_number, width=p.width, height=p.height, extraction_method=p.extraction_method,
                     validation_status=p.validation_status, validation_notes=p.validation_notes or [],
                     text=p.extracted_text or "", sentences=p.sentences or [])
            for p in rows
        ],
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(doc: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    storage = get_storage()
    storage.delete_prefix(f"audio/{doc.id}")
    storage.delete(doc.file_path)
    db.delete(doc)  # cascades to pages, segments, progress
    db.commit()
    return Response(status_code=204)


@router.post("/{document_id}/process", response_model=ProcessResponse, status_code=202)
def process_pdf(background_tasks: BackgroundTasks, doc: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    if doc.processing_status in {"queued", "processing"}:
        raise ApiError(409, "already_processing", "This document is already being processed")
    doc.processing_status, doc.progress_stage, doc.progress_percent, doc.error_message = "queued", "queued", 0.0, None
    db.commit()
    dispatch(background_tasks, "process_document", str(doc.id))
    return ProcessResponse(document_id=doc.id, processing_status="queued")


@router.get("/{document_id}/status", response_model=StatusOut)
def get_status(doc: Document = Depends(get_owned_document)):
    return StatusOut(document_id=doc.id, processing_status=doc.processing_status, stage=doc.progress_stage,
                     percent=doc.progress_percent, error_message=doc.error_message)


def _progress_payload(db: Session, doc: Document) -> ProgressOut:
    counts = dict(db.execute(
        select(DocumentPage.validation_status, func.count()).where(DocumentPage.document_id == doc.id).group_by(DocumentPage.validation_status)
    ).all())
    chunks = chunk_progress(db, doc.id)
    return ProgressOut(
        document_id=doc.id, processing_status=doc.processing_status, stage=doc.progress_stage, percent=doc.progress_percent,
        error_message=doc.error_message, total_pages=doc.total_pages, pages_extracted=sum(counts.values()),
        pages_with_warnings=counts.get("warning", 0), pages_empty=counts.get("empty", 0), pages_failed=counts.get("failed", 0),
        chunks_total=chunks["total"], chunks_audio_ready=chunks["ready"], chunks_audio_failed=chunks["failed"],
    )


@router.get("/{document_id}/progress", response_model=ProgressOut)
def get_progress(doc: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    return _progress_payload(db, doc)


@router.get("/{document_id}/progress/stream")
async def stream_progress(doc: Document = Depends(get_owned_document)):
    """Server-Sent Events: one `progress` event per second until processing finishes."""
    doc_id, user_id = doc.id, doc.user_id

    async def events():
        deadline = time.monotonic() + 60 * 60
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                d = db.get(Document, doc_id)
                if d is None or d.user_id != user_id:
                    break
                payload = _progress_payload(db, d)
            yield f"event: progress\ndata: {json.dumps(payload.model_dump(mode='json'))}\n\n"
            if payload.processing_status in {"completed", "failed"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
