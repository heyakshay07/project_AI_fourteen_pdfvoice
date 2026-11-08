import shutil

import pytest

from app.agents import pdf_analyzer, text_extraction, text_validation
from app.utils.text_utils import words
from tests import pdf_factory as F
from tests.conftest import upload_and_process


def _extract(tmp_path, data: bytes):
    p = tmp_path / "t.pdf"
    p.write_bytes(data)
    analysis = pdf_analyzer.analyze_pdf(p)
    pages = text_extraction.extract_pages(p, analysis)
    pages, retry = text_validation.validate_pages(pages)
    return analysis, pages


def _text(page) -> str:
    return "\n\n".join(x["text"] for x in page["paragraphs"])


def test_analyzer_detects_text_pdf(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(F.small_pdf(3))
    a = pdf_analyzer.analyze_pdf(p)
    assert a["page_count"] == 3 and a["pdf_type"] == "text" and a["ocr_pages"] == []


def test_analyzer_detects_scanned_and_mixed(tmp_path):
    p = tmp_path / "s.pdf"
    p.write_bytes(F.scanned_pdf())
    assert pdf_analyzer.analyze_pdf(p)["pdf_type"] == "scanned"
    p.write_bytes(F.mixed_pdf())
    a = pdf_analyzer.analyze_pdf(p)
    assert a["pdf_type"] == "mixed" and a["ocr_pages"] == [2]


def test_text_extraction_preserves_every_word(tmp_path):
    _, pages = _extract(tmp_path, F.small_pdf(2))
    got = words(" ".join(_text(p) for p in pages))
    for i in (1, 2):
        for w in words(F._para(i)):
            assert w in got
    assert [p["page_number"] for p in pages] == [1, 2]  # page order


def test_heading_detected(tmp_path):
    _, pages = _extract(tmp_path, F.small_pdf(1))
    assert pages[0]["paragraphs"][0]["text"].startswith("Chapter 1")
    assert pages[0]["paragraphs"][0]["is_heading"] is True


def test_multi_column_reading_order(tmp_path):
    _, pages = _extract(tmp_path, F.two_column_pdf())
    text = _text(pages[0])
    markers = ["Two Column Title"] + [s.split()[0] for s in F.LEFT] + [s.split()[0] for s in F.RIGHT]
    positions = [text.index(m) for m in markers]
    assert positions == sorted(positions), f"columns interleaved: {text!r}"


def test_table_cells_all_extracted(tmp_path):
    _, pages = _extract(tmp_path, F.table_pdf())
    text = _text(pages[0])
    for row in F.TABLE_CELLS:
        for cell in row:
            assert cell in text


def test_multilingual_text_is_preserved(tmp_path):
    _, pages = _extract(tmp_path, F.multilang_pdf())
    text = " ".join(_text(pages[0]).split())
    for sentence in ["été, garçon, où.", "Größe, Mädchen, schön.", "¿Cómo estás? ¡Muy bien!"]:
        assert sentence in text


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_scanned_pdf_uses_ocr(tmp_path):
    _, pages = _extract(tmp_path, F.scanned_pdf())
    assert pages[0]["method"] == "ocr"
    got = {w.lower() for w in words(_text(pages[0]))}
    expected = {w.lower() for w in words(F.SCAN_TEXT)}
    assert len(got & expected) / len(expected) > 0.8, got


def test_blank_page_is_reported_not_invented(tmp_path):
    _, pages = _extract(tmp_path, F.blank_pdf())
    assert pages[0]["paragraphs"] == []
    assert pages[0]["validation_status"] in {"empty", "failed"}
    assert pages[0]["validation_notes"]


def test_validation_flags_duplicate_pages():
    page = {"page_number": 1, "method": "text", "errors": [], "raw_word_count": 3,
            "paragraphs": [{"text": "same words here", "bbox": [0, 0, 1, 1], "is_heading": False}]}
    pages, _ = text_validation.validate_pages([dict(page), dict(page, page_number=2)])
    assert pages[1]["validation_status"] == "warning" and any("identical" in n for n in pages[1]["validation_notes"])


def test_validation_flags_extraction_gap():
    page = {"page_number": 1, "method": "text", "errors": [], "raw_word_count": 100,
            "paragraphs": [{"text": "only a few words", "bbox": [0, 0, 1, 1], "is_heading": False}]}
    pages, _ = text_validation.validate_pages([page])
    assert pages[0]["validation_status"] == "warning" and "gap" in pages[0]["validation_notes"][0]


def test_api_text_endpoint_after_processing(client, auth):
    doc = upload_and_process(client, auth, F.small_pdf(2))
    r = client.get(f"/api/v1/pdf/{doc['id']}/text", headers=auth)
    assert r.status_code == 200 and len(r.json()["pages"]) == 2
    one = client.get(f"/api/v1/pdf/{doc['id']}/text?page=2", headers=auth).json()["pages"][0]
    assert one["page_number"] == 2 and one["sentences"] and one["sentences"][0]["bbox"]
    assert client.get(f"/api/v1/pdf/{doc['id']}/text?page=99", headers=auth).status_code == 404
    pages = client.get(f"/api/v1/pdf/{doc['id']}/pages", headers=auth).json()
    assert [p["page_number"] for p in pages] == [1, 2]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_api_processes_scanned_pdf(client, auth):
    doc = upload_and_process(client, auth, F.scanned_pdf())
    assert doc["pdf_type"] == "scanned" and doc["ocr_page_count"] == 1
    page = client.get(f"/api/v1/pdf/{doc['id']}/text?page=1", headers=auth).json()["pages"][0]
    assert page["extraction_method"] == "ocr" and "Scanned" in page["text"]
