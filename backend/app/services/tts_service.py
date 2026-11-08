"""Pluggable TTS providers. Each returns mono float32 audio + sample rate for ONE piece of text.

Kokoro (local) is the primary engine. Edge TTS and Coqui XTTS-v2 are optional and loaded lazily, so the
app starts even when their packages are not installed. OpenAI is never required.
"""
from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

import numpy as np

from app.utils import audio_utils


class TTSError(Exception):
    pass


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    language: str  # "en", "hi", "mr"
    gender: str  # "female" | "male"
    engine: str

    def to_dict(self) -> dict:
        return asdict(self)


class TTSProvider(ABC):
    name: str = ""
    label: str = ""

    @abstractmethod
    def is_available(self) -> tuple[bool, str]: ...

    @abstractmethod
    def voices(self) -> list[Voice]: ...

    @abstractmethod
    def synthesize(self, text: str, voice: str, language: str, speed: float = 1.0) -> tuple[np.ndarray, int]: ...


# ---------------------------------------------------------------- Kokoro
class KokoroProvider(TTSProvider):
    name, label = "kokoro", "Kokoro (local, recommended)"
    SAMPLE_RATE = 24000
    _VOICES = [
        ("af_heart", "Heart (US)", "en", "female"), ("af_bella", "Bella (US)", "en", "female"),
        ("af_nicole", "Nicole (US)", "en", "female"), ("af_sarah", "Sarah (US)", "en", "female"),
        ("am_adam", "Adam (US)", "en", "male"), ("am_michael", "Michael (US)", "en", "male"),
        ("bf_emma", "Emma (UK)", "en", "female"), ("bf_isabella", "Isabella (UK)", "en", "female"),
        ("bm_george", "George (UK)", "en", "male"), ("bm_lewis", "Lewis (UK)", "en", "male"),
        ("hf_alpha", "Alpha (Hindi)", "hi", "female"), ("hf_beta", "Beta (Hindi)", "hi", "female"),
        ("hm_omega", "Omega (Hindi)", "hi", "male"), ("hm_psi", "Psi (Hindi)", "hi", "male"),
    ]

    def __init__(self):
        self._pipelines: dict[str, object] = {}
        self._lock = threading.Lock()

    def is_available(self):
        try:
            import kokoro  # noqa: F401

            return True, ""
        except Exception as exc:
            return False, f"kokoro is not installed ({exc}). Run: pip install -r requirements-tts.txt"

    def voices(self):
        return [Voice(i, n, lang, g, self.name) for i, n, lang, g in self._VOICES]

    def _pipeline(self, lang_code: str):
        if lang_code not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        return self._pipelines[lang_code]

    def synthesize(self, text, voice, language, speed=1.0):
        ok, reason = self.is_available()
        if not ok:
            raise TTSError(reason)
        lang_code = voice[0]  # Kokoro voice ids start with their language code (a, b, h, ...)
        with self._lock:  # one inference at a time per process
            try:
                pipe = self._pipeline(lang_code)
                parts = []
                for _gs, _ps, audio in pipe(text, voice=voice, speed=speed):
                    if audio is None:
                        continue
                    arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
                    parts.append(arr.astype(np.float32).reshape(-1))
            except Exception as exc:
                raise TTSError(f"Kokoro failed: {exc}") from exc
        if not parts:
            raise TTSError("Kokoro returned no audio")
        return np.concatenate(parts), self.SAMPLE_RATE


# ---------------------------------------------------------------- Edge TTS
class EdgeTTSProvider(TTSProvider):
    name, label = "edge", "Edge TTS (online, optional)"
    _VOICES = [
        ("en-US-AriaNeural", "Aria (US)", "en", "female"), ("en-US-GuyNeural", "Guy (US)", "en", "male"),
        ("en-GB-SoniaNeural", "Sonia (UK)", "en", "female"), ("en-GB-RyanNeural", "Ryan (UK)", "en", "male"),
        ("en-IN-NeerjaNeural", "Neerja (India)", "en", "female"), ("en-IN-PrabhatNeural", "Prabhat (India)", "en", "male"),
        ("hi-IN-SwaraNeural", "Swara (Hindi)", "hi", "female"), ("hi-IN-MadhurNeural", "Madhur (Hindi)", "hi", "male"),
        ("mr-IN-AarohiNeural", "Aarohi (Marathi)", "mr", "female"), ("mr-IN-ManoharNeural", "Manohar (Marathi)", "mr", "male"),
    ]
    SAMPLE_RATE = 24000

    def is_available(self):
        try:
            import edge_tts  # noqa: F401
        except Exception as exc:
            return False, f"edge-tts is not installed ({exc})"
        if not audio_utils.ffmpeg_available():
            return False, "ffmpeg is required to decode Edge TTS audio"
        return True, ""

    def voices(self):
        return [Voice(i, n, lang, g, self.name) for i, n, lang, g in self._VOICES]

    async def _fetch(self, text: str, voice: str, speed: float) -> bytes:
        import edge_tts

        pct = int(round((speed - 1.0) * 100))
        comm = edge_tts.Communicate(text, voice, rate=f"{pct:+d}%")
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    def synthesize(self, text, voice, language, speed=1.0):
        ok, reason = self.is_available()
        if not ok:
            raise TTSError(reason)
        try:
            data = asyncio.run(self._fetch(text, voice, speed))
            if not data:
                raise TTSError("Edge TTS returned no audio")
            return audio_utils.decode_to_float32(data, self.SAMPLE_RATE), self.SAMPLE_RATE
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"Edge TTS failed: {exc}") from exc


# ---------------------------------------------------------------- Coqui XTTS-v2
class XTTSProvider(TTSProvider):
    name, label = "xtts", "Coqui XTTS-v2 (advanced, optional)"
    SAMPLE_RATE = 24000
    _VOICES = [
        ("Ana Florence", "Ana Florence", "en", "female"), ("Claribel Dervla", "Claribel Dervla", "en", "female"),
        ("Andrew Chipper", "Andrew Chipper", "en", "male"), ("Damien Black", "Damien Black", "en", "male"),
        ("Ana Florence", "Ana Florence (Hindi)", "hi", "female"),
    ]

    def __init__(self):
        self._tts = None
        self._lock = threading.Lock()

    def is_available(self):
        try:
            from TTS.api import TTS  # noqa: F401

            return True, ""
        except Exception as exc:
            return False, f"coqui-tts is not installed ({exc}). Uncomment it in requirements-tts.txt"

    def voices(self):
        return [Voice(i, n, lang, g, self.name) for i, n, lang, g in self._VOICES]

    def synthesize(self, text, voice, language, speed=1.0):
        ok, reason = self.is_available()
        if not ok:
            raise TTSError(reason)
        with self._lock:
            try:
                if self._tts is None:
                    from TTS.api import TTS

                    self._tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
                wav = self._tts.tts(text=text, speaker=voice, language=language, speed=speed)
            except Exception as exc:
                raise TTSError(f"XTTS failed: {exc}") from exc
        return np.asarray(wav, dtype=np.float32), self.SAMPLE_RATE


# ---------------------------------------------------------------- registry
_providers: dict[str, TTSProvider] = {}


def _ensure_registry() -> None:
    if not _providers:
        for p in (KokoroProvider(), EdgeTTSProvider(), XTTSProvider()):
            _providers[p.name] = p


def register_provider(provider: TTSProvider) -> None:
    """Add or replace a provider (used by tests and for plugging in custom engines)."""
    _ensure_registry()
    _providers[provider.name] = provider


def get_provider(name: str) -> TTSProvider:
    _ensure_registry()
    if name not in _providers:
        raise TTSError(f"Unknown TTS engine '{name}'")
    return _providers[name]


def list_engines() -> list[dict]:
    _ensure_registry()
    out = []
    for p in _providers.values():
        ok, reason = p.is_available()
        out.append(
            {"engine": p.name, "label": p.label, "available": ok, "reason": reason or None,
             "voices": [v.to_dict() for v in p.voices()]}
        )
    return out


def resolve_voice(engine: str, voice: str, language: str) -> Voice:
    provider = get_provider(engine)
    for v in provider.voices():
        if v.id == voice and v.language == language:
            return v
    raise TTSError(f"Voice '{voice}' is not available for language '{language}' on engine '{engine}'")
