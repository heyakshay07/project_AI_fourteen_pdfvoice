import pytest

from app.agents import chunk_manager
from app.utils.text_utils import normalize_whitespace, split_sentences


@pytest.mark.parametrize("text", [
    "Dr. Smith arrived at 3 p.m. on Fig. 2. He said hello! Did anyone answer? No one did.",
    "J. K. Rowling wrote it. e.g. this one. The U.S. economy grew 3.5% last year. Next.",
    "नमस्ते दुनिया। यह दूसरा वाक्य है। तीसरा वाक्य भी है।",
    "He said \"stop.\" Then he left. (Really.) Done",
    "No terminator at all",
])
def test_sentence_split_loses_nothing(text):
    s = split_sentences(text)
    assert " ".join(s) == normalize_whitespace(text)


def test_abbreviations_do_not_split():
    assert split_sentences("Dr. Smith met Mr. Jones.") == ["Dr. Smith met Mr. Jones."]
    assert len(split_sentences("It ended. Then it began. Finally it ended!")) == 3
    assert len(split_sentences("नमस्ते दुनिया। यह दूसरा वाक्य है।")) == 2


def _page(paras):
    return {"page_number": 1, "paragraphs": [{"text": t, "bbox": [0, 0, 10, 10], "is_heading": h} for t, h in paras]}


def test_chunks_cover_every_sentence_exactly_once():
    page = _page([("Title Words", True)] + [("One sentence here. " * 30, False)] * 3)
    sentences = chunk_manager.build_sentences(page)
    chunks = chunk_manager.chunk_sentences(sentences, max_chars=200)
    chunk_manager.verify_chunks(sentences, chunks)
    covered = [i for c in chunks for i in range(c["sentence_start"], c["sentence_end"] + 1)]
    assert covered == list(range(len(sentences)))
    assert len(chunks) > 1


def test_long_sentence_is_never_split():
    long = "word " * 400 + "end."
    sentences = chunk_manager.build_sentences(_page([(long, False)]))
    chunks = chunk_manager.chunk_sentences(sentences, max_chars=100)
    assert len(sentences) == 1 and len(chunks) == 1


def test_verify_detects_gap():
    sentences = [{"text": "a."}, {"text": "b."}, {"text": "c."}]
    with pytest.raises(ValueError):
        chunk_manager.verify_chunks(sentences, [{"sentence_start": 0, "sentence_end": 0}, {"sentence_start": 2, "sentence_end": 2}])


def test_build_chunks_preserves_page_text():
    pages = [_page([("First paragraph. It has two sentences.", False), ("Second paragraph alone.", False)])]
    out = chunk_manager.build_chunks(pages)[1]
    joined = " ".join(s["text"] for s in out["sentences"])
    assert joined == "First paragraph. It has two sentences. Second paragraph alone."
    assert out["sentences"][1]["para_end"] and not out["sentences"][0]["para_end"]


def test_empty_page_has_no_chunks():
    assert chunk_manager.build_chunks([_page([])])[1] == {"sentences": [], "chunks": []}
