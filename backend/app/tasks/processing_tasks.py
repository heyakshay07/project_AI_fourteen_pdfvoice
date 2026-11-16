"""Background jobs. The same plain functions run under Celery (production) or FastAPI BackgroundTasks (dev)."""
import logging
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from collections.abc import Iterator

from celery import Celery
from sqlalchemy import select, update

from app.agents import voice_agent
from app.agents import chunk_manager, groq_enrichment, text_extraction, text_validation
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.audio_segment import AudioSegment
from app.models.document import Document, DocumentPage
from app.models.user import UserVoiceSettings
from app.services import pdf_service
from app.services.pdf_service import PdfError
from app.services.storage_service import get_storage

log = logging.getLogger("pdfvoice.tasks")

celery_app = Celery("pdfvoice", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "pdfvoice.process_document": {"queue": "extract"},
        "pdfvoice.generate_audio": {"queue": "tts"},
        "pdfvoice.generate_segment_ids_audio": {"queue": "tts"},
        "pdfvoice.enrich_document": {"queue": "enrich"},
    },
)
_inline_tts_pool = ThreadPoolExecutor(max_workers=settings.tts_worker_concurrency, thread_name_prefix="pdfvoice-tts")
_inline_enrichment_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdfvoice-enrich")


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


def _generate_segment_ids(document_id: str, segment_ids: list[int], engine: str, voice: str, language: str) -> None:
    with SessionLocal() as db:
        for segment_id in segment_ids:
            seg = db.get(AudioSegment, segment_id)
            if seg is None or str(seg.document_id) != document_id:
                continue
            try:
                voice_agent.ensure_segment_audio(db, seg, engine, voice, language)
            except Exception:
                log.exception("Initial audio generation failed for segment %s", segment_id)


def _schedule_segment_audio(document_id: uuid.UUID, segment_ids: list[int], engine: str, voice: str, language: str) -> None:
    if not segment_ids:
        return
    args = (str(document_id), list(segment_ids), engine, voice, language)
    try:
        if settings.task_backend == "celery":
            generate_segment_ids_task.delay(*args)
        else:
            _inline_tts_pool.submit(_generate_segment_ids, *args)
    except Exception:
        # Audio is optional for extraction progress; the reader can still request any chunk on demand.
        log.exception("Could not queue audio generation for document %s", document_id)


def _schedule_batch_audio(document_id: uuid.UUID, user_id: int, start_page: int, end_page: int) -> None:
    """Generate the first playable buffer first, then queue audio per extracted page batch."""
    with SessionLocal() as db:
        prefs = db.scalar(select(UserVoiceSettings).where(UserVoiceSettings.user_id == user_id))
        engine = prefs.voice_engine if prefs else settings.default_tts_engine
        voice = prefs.voice_name if prefs else settings.default_voice
        language = prefs.language if prefs else settings.default_language
        segment_ids = db.scalars(
            select(AudioSegment.id)
            .where(
                AudioSegment.document_id == document_id,
                AudioSegment.page_number >= start_page,
                AudioSegment.page_number <= end_page,
            )
            .order_by(AudioSegment.page_number, AudioSegment.chunk_index)
        ).all()
    if start_page == 1:
        # Keep the initial three in their own short task so later chunks cannot delay Play.
        _schedule_segment_audio(document_id, segment_ids[:3], engine, voice, language)
        _schedule_segment_audio(document_id, segment_ids[3:], engine, voice, language)
    else:
        _schedule_segment_audio(document_id, segment_ids, engine, voice, language)


def process_document(document_id: str) -> None:
    """Prepare and persist small page batches so the reader can start before the PDF finishes."""
    doc_id = uuid.UUID(document_id)
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        key, pdf_data, filename = doc.file_path, doc.pdf_data, doc.filename
        analysis = {
            "page_count": doc.total_pages,
            **(doc.analysis or {}),
        }
    _set_progress(doc_id, "starting", 1, status="processing", error="")

    last = {"stage": "", "pct": -10.0}

    def progress(stage: str, pct: float) -> None:
        if stage != last["stage"] or pct - last["pct"] >= 2:
            last["stage"], last["pct"] = stage, pct
            _set_progress(doc_id, stage, pct)

    try:
        with _local_pdf_copy(pdf_data, key, filename) as path, closing(pdf_service.open_pdf(path)) as pdf_doc:
            batch_size = settings.processing_batch_pages
            first_batch_size = min(4, batch_size)
            start = 1
            while start <= analysis["page_count"]:
                batch_size = first_batch_size if start == 1 else settings.processing_batch_pages
                end = min(start + batch_size - 1, analysis["page_count"])
                with SessionLocal() as db:
                    saved_pages = set(db.scalars(
                        select(DocumentPage.page_number).where(
                            DocumentPage.document_id == doc_id,
                            DocumentPage.page_number >= start,
                            DocumentPage.page_number <= end,
                        )
                    ).all())
                missing_pages = set(range(start, end + 1)) - saved_pages
                if not missing_pages:
                    _schedule_batch_audio(doc_id, doc.user_id, start, end)
                    progress("extracting", 5 + 80 * end / max(analysis["page_count"], 1))
                    start = end + 1
                    continue

                pages = text_extraction.extract_pages(path, analysis, only_pages=missing_pages, pdf_doc=pdf_doc)
                pages, retry = text_validation.validate_pages(pages)
                if retry:
                    redone = {p["page_number"]: p for p in text_extraction.extract_pages(
                        path, analysis, force_ocr=set(retry), only_pages=set(retry), pdf_doc=pdf_doc)}
                    pages = [({**redone[p["page_number"]], "errors": [], "validation_status": "ok", "validation_notes": []}
                              if p["page_number"] in redone and redone[p["page_number"]]["paragraphs"] else p) for p in pages]
                    pages, _ = text_validation.validate_pages(pages)
                chunks = chunk_manager.build_chunks(pages)
                discovered_ocr_pages = set(analysis.get("ocr_pages", []))
                discovered_ocr_pages.update(p["page_number"] for p in pages if p.get("needs_ocr"))
                analysis["ocr_pages"] = sorted(discovered_ocr_pages)
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
                    analysis["pdf_type"] = (
                        "scanned" if len(discovered_ocr_pages) >= analysis["page_count"]
                        else "mixed" if discovered_ocr_pages
                        else "pending" if end < analysis["page_count"]
                        else "text"
                    )
                    doc.analysis = {k: analysis.get(k) for k in ("pdf_type", "ocr_pages", "metadata")}
                    db.commit()
                _schedule_batch_audio(doc_id, doc.user_id, start, end)
                progress("extracting", 5 + 80 * end / max(analysis["page_count"], 1))
                start = end + 1

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


def enrich_document(document_id: str) -> None:
    """Enrich completed page batches after source text is already ready to read."""
    if not settings.groq_api_key:
        return
    doc_id = uuid.UUID(document_id)
    last_page = 0
    batch_size = settings.processing_batch_pages
    while True:
        with SessionLocal() as db:
            rows = db.execute(
                select(DocumentPage.page_number, DocumentPage.extracted_text)
                .where(DocumentPage.document_id == doc_id, DocumentPage.page_number > last_page)
                .order_by(DocumentPage.page_number)
                .limit(batch_size)
            ).all()
        if not rows:
            return

        pages = [{"page_number": number, "paragraphs": [{"text": text or ""}]} for number, text in rows]
        enriched = groq_enrichment.enrich_pages(pages)
        if enriched:
            with SessionLocal() as db:
                for number, content in enriched.items():
                    db.execute(
                        update(DocumentPage)
                        .where(DocumentPage.document_id == doc_id, DocumentPage.page_number == number)
                        .values(ai_prepared_text=_remove_nuls(content["prepared_text"]), ai_summary=_remove_nuls(content["summary"]))
                    )
                db.commit()
        last_page = rows[-1].page_number


def generate_audio(document_id: str, engine: str, voice: str, language: str, from_page: int = 1, to_page: int | None = None) -> dict:
    with SessionLocal() as db:
        return voice_agent.generate_range(db, uuid.UUID(document_id), engine, voice, language, from_page, to_page)


@celery_app.task(name="pdfvoice.process_document")
def process_document_task(document_id: str) -> None:
    _process_and_schedule_enrichment(document_id)


def _process_and_schedule_enrichment(document_id: str) -> None:
    process_document(document_id)
    if not settings.groq_api_key:
        return
    with SessionLocal() as db:
        doc = db.get(Document, uuid.UUID(document_id))
        complete = doc is not None and doc.processing_status == "completed"
    if not complete:
        return
    try:
        if settings.task_backend == "celery":
            enrich_document_task.delay(document_id)
        else:
            _inline_enrichment_pool.submit(enrich_document, document_id)
    except Exception:
        # Source extraction and speech are already available; enrichment can be retried separately.
        log.exception("Could not queue optional Groq enrichment for document %s", document_id)


@celery_app.task(name="pdfvoice.generate_audio")
def generate_audio_task(document_id: str, engine: str, voice: str, language: str, from_page: int = 1, to_page: int | None = None) -> dict:
    return generate_audio(document_id, engine, voice, language, from_page, to_page)


@celery_app.task(name="pdfvoice.generate_segment_ids_audio")
def generate_segment_ids_task(document_id: str, segment_ids: list[int], engine: str, voice: str, language: str) -> None:
    _generate_segment_ids(document_id, segment_ids, engine, voice, language)


@celery_app.task(name="pdfvoice.enrich_document")
def enrich_document_task(document_id: str) -> None:
    enrich_document(document_id)


def dispatch(background_tasks, fn_name: str, *args) -> None:
    """Run via Celery when TASK_BACKEND=celery, otherwise via FastAPI BackgroundTasks."""
    if settings.task_backend == "celery":
        {"process_document": process_document_task, "generate_audio": generate_audio_task}[fn_name].delay(*args)
    else:
        task = _process_and_schedule_enrichment if fn_name == "process_document" else generate_audio
        background_tasks.add_task(task, *args)
