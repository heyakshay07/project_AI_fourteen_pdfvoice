"""Agent 4 - Chunk Management: sentences + chunks per page. Every sentence belongs to exactly one chunk."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audio_segment import AudioSegment
from app.utils.text_utils import normalize_whitespace, split_sentences


def build_sentences(page: dict) -> list[dict]:
    """Sentences in reading order with the bbox of their source paragraph (PDF points)."""
    out: list[dict] = []
    for para in page["paragraphs"]:
        parts = split_sentences(para["text"])
        for k, s in enumerate(parts):
            out.append(
                {
                    "i": len(out),
                    "text": s,
                    "bbox": para["bbox"],
                    "heading": bool(para.get("is_heading")),
                    "para_end": k == len(parts) - 1,
                }
            )
    return out


def chunk_sentences(sentences: list[dict], max_chars: int | None = None) -> list[dict]:
    """Greedy grouping; a sentence is never split, so one long sentence may exceed max_chars."""
    max_chars = max_chars or settings.chunk_max_chars
    chunks: list[dict] = []
    start, size = 0, 0
    for idx, s in enumerate(sentences):
        n = len(s["text"]) + 1
        if idx > start and size + n > max_chars:
            chunks.append({"chunk_index": len(chunks), "sentence_start": start, "sentence_end": idx - 1, "char_count": size})
            start, size = idx, 0
        size += n
    if sentences:
        chunks.append({"chunk_index": len(chunks), "sentence_start": start, "sentence_end": len(sentences) - 1, "char_count": size})
    return chunks


def verify_chunks(sentences: list[dict], chunks: list[dict]) -> None:
    """Raise if any sentence is lost/duplicated - the 'never lose words' guarantee."""
    expected = 0
    for c in chunks:
        if c["sentence_start"] != expected or c["sentence_end"] < c["sentence_start"]:
            raise ValueError(f"Chunk gap or overlap at sentence {expected}")
        expected = c["sentence_end"] + 1
    if expected != len(sentences):
        raise ValueError(f"Chunks cover {expected} of {len(sentences)} sentences")


def page_text(page: dict) -> str:
    return "\n\n".join(p["text"] for p in page["paragraphs"])


def build_chunks(pages: list[dict]) -> dict[int, dict]:
    """{page_number: {"sentences": [...], "chunks": [...]}} with the integrity check applied."""
    result: dict[int, dict] = {}
    for p in pages:
        sentences = build_sentences(p)
        chunks = chunk_sentences(sentences)
        verify_chunks(sentences, chunks)
        joined = normalize_whitespace(" ".join(s["text"] for s in sentences))
        if joined != normalize_whitespace(page_text(p)):
            raise ValueError(f"Text changed while splitting page {p['page_number']}")
        result[p["page_number"]] = {"sentences": sentences, "chunks": chunks}
    return result


def chunk_progress(db: Session, document_id) -> dict:
    """Processed (audio ready) vs unprocessed chunks for a document."""
    rows = db.execute(
        select(AudioSegment.generation_status, func.count()).where(AudioSegment.document_id == document_id).group_by(AudioSegment.generation_status)
    ).all()
    counts = {status: n for status, n in rows}
    total = sum(counts.values())
    return {"total": total, "ready": counts.get("ready", 0), "pending": counts.get("pending", 0), "failed": counts.get("failed", 0)}
