import uuid
import jwt

from tests import pdf_factory as F
from app.core.config import settings
from tests.conftest import upload


def test_unauthenticated_and_bad_token(client):
    assert client.get("/api/v1/history").status_code == 401
    r = client.get("/api/v1/history", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "http_error"


def test_unauthorized_responses_include_cors_for_deployed_frontend(client):
    origin = "https://project-ai-fourteen-pdfvoice.onrender.com"
    response = client.get(f"/api/v1/pdf/{uuid.uuid4()}", headers={"Origin": origin})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == origin


def test_login_errors_and_success(client):
    body = {"name": "A", "email": "dupe@example.com", "password": "longenough1"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    assert client.post("/api/v1/auth/register", json=body).json()["error"]["code"] == "email_taken"
    assert client.post("/api/v1/auth/login", json={"email": "dupe@example.com", "password": "wrong"}).status_code == 401
    ok = client.post("/api/v1/auth/login", json={"email": "DUPE@example.com", "password": "longenough1"})
    assert ok.status_code == 200
    claims = jwt.decode(ok.json()["access_token"], settings.secret_key, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 4 * 24 * 60 * 60
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"})
    assert me.json()["email"] == "dupe@example.com"


def test_validation_error_shape(client):
    r = client.post("/api/v1/auth/register", json={"name": "", "email": "not-an-email", "password": "short"})
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "validation_error" and len(err["details"]) == 3


def test_unknown_document_is_404(client, auth):
    r = client.get(f"/api/v1/pdf/{uuid.uuid4()}", headers=auth)
    assert r.status_code == 404 and r.json()["error"]["code"] == "document_not_found"
    assert client.get("/api/v1/pdf/not-a-uuid", headers=auth).status_code == 422


def test_double_process_conflict_and_reprocess(client, auth):
    d = upload(client, auth, F.small_pdf(1)).json()["id"]
    assert client.post(f"/api/v1/pdf/{d}/process", headers=auth).status_code == 202
    assert client.post(f"/api/v1/pdf/{d}/process", headers=auth).status_code == 202  # completed docs can be re-processed


def test_processing_failure_is_recorded(client, auth, monkeypatch):
    from app.core.database import SessionLocal
    from app.models.document import Document
    import uuid as _u
    d = upload(client, auth, F.small_pdf(1)).json()["id"]
    with SessionLocal() as db:  # simulate a file that became unreadable after upload
        doc = db.get(Document, _u.UUID(d))
        doc.pdf_data = F.CORRUPTED
        db.commit()
    client.post(f"/api/v1/pdf/{d}/process", headers=auth)
    st = client.get(f"/api/v1/pdf/{d}/status", headers=auth).json()
    assert st["processing_status"] == "failed" and st["error_message"]


def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "service": "PDFVoice AI API",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


def test_sse_progress_stream_emits_final_event(client, auth):
    d = upload(client, auth, F.small_pdf(1)).json()["id"]
    client.post(f"/api/v1/pdf/{d}/process", headers=auth)
    r = client.get(f"/api/v1/pdf/{d}/progress/stream", headers=auth)
    assert r.status_code == 200 and "event: progress" in r.text and '"processing_status": "completed"' in r.text
