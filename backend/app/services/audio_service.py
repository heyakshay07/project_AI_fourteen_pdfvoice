"""Assembles per-sentence clips into one chunk file, with exact sentence timings, and stores it."""
import hashlib
import tempfile
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.storage_service import get_storage
from app.utils import audio_utils


def voice_key(engine: str, voice: str, language: str) -> str:
    return hashlib.sha1(f"{engine}|{voice}|{language}".encode()).hexdigest()[:16]


def assemble(clips: list[tuple[np.ndarray, int]], sentence_indices: list[int], heading_flags: list[bool], para_end_flags: list[bool]):
    """Concatenate clips with natural pauses. Returns (audio, sample_rate, timings).

    A sentence's [start, end) window includes the pause after it, so the highlight never flickers off.
    """
    if not clips:
        raise ValueError("No audio clips to assemble")
    sr = clips[0][1]
    pieces, timings, cursor = [], [], 0.0
    for (audio, clip_sr), idx, heading, para_end in zip(clips, sentence_indices, heading_flags, para_end_flags):
        if clip_sr != sr:
            raise ValueError("Mixed sample rates inside one chunk")
        gap = settings.heading_gap_seconds if heading else settings.sentence_gap_seconds
        if para_end and not heading:
            gap = settings.sentence_gap_seconds + 0.15
        clip = np.concatenate([audio, audio_utils.silence(gap, sr)])
        start, end = cursor, cursor + len(clip) / sr
        timings.append({"sentence": idx, "start": round(start, 3), "end": round(end, 3)})
        pieces.append(clip)
        cursor = end
    return np.concatenate(pieces), sr, timings


def store_audio(key_base: str, audio: np.ndarray, sample_rate: int) -> tuple[str, float]:
    """Write audio under `key_base` + extension. Returns (storage_key, duration_seconds)."""
    storage = get_storage()
    fmt = settings.audio_format if (settings.audio_format == "wav" or audio_utils.ffmpeg_available()) else "wav"
    with tempfile.TemporaryDirectory(prefix="pdfvoice_audio_") as tmp:
        wav = Path(tmp) / "chunk.wav"
        audio_utils.write_wav(wav, audio, sample_rate)
        if fmt == "mp3":
            out = Path(tmp) / "chunk.mp3"
            audio_utils.encode_mp3(wav, out)
        else:
            out = wav
        key = f"{key_base}.{fmt}"
        storage.put_file(key, out)
    return key, len(audio) / sample_rate


def media_type_for(key: str) -> str:
    return "audio/mpeg" if key.endswith(".mp3") else "audio/wav"
