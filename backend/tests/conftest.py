import os
import shutil
import tempfile
import uuid

_TMP = tempfile.mkdtemp(prefix="pdfvoice_test_")
os.environ.update(
    DATABASE_URL=f"sqlite:///{_TMP}/test.db", STORAGE_DIR=f"{_TMP}/storage", TASK_BACKEND="inline",
    SECRET_KEY="test-secret-key-that-is-long-enough-32b", AUDIO_FORMAT="mp3", OCR_LANGUAGES="eng",
    CORS_ORIGINS="http://localhost:5173,https://project-ai-fourteen-pdfvoice.onrender.com",
)

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import tts_service  # noqa: E402


class ToneProvider(tts_service.TTSProvider):
    """Test double: deterministic tone whose length scales with the text. Counts calls; can fail on demand."""

    name, label = "tone", "Tone (tests only)"

    def __init__(self):
        self.calls: list[str] = []
        self.fail_next = 0

    def is_available(self):
        return True, ""

    def voices(self):
        return [tts_service.Voice("tone_f", "Tone F", "en", "female", self.name),
                tts_service.Voice("tone_m", "Tone M", "en", "male", self.name)]

    def synthesize(self, text, voice, language, speed=1.0):
        if self.fail_next > 0:
            self.fail_next -= 1
            raise tts_service.TTSError("simulated engine failure")
        self.calls.append(text)
        sr = 24000
        seconds = max(0.2, len(text) * 0.04 / speed)
        t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
        return (0.2 * np.sin(2 * np.pi * (220 if voice == "tone_f" else 140) * t)).astype(np.float32), sr


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def tone():
    p = ToneProvider()
    tts_service.register_provider(p)
    return p


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def make_user(client: TestClient) -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/auth/register", json={"name": "Test User", "email": email, "password": "correct-horse-battery"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return make_user(client)


def upload(client, headers, data: bytes, name: str = "test.pdf"):
    return client.post("/api/v1/pdf/upload", headers=headers, files={"file": (name, data, "application/pdf")})


def upload_and_process(client, headers, data: bytes, name: str = "test.pdf") -> dict:
    r = upload(client, headers, data, name)
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    r = client.post(f"/api/v1/pdf/{doc_id}/process", headers=headers)
    assert r.status_code == 202, r.text
    status = client.get(f"/api/v1/pdf/{doc_id}/status", headers=headers).json()
    assert status["processing_status"] == "completed", status
    return client.get(f"/api/v1/pdf/{doc_id}", headers=headers).json()


def use_tone_voice(client, headers):
    r = client.put("/api/v1/voice/settings", headers=headers,
                   json={"voice_engine": "tone", "voice_name": "tone_f", "language": "en", "speaking_speed": 1.0})
    assert r.status_code == 200, r.text
