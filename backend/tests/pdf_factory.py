"""Builds the test PDFs on the fly with PyMuPDF (no binary fixtures to commit)."""
import io

import fitz
from PIL import Image

LOREM = [
    "The quick brown fox jumps over the lazy dog. Dr. Watson examined the evidence carefully.",
    "Reading aloud requires every single word to be preserved! Is that clear? Yes, it is.",
    "Sentence boundaries matter because highlighting follows them. This is the final sentence of the paragraph.",
]


def _para(i: int) -> str:
    return " ".join(f"Page {i} sentence {k}: {LOREM[k % 3]}" for k in range(4))


def small_pdf(pages: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 90), f"Chapter {i}", fontsize=22, fontname="helv")
        page.insert_textbox(fitz.Rect(50, 110, 550, 500), _para(i), fontsize=11, fontname="helv")
    return doc.tobytes()


def large_pdf(pages: int = 150) -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 60, 550, 700), _para(i) + " " + _para(i), fontsize=11, fontname="helv")
    return doc.tobytes()


LEFT = ["LEFT-ONE alpha beta gamma delta.", "LEFT-TWO epsilon zeta eta theta.", "LEFT-THREE iota kappa lambda."]
RIGHT = ["RIGHT-ONE mu nu xi omicron.", "RIGHT-TWO pi rho sigma tau.", "RIGHT-THREE upsilon phi chi."]


def two_column_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 555, 80), "Two Column Title", fontsize=20, fontname="helv")
    for k, (l, r) in enumerate(zip(LEFT, RIGHT)):
        y = 110 + k * 90
        page.insert_textbox(fitz.Rect(40, y, 280, y + 70), l, fontsize=11, fontname="helv")
        page.insert_textbox(fitz.Rect(315, y, 555, y + 70), r, fontsize=11, fontname="helv")
    return doc.tobytes()


TABLE_CELLS = [["Name", "Qty", "Price"], ["Apple", "10", "1.50"], ["Banana", "24", "0.75"], ["Cherry", "5", "12.00"]]


def table_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    for r, row in enumerate(TABLE_CELLS):
        for c, cell in enumerate(row):
            rect = fitz.Rect(60 + c * 120, 100 + r * 30, 180 + c * 120, 130 + r * 30)
            page.draw_rect(rect)
            page.insert_textbox(rect + (4, 6, -4, 0), cell, fontsize=11, fontname="helv")
    return doc.tobytes()


MULTILANG = [
    "Bonjour tout le monde. Ceci est une phrase en français avec des accents: été, garçon, où.",
    "Guten Tag. Das ist ein deutscher Satz mit Umlauten: Größe, Mädchen, schön.",
    "Hola. Esta es una oración en español: ¿Cómo estás? ¡Muy bien!",
]


def multilang_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 500), "\n\n".join(MULTILANG), fontsize=12, fontname="helv")
    return doc.tobytes()


SCAN_TEXT = "Scanned documents need optical character recognition. This sentence was rendered as an image."


def scanned_pdf() -> bytes:
    """A page that contains ONLY a raster image of text (no selectable text)."""
    src = fitz.open()
    p = src.new_page()
    p.insert_textbox(fitz.Rect(50, 80, 550, 300), SCAN_TEXT, fontsize=20, fontname="helv")
    pix = p.get_pixmap(matrix=fitz.Matrix(3, 3))
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    out = fitz.open()
    page = out.new_page()
    page.insert_image(page.rect, stream=buf.getvalue())
    return out.tobytes()


def mixed_pdf() -> bytes:
    a, b = fitz.open(stream=small_pdf(1)), fitz.open(stream=scanned_pdf())
    a.insert_pdf(b)
    return a.tobytes()


def encrypted_pdf() -> bytes:
    doc = fitz.open(stream=small_pdf(1))
    return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")


def blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()
    return doc.tobytes()


CORRUPTED = b"%PDF-1.4\nthis is definitely not a real pdf body \x00\x01\x02"
