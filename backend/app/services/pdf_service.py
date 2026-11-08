"""Low-level PDF operations built on PyMuPDF: open/validate, per-page analysis, text extraction.

Reading order: blocks are grouped into vertical bands separated by full-width blocks. Inside a band that
has blocks on both halves of the page, the left column is read first, then the right column. Otherwise
blocks are read top-to-bottom, left-to-right.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import fitz  # PyMuPDF

from app.core.config import settings
from app.utils.text_utils import join_lines


class PdfError(Exception):
    """Raised for corrupted / encrypted / unreadable PDFs. `code` is machine readable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PageAnalysis:
    page_number: int
    char_count: int
    image_count: int
    needs_ocr: bool
    width: float
    height: float


@dataclass
class Paragraph:
    text: str
    bbox: tuple[float, float, float, float]
    is_heading: bool = False


@dataclass
class ExtractedPage:
    page_number: int
    method: str  # text | ocr | none
    width: float
    height: float
    paragraphs: list[Paragraph] = field(default_factory=list)
    raw_word_count: int = 0  # words PyMuPDF reports for the page (for gap detection)


def open_pdf(path: Path) -> "fitz.Document":
    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise PdfError("corrupted", f"The file could not be opened as a PDF: {exc}") from exc
    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise PdfError("encrypted", "The PDF is password-protected. Remove the password and upload it again.")
    if doc.page_count == 0:
        doc.close()
        raise PdfError("empty", "The PDF has no pages.")
    return doc


def analyze_page(page: "fitz.Page") -> PageAnalysis:
    text = page.get_text("text") or ""
    chars = len("".join(text.split()))
    images = len(page.get_images(full=True))
    needs_ocr = chars < settings.ocr_min_chars
    r = page.rect
    return PageAnalysis(page.number + 1, chars, images, needs_ocr, float(r.width), float(r.height))


def _split_block_by_column(block: dict) -> list[dict]:
    """MuPDF can put lines from side-by-side columns in one block. Split them by horizontal overlap."""
    groups: list[dict] = []
    for line in block.get("lines", []):
        text = "".join(sp.get("text", "") for sp in line.get("spans", []))
        if not text.strip():
            continue
        sizes = [float(sp.get("size", 0)) for sp in line["spans"] if sp.get("text", "").strip()]
        x0, y0, x1, y1 = line["bbox"]
        target = None
        for g in groups:
            gx0, _, gx1, _ = g["bbox"]
            overlap = min(x1, gx1) - max(x0, gx0)
            if overlap > 0.2 * min(x1 - x0, gx1 - gx0):
                target = g
                break
        if target is None:
            groups.append({"bbox": [x0, y0, x1, y1], "lines": [text], "sizes": sizes})
        else:
            b = target["bbox"]
            target["bbox"] = [min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)]
            target["lines"].append(text)
            target["sizes"].extend(sizes)
    return groups


def _order_blocks(blocks: list[dict], page_width: float) -> list[dict]:
    """Return blocks in natural reading order (handles 1- and 2-column layouts)."""
    if len(blocks) < 2:
        return blocks
    mid = page_width / 2
    full_width = lambda b: (b["bbox"][2] - b["bbox"][0]) > 0.6 * page_width
    straddles = lambda b: b["bbox"][0] < mid - 0.05 * page_width and b["bbox"][2] > mid + 0.05 * page_width

    by_y = sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
    ordered: list[dict] = []
    band: list[dict] = []

    def flush():
        if not band:
            return
        left = [b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 < mid]
        right = [b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 >= mid]
        if len(left) >= 2 and len(right) >= 2:
            ordered.extend(sorted(left, key=lambda b: b["bbox"][1]))
            ordered.extend(sorted(right, key=lambda b: b["bbox"][1]))
        else:
            ordered.extend(sorted(band, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0])))
        band.clear()

    for b in by_y:
        if full_width(b) or straddles(b):
            flush()
            ordered.append(b)
        else:
            band.append(b)
    flush()
    return ordered


def extract_text_page(page: "fitz.Page") -> ExtractedPage:
    d = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
    width, height = float(page.rect.width), float(page.rect.height)
    text_blocks = [b for b in d.get("blocks", []) if b.get("type") == 0]

    all_sizes: list[float] = []
    prepared = []
    for b in text_blocks:
        for g in _split_block_by_column(b):
            all_sizes.extend(g["sizes"])
            prepared.append({"bbox": tuple(g["bbox"]), "lines": g["lines"], "sizes": g["sizes"]})

    body_size = median(all_sizes) if all_sizes else 0.0
    paragraphs: list[Paragraph] = []
    for b in _order_blocks(prepared, width):
        text = join_lines(b["lines"], settings.dehyphenate)
        if not text:
            continue
        biggest = max(b["sizes"]) if b["sizes"] else 0.0
        heading = bool(body_size) and biggest >= body_size * 1.25 and len(b["lines"]) <= 3 and len(text) < 160
        paragraphs.append(Paragraph(text=text, bbox=b["bbox"], is_heading=heading))

    raw_words = len(page.get_text("words"))
    return ExtractedPage(page.number + 1, "text" if paragraphs else "none", width, height, paragraphs, raw_words)


def page_dimensions(path: Path) -> list[tuple[float, float]]:
    with fitz.open(str(path)) as doc:
        return [(float(p.rect.width), float(p.rect.height)) for p in doc]


def median_or_zero(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0
