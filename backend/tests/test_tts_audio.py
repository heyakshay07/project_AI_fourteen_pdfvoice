import io

import soundfile as sf

from app.services import tts_service
from tests import pdf_factory as F
from tests.conftest import upload_and_process, use_tone_voice


def _first_segment(client, auth, doc_id):
    return client.get(f"/api/v1/voice/{doc_id}/segments", headers=auth).json()[0]


def test_available_voices_lists_engines(client):
    body = client.get("/api/v1/voice/available-voices").json()
    engines = {e["engine"]: e for e in body["engines"]}
    assert {"kokoro", "edge", "xtts"} <= set(engines)
    langs = {v["language"] for e in engines.values() for v in e["voices"]}
    assert {"en", "hi", "mr"} <= langs


def test_voice_settings_roundtrip_and_validation(client, auth, tone):
    use_tone_voice(client, auth)
    assert client.get("/api/v1/voice/settings", headers=auth).json()["voice_name"] == "tone_f"
    bad = client.put("/api/v1/voice/settings", headers=auth,
                     json={"voice_engine": "tone", "voice_name": "nope", "language": "en", "speaking_speed": 1})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_voice"


def test_segments_audio_and_timings(client, auth, tone):
    use_tone_voice(client, auth)
    doc = upload_and_process(client, auth, F.small_pdf(1))
    seg = _first_segment(client, auth, doc["id"])
    assert seg["generation_status"] == "pending"
    detail = client.get(f"/api/v1/voice/{doc['id']}/segments/{seg['id']}", headers=auth).json()
    t = detail["timings"]
    assert detail["generation_status"] == "ready" and detail["duration"] > 0
    assert [x["sentence"] for x in t] == list(range(seg["sentence_start"], seg["sentence_end"] + 1))
    assert t[0]["start"] == 0 and all(a["end"] == b["start"] for a, b in zip(t, t[1:]))
    assert abs(t[-1]["end"] - detail["duration"]) < 0.01
    audio = client.get(f"/api/v1/voice/{doc['id']}/audio/{seg['id']}", headers=auth)
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
    data, sr = sf.read(io.BytesIO(audio.content))
    assert abs(len(data) / sr - detail["duration"]) < 0.3  # mp3 padding tolerance


def test_every_sentence_is_spoken_in_order(client, auth, tone):
    use_tone_voice(client, auth)
    doc = upload_and_process(client, auth, F.small_pdf(1))
    for seg in client.get(f"/api/v1/voice/{doc['id']}/segments", headers=auth).json():
        client.get(f"/api/v1/voice/{doc['id']}/segments/{seg['id']}", headers=auth)
    page = client.get(f"/api/v1/pdf/{doc['id']}/text?page=1", headers=auth).json()["pages"][0]
    assert tone.calls == [s["text"] for s in page["sentences"]]  # nothing skipped, nothing added


def test_audio_is_cached_not_regenerated(client, auth, tone):
    use_tone_voice(client, auth)
    doc = upload_and_process(client, auth, F.small_pdf(1))
    seg = _first_segment(client, auth, doc["id"])
    url = f"/api/v1/voice/{doc['id']}/segments/{seg['id']}"
    client.get(url, headers=auth)
    calls = len(tone.calls)
    client.get(url, headers=auth)
    client.get(f"/api/v1/voice/{doc['id']}/audio/{seg['id']}", headers=auth)
    assert len(tone.calls) == calls


def test_switching_voice_generates_then_reuses_cache(client, auth, tone):
    use_tone_voice(client, auth)
    doc = upload_and_process(client, auth, F.small_pdf(1))
    seg = _first_segment(client, auth, doc["id"])
    base = f"/api/v1/voice/{doc['id']}/segments/{seg['id']}"
    client.get(base, headers=auth)
    n1 = len(tone.calls)
    client.get(base + "?voice=tone_m", headers=auth)
    n2 = len(tone.calls)
    assert n2 > n1
    client.get(base + "?voice=tone_f", headers=auth)
    assert len(tone.calls) == n2  # first voice served from cache


def test_failed_generation_is_retried_without_duplicates(client, auth, tone):
    use_tone_voice(client, auth)
    doc = upload_and_process(client, auth, F.small_pdf(1))
    seg = _first_segment(client, auth, doc["id"])
    tone.fail_next = 2
    r = client.get(f"/api/v1/voice/{doc['id']}/segments/{seg['id']}", headers=auth)
    assert r.status_code == 200
    n_sentences = seg["sentence_end"] - seg["sentence_start"] + 1
    assert len(tone.calls) == n_sentences


def test_permanent_failure_returns_structured_error(client, auth, tone):
    use_tone_voice(client, auth)
    doc = upload_and_process(client, auth, F.small_pdf(1))
    seg = _first_segment(client, auth, doc["id"])
    tone.fail_next = 100
    r = client.get(f"/api/v1/voice/{doc['id']}/segments/{seg['id']}", headers=auth)
    assert r.status_code == 502 and r.json()["error"]["code"] == "tts_failed"
    tone.fail_next = 0
    assert client.get(f"/api/v1/voice/{doc['id']}/segments/{seg['id']}", headers=auth).status_code == 200  # recovers


def test_unavailable_engine_gives_503(client, auth):
    r = client.put("/api/v1/voice/settings", headers=auth,
                   json={"voice_engine": "xtts", "voice_name": "Ana Florence", "language": "en", "speaking_speed": 1})
    assert r.status_code == 200
    doc = upload_and_process(client, auth, F.small_pdf(1))
    seg = _first_segment(client, auth, doc["id"])
    ok, _ = tts_service.get_provider("xtts").is_available()
    if not ok:
        assert client.get(f"/api/v1/voice/{doc['id']}/segments/{seg['id']}", headers=auth).status_code == 503


def test_generate_endpoint_pregenerates_in_background(client, auth, tone):
    use_tone_voice(client, auth)
    doc = upload_and_process(client, auth, F.small_pdf(2))
    r = client.post("/api/v1/voice/generate", headers=auth, json={"document_id": doc["id"]})
    assert r.status_code == 202
    segs = client.get(f"/api/v1/voice/{doc['id']}/segments", headers=auth).json()
    assert segs and all(s["generation_status"] == "ready" for s in segs)
    prog = client.get(f"/api/v1/pdf/{doc['id']}/progress", headers=auth).json()
    assert prog["chunks_audio_ready"] == prog["chunks_total"] > 0


def test_audio_requires_processed_document(client, auth, tone):
    use_tone_voice(client, auth)
    from tests.conftest import upload
    doc_id = upload(client, auth, F.small_pdf(1)).json()["id"]
    r = client.post("/api/v1/voice/generate", headers=auth, json={"document_id": doc_id})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_processed"
