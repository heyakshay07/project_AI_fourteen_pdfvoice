import pytest

from app.api.routes.pdf import sanitize_filename
from app.core.config import settings
from tests import pdf_factory as F
from tests.conftest import make_user, upload


def test_upload_valid_pdf_returns_metadata(client, auth):
    r = upload(client, auth, F.small_pdf(3), "My Report.pdf")
    assert r.status_code == 201
    body = r.json()
    assert body["total_pages"] == 3 and body["filename"] == "My Report.pdf"
    assert body["processing_status"] == "uploaded" and body["file_size"] > 0
    assert "file_path" not in body  # private paths are never exposed


def test_upload_requires_auth(client):
    assert client.post("/api/v1/pdf/upload", files={"file": ("a.pdf", F.small_pdf(1), "application/pdf")}).status_code == 401


def test_rejects_wrong_extension(client, auth):
    r = upload(client, auth, F.small_pdf(1), "notes.txt")
    assert r.status_code == 415 and r.json()["error"]["code"] == "invalid_file_type"


def test_rejects_non_pdf_content_with_pdf_extension(client, auth):
    r = upload(client, auth, b"MZ\x90\x00 this is an executable", "evil.pdf")
    assert r.status_code == 415


def test_rejects_empty_file(client, auth):
    assert upload(client, auth, b"", "empty.pdf").status_code == 422


def test_rejects_corrupted_pdf(client, auth):
    r = upload(client, auth, F.CORRUPTED, "broken.pdf")
    assert r.status_code == 422 and r.json()["error"]["code"] in {"corrupted"}


def test_rejects_encrypted_pdf(client, auth):
    r = upload(client, auth, F.encrypted_pdf(), "locked.pdf")
    assert r.status_code == 422 and r.json()["error"]["code"] == "encrypted"


def test_rejects_oversized_file(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    r = upload(client, auth, F.small_pdf(1))
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"


def test_rejects_too_many_pages(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "max_pages", 2)
    r = upload(client, auth, F.small_pdf(3))
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_many_pages"


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd.pdf", "passwd.pdf"),
    ("C:\\Users\\me\\report.pdf", "report.pdf"),
    ("na<>me?.pdf", "na__me_.pdf"),
    ("noextension", "noextension.pdf"),
    ("", "document.pdf"),
])
def test_filename_sanitized(raw, expected):
    assert sanitize_filename(raw) == expected


def test_documents_are_private_per_user(client):
    a, b = make_user(client), make_user(client)
    doc_id = upload(client, a, F.small_pdf(1)).json()["id"]
    assert client.get(f"/api/v1/pdf/{doc_id}", headers=a).status_code == 200
    for path in (f"/api/v1/pdf/{doc_id}", f"/api/v1/pdf/{doc_id}/file", f"/api/v1/pdf/{doc_id}/text", f"/api/v1/pdf/{doc_id}/status"):
        assert client.get(path, headers=b).status_code == 404
    assert client.delete(f"/api/v1/pdf/{doc_id}", headers=b).status_code == 404
    assert client.post(f"/api/v1/pdf/{doc_id}/process", headers=b).status_code == 404


def test_delete_removes_document_and_files(client, auth):
    doc_id = upload(client, auth, F.small_pdf(1)).json()["id"]
    assert client.delete(f"/api/v1/pdf/{doc_id}", headers=auth).status_code == 204
    assert client.get(f"/api/v1/pdf/{doc_id}", headers=auth).status_code == 404
