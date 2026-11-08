"""OCR via Tesseract (pytesseract). Returns paragraphs with bounding boxes in PDF points."""
import io
from dataclasses import dataclass

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from app.core.config import settings


@dataclass
class OcrParagraph:
    text: str
    bbox: tuple[float, float, float, float]  # PDF points


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def installed_languages() -> set[str]:
    try:
        return set(pytesseract.get_languages(config=""))
    except Exception:
        return set()


def effective_languages() -> str:
    """Requested languages that are actually installed (so a missing 'mar' pack doesn't break OCR)."""
    wanted = [l for l in settings.ocr_languages.split("+") if l]
    have = installed_languages()
    usable = [l for l in wanted if l in have] if have else wanted
    return "+".join(usable) if usable else "eng"


def ocr_page(page: "fitz.Page") -> list[OcrParagraph]:
    zoom = settings.ocr_dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    data = pytesseract.image_to_data(image, lang=effective_languages(), output_type=pytesseract.Output.DICT)

    # group words -> lines -> paragraphs (Tesseract block/par/line numbering)
    paras: dict[tuple[int, int], dict[int, list]] = {}
    boxes: dict[tuple[int, int], list[float]] = {}
    order: list[tuple[int, int]] = []
    for i, raw in enumerate(data["text"]):
        word = (raw or "").strip()
        if not word or float(data["conf"][i]) < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i])
        if key not in paras:
            paras[key], boxes[key] = {}, [1e9, 1e9, -1e9, -1e9]
            order.append(key)
        paras[key].setdefault(data["line_num"][i], []).append(word)
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        b = boxes[key]
        b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)

    out = []
    for key in order:
        text = " ".join(" ".join(ws) for _, ws in sorted(paras[key].items()))
        b = boxes[key]
        out.append(OcrParagraph(text=text, bbox=(b[0] / zoom, b[1] / zoom, b[2] / zoom, b[3] / zoom)))
    return out
