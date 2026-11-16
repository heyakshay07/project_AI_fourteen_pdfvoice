import time
import uuid

from app.core.database import SessionLocal
from app.models.audio_segment import AudioSegment
from app.models.document import Document
from sqlalchemy import select
from app.tasks import processing_tasks
from tests import pdf_factory as F
from tests.conftest import upload_and_process


def test_large_pdf_150_pages_processes_completely(client, auth):
    t0 = time.time()
    doc = upload_and_process(client, auth, F.large_pdf(150))
    assert doc["total_pages"] == 150 and doc["processing_status"] == "completed"
    prog = client.get(f"/api/v1/pdf/{doc['id']}/progress", headers=auth).json()
    assert prog["pages_extracted"] == 150 and prog["pages_failed"] == 0 and prog["chunks_total"] >= 150
    pages = client.get(f"/api/v1/pdf/{doc['id']}/pages", headers=auth).json()
    assert [p["page_number"] for p in pages] == list(range(1, 151))
    # every chunk range is contiguous and covers all sentences on its page
    segs = client.get(f"/api/v1/voice/{doc['id']}/segments", headers=auth).json()
    by_page = {}
    for s in segs:
        by_page.setdefault(s["page_number"], []).append(s)
    for p in pages:
        ss = sorted(by_page[p["page_number"]], key=lambda s: s["chunk_index"])
        assert ss[0]["sentence_start"] == 0 and ss[-1]["sentence_end"] == p["sentence_count"] - 1
        assert all(a["sentence_end"] + 1 == b["sentence_start"] for a, b in zip(ss, ss[1:]))
    assert time.time() - t0 < 120
    text = client.get(f"/api/v1/pdf/{doc['id']}/text?start=148&limit=10", headers=auth).json()["pages"]
    assert [p["page_number"] for p in text] == [148, 149, 150]


def test_audio_batches_prioritize_first_three_chunks(client, auth, monkeypatch):
    doc = upload_and_process(client, auth, F.large_pdf(8))
    with SessionLocal() as db:
        row = db.get(Document, uuid.UUID(doc["id"]))
        user_id = row.user_id
        expected_ids = db.scalars(
            select(AudioSegment.id)
            .where(AudioSegment.document_id == row.id, AudioSegment.page_number <= 4)
            .order_by(AudioSegment.page_number, AudioSegment.chunk_index)
        ).all()

    scheduled = []
    monkeypatch.setattr(processing_tasks, "_schedule_segment_audio", lambda _doc, ids, *_voice: scheduled.append(list(ids)))
    processing_tasks._schedule_batch_audio(uuid.UUID(doc["id"]), user_id, 1, 4)

    assert scheduled[0] == expected_ids[:3]
    assert scheduled[1] == expected_ids[3:]
    assert len(expected_ids) >= 4
    assert processing_tasks.celery_app.conf.task_routes["pdfvoice.process_document"]["queue"] == "extract"
    assert processing_tasks.celery_app.conf.task_routes["pdfvoice.generate_segment_ids_audio"]["queue"] == "tts"
