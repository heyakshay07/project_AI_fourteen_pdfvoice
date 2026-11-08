"""Background jobs. The same plain functions run under Celery (production) or FastAPI BackgroundTasks (dev)."""
import logging
import uuid

from celery import Celery
from sqlalchemy import delete

from app.agents import voice_agent
from app.agents.workflow import run_processing_workflow
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.audio_segment import AudioSegment
from app.models.document import Document, DocumentPage
from app.services.pdf_service import PdfError
from app.services.storage_service import get_storage

log = logging.getLogger("pdfvoice.tasks")

celery_app = Celery("pdfvoice", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_acks_late=True, worker_prefetch_multiplier=1)


def _set_progress(document_id: uuid.UUID, stage: str, percent: float, status: str | None = None, error: str | None = None) -> None:
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        doc.progress_stage, doc.progress_percent = stage, round(percent, 1)
        if status:
            doc.processing_status = status
        if error is not None:
            doc.error_message = error
        db.commit()


def process_document(document_id: str) -> None:
    """Analyze -> extract -> validate -> chunk (LangGraph), then persist pages and audio-segment rows."""
    doc_id = uuid.UUID(document_id)
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        key = doc.file_path
    _set_progress(doc_id, "starting", 1, status="processing", error="")

    last = {"stage": "", "pct": -10.0}

    def progress(stage: str, pct: float) -> None:
        if stage != last["stage"] or pct - last["pct"] >= 2:
            last["stage"], last["pct"] = stage, pct
            _set_progress(doc_id, stage, pct)

    try:
        with get_storage().local_copy(key) as path:
            state = run_processing_workflow(path, progress)
        _set_progress(doc_id, "saving", 90)

        with SessionLocal() as db:
            doc = db.get(Document, doc_id)
            if doc is None:
                return  # deleted while processing
            db.execute(delete(AudioSegment).where(AudioSegment.document_id == doc_id))
            db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc_id))
            analysis = state["analysis"]
            for p in state["pages"]:
                pc = state["chunks"][p["page_number"]]
                db.add(
                    DocumentPage(
                        document_id=doc_id, page_number=p["page_number"],
                        extracted_text="\n\n".join(x["text"] for x in p["paragraphs"]),
                        extraction_method=p["method"], validation_status=p["validation_status"],
                        validation_notes=p["validation_notes"], width=p["width"], height=p["height"],
                        sentences=pc["sentences"],
                    )
                )
                for c in pc["chunks"]:
                    db.add(AudioSegment(document_id=doc_id, page_number=p["page_number"], **c))
            doc.total_pages = analysis["page_count"]
            doc.analysis = {k: analysis[k] for k in ("pdf_type", "ocr_pages", "metadata")}
            doc.processing_status, doc.progress_stage, doc.progress_percent, doc.error_message = "completed", "completed", 100.0, None
            db.commit()
    except PdfError as exc:
        _set_progress(doc_id, "failed", 0, status="failed", error=exc.message)
    except Exception as exc:  # keep a record of the failure rather than silently dropping content
        log.exception("Processing failed for %s", document_id)
        _set_progress(doc_id, "failed", 0, status="failed", error=f"Processing failed: {exc}")


def generate_audio(document_id: str, engine: str, voice: str, language: str, from_page: int = 1, to_page: int | None = None) -> dict:
    with SessionLocal() as db:
        return voice_agent.generate_range(db, uuid.UUID(document_id), engine, voice, language, from_page, to_page)


@celery_app.task(name="pdfvoice.process_document")
def process_document_task(document_id: str) -> None:
    process_document(document_id)


@celery_app.task(name="pdfvoice.generate_audio")
def generate_audio_task(document_id: str, engine: str, voice: str, language: str, from_page: int = 1, to_page: int | None = None) -> dict:
    return generate_audio(document_id, engine, voice, language, from_page, to_page)


def dispatch(background_tasks, fn_name: str, *args) -> None:
    """Run via Celery when TASK_BACKEND=celery, otherwise via FastAPI BackgroundTasks."""
    if settings.task_backend == "celery":
        {"process_document": process_document_task, "generate_audio": generate_audio_task}[fn_name].delay(*args)
    else:
        background_tasks.add_task({"process_document": process_document, "generate_audio": generate_audio}[fn_name], *args)
