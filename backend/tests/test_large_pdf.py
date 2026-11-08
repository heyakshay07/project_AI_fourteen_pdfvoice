import time

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
