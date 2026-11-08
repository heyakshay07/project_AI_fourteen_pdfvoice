"""Agent 3 - Text Validation. Reports problems; never edits, drops or invents text."""
from collections import defaultdict

from app.services import ocr_service
from app.utils.text_utils import normalize_whitespace, sha1, word_count

GARBLED_RATIO = 0.05
GAP_RATIO = 0.90


def _garbled_ratio(text: str) -> float:
    if not text:
        return 0.0
    bad = sum(1 for ch in text if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\n\t\r") or 0xE000 <= ord(ch) <= 0xF8FF)
    return bad / len(text)


def validate_pages(pages: list[dict]) -> tuple[list[dict], list[int]]:
    """Annotate each page with validation_status/validation_notes. Returns (pages, pages_worth_an_OCR_retry)."""
    retry: list[int] = []
    seen_page_hash: dict[str, int] = {}
    para_pages: dict[str, set[int]] = defaultdict(set)

    for p in pages:
        notes: list[str] = list(p.get("errors", []))
        text = "\n\n".join(x["text"] for x in p["paragraphs"])
        status = "ok"

        if p["errors"]:
            status = "failed"
        if not text.strip():
            if status != "failed":
                status = "empty"
            notes.append("No text could be extracted from this page (it may be blank or an image).")
        else:
            if p["method"] == "text":
                if _garbled_ratio(text) > GARBLED_RATIO:
                    status = "warning"
                    notes.append("Extracted text contains many unreadable characters; OCR retry recommended.")
                    if ocr_service.tesseract_available():
                        retry.append(p["page_number"])
                raw = p.get("raw_word_count", 0)
                got = word_count(text)
                if raw and got < GAP_RATIO * raw:
                    status = "warning"
                    notes.append(f"Possible extraction gap: PyMuPDF sees {raw} words, {got} were extracted.")
            h = sha1(normalize_whitespace(text))
            if h in seen_page_hash:
                status = "warning" if status == "ok" else status
                notes.append(f"Page text is identical to page {seen_page_hash[h]}.")
            else:
                seen_page_hash[h] = p["page_number"]
            for para in p["paragraphs"]:
                if len(para["text"]) < 120:
                    para_pages[normalize_whitespace(para["text"])].add(p["page_number"])

        p["validation_status"], p["validation_notes"] = status, notes

    # Repeated short paragraphs (running headers / footers / page numbers) are only reported.
    repeated = {t for t, pg in para_pages.items() if len(pg) >= 3 and len(t) > 3}
    for p in pages:
        hits = [x["text"] for x in p["paragraphs"] if normalize_whitespace(x["text"]) in repeated]
        if hits:
            p["validation_notes"].append(f"{len(hits)} repeated header/footer-like line(s) kept as is.")
    return pages, retry
