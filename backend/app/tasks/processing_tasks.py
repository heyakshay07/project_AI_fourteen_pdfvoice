"""Background jobs. The same plain functions run under Celery (production) or FastAPI BackgroundTasks (dev)."""
import logging
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from celery import Celery
from sqlalchemy import delete

from app.agents import voice_agent
from app.agents import chunk_manager, pdf_analyzer, text_extraction, text_validation
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.audio_segment import AudioSegment
from app.models.document import Document, DocumentPage
from app.services.pdf_service import PdfError
from app.services.storage_service import get_storage

log = logging.getLogger("pdfvoice.tasks")

celery_app = Celery("pdfvoice", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_acks_late=True, worker_prefetch_multiplier=1)


def _remove_nuls(value):
    """Strip PostgreSQL-incompatible NULs from text values, including nested JSON."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_remove_nuls(item) for item in value]
    if isinstance(value, dict):
        return {key: _remove_nuls(item) for key, item in value.items()}
    return value


@contextmanager
def _local_pdf_copy(pdf_data: bytes | None, key: str | None, filename: str) -> Iterator[Path]:
    if pdf_data is not None:
        with tempfile.TemporaryDirectory(prefix="pdfvoice_process_") as tmp:
            path = Path(tmp) / filename
            path.write_bytes(pdf_data)
            yield path
        return
    if key:
        with get_storage().local_copy(key) as path:
            yield path
        return
    raise FileNotFoundError("PDF content and legacy storage key are both missing")


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
    """Prepare and persist small page batches so the reader can start before the PDF finishes."""
    doc_id = uuid.UUID(document_id)
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        key, pdf_data, filename = doc.file_path, doc.pdf_data, doc.filename
    _set_progress(doc_id, "starting", 1, status="processing", error="")

    last = {"stage": "", "pct": -10.0}

    def progress(stage: str, pct: float) -> None:
        if stage != last["stage"] or pct - last["pct"] >= 2:
            last["stage"], last["pct"] = stage, pct
            _set_progress(doc_id, stage, pct)

    try:
        with _local_pdf_copy(pdf_data, key, filename) as path:
            _set_progress(doc_id, "analyzing", 2)
            analysis = pdf_analyzer.analyze_pdf(path)
            with SessionLocal() as db:
                doc = db.get(Document, doc_id)
                if doc is None: return
                doc.total_pages = analysis["page_count"]
                doc.analysis = {k: analysis[k] for k in ("pdf_type", "ocr_pages", "metadata")}
                db.commit()

            batch_size = 4
            for start in range(1, analysis["page_count"] + 1, batch_size):
                end = min(start + batch_size - 1, analysis["page_count"])
                pages = text_extraction.extract_pages(path, analysis, only_pages=set(range(start, end + 1)))
                pages, retry = text_validation.validate_pages(pages)
                if retry:
                    redone = {p["page_number"]: p for p in text_extraction.extract_pages(
                        path, analysis, force_ocr=set(retry), only_pages=set(retry))}
                    pages = [({**redone[p["page_number"]], "errors": [], "validation_status": "ok", "validation_notes": []}
                              if p["page_number"] in redone and redone[p["page_number"]]["paragraphs"] else p) for p in pages]
                    pages, _ = text_validation.validate_pages(pages)
                chunks = chunk_manager.build_chunks(pages)
                with SessionLocal() as db:
                    doc = db.get(Document, doc_id)
                    if doc is None: return
                    for p in pages:
                        pc = chunks[p["page_number"]]
                        db.add(DocumentPage(document_id=doc_id, page_number=p["page_number"],
                            extracted_text=_remove_nuls("\n\n".join(x["text"] for x in p["paragraphs"])), extraction_method=p["method"],
                            validation_status=p["validation_status"], validation_notes=_remove_nuls(p["validation_notes"]),
                            width=p["width"], height=p["height"], sentences=_remove_nuls(pc["sentences"])))
                        for c in pc["chunks"]:
                            db.add(AudioSegment(document_id=doc_id, page_number=p["page_number"], **c))
                    db.commit()
                progress("extracting", 5 + 80 * end / max(analysis["page_count"], 1))

        with SessionLocal() as db:
            doc = db.get(Document, doc_id)
            if doc is None: return
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
