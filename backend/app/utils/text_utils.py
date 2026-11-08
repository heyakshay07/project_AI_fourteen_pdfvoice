"""Text helpers. Nothing here rewrites or drops words: splitting only changes where whitespace is."""
import hashlib
import re

_WS = re.compile(r"\s+")
_WORD = re.compile(r"\w+", re.UNICODE)

# Sentence terminators: Latin + Devanagari danda
_BOUNDARY = re.compile(r"""[.!?\u2026\u0964\u0965]+["'\u201d\u2019)\]]*\s+""")
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "fig", "eq", "no", "nos",
    "vol", "pp", "p", "ch", "sec", "al", "approx", "dept", "est", "inc", "ltd", "co", "corp", "mt", "gen",
    "col", "capt", "lt", "sgt", "rev", "hon", "u.s", "u.k", "a.m", "p.m", "ph.d", "cf", "ca",
}


def normalize_whitespace(text: str) -> str:
    return _WS.sub(" ", text).strip()


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _is_boundary(text: str, match: re.Match) -> bool:
    terminator = match.group(0).strip()
    before = text[: match.start()]
    after = text[match.end():]
    if not after:
        return True
    # "?" and "!" and Devanagari danda always end a sentence
    if terminator[0] in "?!\u0964\u0965":
        return True
    last_token = before.rsplit(None, 1)[-1] if before.strip() else ""
    last_token = last_token.lstrip("(\"'\u201c\u2018[").lower()
    if last_token.rstrip(".") in _ABBREVIATIONS and len(terminator.rstrip("\"')]\u201d\u2019")) == 1:
        return False
    if re.fullmatch(r"[a-z]", last_token.rstrip(".")) and len(last_token.rstrip(".")) == 1:
        return False  # a single initial, e.g. "J. Smith"
    if after[0].islower():
        return False
    return True


def split_sentences(text: str) -> list[str]:
    """Split text into sentences. ''.join with single spaces reproduces the normalized input."""
    text = normalize_whitespace(text)
    if not text:
        return []
    sentences, start = [], 0
    for m in _BOUNDARY.finditer(text):
        if _is_boundary(text, m):
            sentences.append(text[start : m.end()].strip())
            start = m.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def join_lines(lines: list[str], dehyphenate: bool = True) -> str:
    """Join wrapped lines of one paragraph. Optionally repairs 'inter-\\nnational' -> 'international'."""
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
        elif dehyphenate and out.endswith("-") and len(out) > 1 and out[-2].isalpha() and line[0].islower():
            out = out[:-1] + line
        else:
            out = out + " " + line
    return out
