"""Agent 2 - Text Extraction: PyMuPDF for selectable text, Tesseract OCR for scanned pages."""
from collections.abc import Callable
from pathlib import Path

from app.services import ocr_service, pdf_service


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
                    if not ocr_service.tesseract_available():
                        errors.append("OCR is required for this page but Tesseract is not installed.")
                    else:
                        paras = ocr_service.ocr_page(page)
                        entry["paragraphs"] = [
                            {"text": p.text, "bbox": list(p.bbox), "is_heading": False} for p in paras
                        ]
                        entry["method"] = "ocr" if paras else "none"
                else:
                    ex = pdf_service.extract_text_page(page)
                    entry["paragraphs"] = [
                        {"text": p.text, "bbox": list(p.bbox), "is_heading": p.is_heading} for p in ex.paragraphs
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
