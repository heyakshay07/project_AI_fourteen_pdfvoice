from tests import pdf_factory as F
from tests.conftest import make_user, upload_and_process


def _ready(client, auth, pages=3):
    return upload_and_process(client, auth, F.small_pdf(pages))["id"]


def _n_sentences(client, auth, doc_id, page):
    return len(client.get(f"/api/v1/pdf/{doc_id}/text?page={page}", headers=auth).json()["pages"][0]["sentences"])


def test_start_defaults_to_beginning_then_resumes_saved_position(client, auth):
    d = _ready(client, auth)
    s = client.post("/api/v1/playback/start", headers=auth, json={"document_id": d}).json()
    assert (s["page"], s["sentence"], s["state"]) == (1, 0, "playing") and s["segment_id"]
    client.post("/api/v1/playback/pause", headers=auth, json={"document_id": d, "page": 2, "sentence": 3})
    again = client.post("/api/v1/playback/start", headers=auth, json={"document_id": d}).json()
    assert (again["page"], again["sentence"]) == (2, 3)  # continues where it stopped


def test_pause_resume_stop_states(client, auth):
    d = _ready(client, auth)
    body = {"document_id": d, "page": 1, "sentence": 2, "position_seconds": 3.4}
    assert client.post("/api/v1/playback/pause", headers=auth, json=body).json()["state"] == "paused"
    assert client.post("/api/v1/playback/resume", headers=auth, json=body).json()["state"] == "playing"
    stopped = client.post("/api/v1/playback/stop", headers=auth, json=body).json()
    assert stopped["state"] == "stopped" and stopped["sentence"] == 2


def test_seek_explicit_and_relative(client, auth):
    d = _ready(client, auth)
    n1 = _n_sentences(client, auth, d, 1)
    client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "page": 1, "sentence": 1})
    nxt = client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "direction": "next_sentence"}).json()
    assert (nxt["page"], nxt["sentence"]) == (1, 2)
    prv = client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "direction": "prev_sentence"}).json()
    assert prv["sentence"] == 1
    client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "page": 1, "sentence": n1 - 1})
    wrap = client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "direction": "next_sentence"}).json()
    assert (wrap["page"], wrap["sentence"]) == (2, 0)  # crosses the page boundary
    back = client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "direction": "prev_sentence"}).json()
    assert (back["page"], back["sentence"]) == (1, n1 - 1)
    assert client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "direction": "next_page"}).json()["page"] == 2
    assert client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "direction": "prev_page"}).json()["page"] == 1


def test_seek_clamps_out_of_range(client, auth):
    d = _ready(client, auth)
    s = client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d, "page": 99, "sentence": 999}).json()
    assert s["page"] == 3 and s["sentence"] == _n_sentences(client, auth, d, 3) - 1
    assert client.post("/api/v1/playback/seek", headers=auth, json={"document_id": d}).status_code == 422


def test_progress_percentage_grows_and_persists(client, auth):
    d = _ready(client, auth)
    pct = []
    for page in (1, 2, 3):
        pct.append(client.put(f"/api/v1/history/{d}/progress", headers=auth, json={"page": page, "sentence": 0}).json()["progress_percentage"])
    assert pct[0] == 0 and pct[0] < pct[1] < pct[2] < 100
    h = client.get(f"/api/v1/history/{d}", headers=auth).json()
    assert h["current_page"] == 3 and h["progress_percentage"] == pct[2]


def test_history_list_and_clear(client):
    a = make_user(client)
    d = _ready(client, a)
    other = _ready(client, a, 1)
    client.put(f"/api/v1/history/{d}/progress", headers=a, json={"page": 2, "sentence": 1})
    items = client.get("/api/v1/history", headers=a).json()
    assert {i["document_id"] for i in items} == {d, other}
    assert items[0]["document_id"] == d  # most recently read first
    assert client.delete(f"/api/v1/history/{d}", headers=a).status_code == 204
    assert client.get(f"/api/v1/history/{d}", headers=a).json()["current_page"] is None
    assert client.get(f"/api/v1/pdf/{d}", headers=a).status_code == 200  # document itself is kept


def test_history_isolated_between_users(client):
    a, b = make_user(client), make_user(client)
    d = _ready(client, a)
    assert client.get("/api/v1/history", headers=b).json() == []
    assert client.put(f"/api/v1/history/{d}/progress", headers=b, json={"page": 1, "sentence": 0}).status_code == 404
    assert client.post("/api/v1/playback/start", headers=b, json={"document_id": d}).status_code == 404


def test_playback_requires_processed_document(client, auth):
    from tests.conftest import upload
    d = upload(client, auth, F.small_pdf(1)).json()["id"]
    r = client.post("/api/v1/playback/start", headers=auth, json={"document_id": d})
    assert r.status_code == 409


def test_deleting_document_removes_progress(client, auth):
    d = _ready(client, auth, 1)
    client.put(f"/api/v1/history/{d}/progress", headers=auth, json={"page": 1, "sentence": 0})
    client.delete(f"/api/v1/pdf/{d}", headers=auth)
    assert client.get("/api/v1/history", headers=auth).json() == []
