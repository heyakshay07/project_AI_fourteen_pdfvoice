import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(int(round(seconds * sample_rate)), dtype=np.float32)


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    sf.write(str(path), audio.astype(np.float32), sample_rate, subtype="PCM_16")


def encode_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "64k") -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)]
    subprocess.run(cmd, check=True, capture_output=True)


def decode_to_float32(data: bytes, sample_rate: int = 24000) -> np.ndarray:
    """Decode any ffmpeg-readable audio (e.g. mp3 from Edge TTS) to mono float32 PCM."""
    cmd = ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "pipe:1"]
    proc = subprocess.run(cmd, input=data, check=True, capture_output=True)
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()
