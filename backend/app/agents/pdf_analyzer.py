"""Agent 1 - PDF Analyzer: validity, encryption, page count, text-vs-scanned detection."""
from pathlib import Path

from app.core.config import settings
from app.services import pdf_service
from app.services.pdf_service import PdfError


def analyze_pdf(path: Path) -> dict:
    doc = pdf_service.open_pdf(path)  # raises PdfError(corrupted | encrypted | empty)
    try:
        if doc.page_count > settings.max_pages:
            raise PdfError("too_many_pages", f"The PDF has {doc.page_count} pages; the limit is {settings.max_pages}.")
        pages = []
        for page in doc:
            try:
                a = pdf_service.analyze_page(page)
                pages.append(
                    {
                        "page_number": a.page_number,
                        "char_count": a.char_count,
                        "image_count": a.image_count,
                        "needs_ocr": a.needs_ocr,
                        "width": a.width,
                        "height": a.height,
                    }
                )
            except Exception as exc:  # a broken page must not abort the whole analysis
                pages.append(
                    {"page_number": page.number + 1, "char_count": 0, "image_count": 0, "needs_ocr": True,
                     "width": 0.0, "height": 0.0, "error": str(exc)}
                )
        ocr_pages = [p["page_number"] for p in pages if p["needs_ocr"]]
        if not ocr_pages:
            pdf_type = "text"
        elif len(ocr_pages) == len(pages):
            pdf_type = "scanned"
        else:
            pdf_type = "mixed"
        return {
            "page_count": doc.page_count,
            "pdf_type": pdf_type,
            "ocr_pages": ocr_pages,
            "pages": pages,
            "metadata": {k: v for k, v in (doc.metadata or {}).items() if v},
        }
    finally:
        doc.close()
