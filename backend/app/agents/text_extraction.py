"""Agent 2 - Text Extraction: PyMuPDF for selectable text, Tesseract OCR for scanned pages."""
from collections.abc import Callable
from pathlib import Path

from app.agents import groq_enrichment
from app.services import ocr_service, pdf_service


def _clean_text(text: str) -> str:
    """Remove characters PostgreSQL cannot store in text or JSON string values."""
    return text.replace("\x00", "")


def extract_pages(
    path: Path,
    analysis: dict,
    force_ocr: set[int] | None = None,
    only_pages: set[int] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Return one dict per page: {page_number, method, width, height, paragraphs[], raw_word_count, errors[]}."""
    force_ocr = force_ocr or set()
    ocr_needed = set(analysis.get("ocr_pages", [])) | force_ocr
    results: list[dict] = []
    doc = pdf_service.open_pdf(path)
    try:
        targets = [n for n in range(1, doc.page_count + 1) if only_pages is None or n in only_pages]
        for done, number in enumerate(targets, start=1):
            page = doc[number - 1]
            errors: list[str] = []
            entry = {
                "page_number": number, "method": "none", "width": float(page.rect.width),
                "height": float(page.rect.height), "paragraphs": [], "raw_word_count": 0, "errors": errors,
            }
            try:
                if number in ocr_needed:
                    paras = []
                    local_ocr_error = None
                    tesseract_ready = ocr_service.tesseract_available()
                    if tesseract_ready:
                        try:
                            paras = ocr_service.ocr_page(page)
                        except Exception as exc:
                            local_ocr_error = exc
                    if paras:
                        entry["paragraphs"] = [
                            {"text": _clean_text(p.text), "bbox": list(p.bbox), "is_heading": False} for p in paras
                        ]
                        entry["method"] = "ocr"
                    else:
                        # Do not send blank pages to a paid remote model. Groq OCR is
                        # a fallback only when local OCR is missing or failed.
                        groq_text = groq_enrichment.extract_scanned_page(page) if not tesseract_ready or local_ocr_error else None
                        if groq_text:
                            entry["paragraphs"] = [{
                                "text": _clean_text(groq_text),
                                "bbox": [0.0, 0.0, entry["width"], entry["height"]],
                                "is_heading": False,
                            }]
                            entry["method"] = "ocr"
                        elif local_ocr_error:
                            errors.append(f"OCR failed: {local_ocr_error}")
                        elif not tesseract_ready:
                            errors.append("OCR is required for this page but Tesseract and Groq OCR are unavailable.")
                else:
                    ex = pdf_service.extract_text_page(page)
                    entry["paragraphs"] = [
                        {"text": _clean_text(p.text), "bbox": list(p.bbox), "is_heading": p.is_heading} for p in ex.paragraphs
                    ]
                    entry["method"] = ex.method
                    entry["raw_word_count"] = ex.raw_word_count
            except Exception as exc:
                errors.append(f"Extraction failed: {exc}")
            results.append(entry)
            if progress:
                progress(done, len(targets))
    finally:
        doc.close()
    return results
