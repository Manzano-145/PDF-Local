import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402


def make_pdf(widths: list[int], password: str | None = None) -> bytes:
    """Build a PDF whose page widths identify each page (e.g. [101, 102, 103])."""
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=200)
    if password:
        writer.encrypt(password, algorithm="AES-256")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def widths(data: bytes, password: str | None = None) -> list[int]:
    reader = PdfReader(io.BytesIO(data))
    if password:
        reader.decrypt(password)
    return [round(float(page.mediabox.width)) for page in reader.pages]


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def post(client, path, files, **form):
    data = {key: value for key, value in form.items()}
    data["files"] = [(io.BytesIO(content), f"f{i}.pdf") for i, content in enumerate(files)]
    return client.post(path, data=data, content_type="multipart/form-data")


def test_merge_keeps_requested_order(client):
    response = post(client, "/api/merge", [make_pdf([101, 102]), make_pdf([201])])
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert widths(response.data) == [101, 102, 201]


def test_merge_with_protected_file_uses_its_password(client):
    files = [make_pdf([101]), make_pdf([201], password="secret")]
    response = post(client, "/api/merge", files, passwords=json.dumps([None, "secret"]))
    assert response.status_code == 200
    assert widths(response.data) == [101, 201]


def test_merge_without_password_reports_password_required(client):
    response = post(client, "/api/merge", [make_pdf([101]), make_pdf([201], password="secret")])
    assert response.status_code == 400
    assert response.json["code"] == "password_required"


def test_split_ranges_returns_zip_with_one_pdf_per_range(client):
    response = post(client, "/api/split", [make_pdf([101, 102, 103, 104])], mode="ranges", ranges="1-2, 4")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    assert [widths(archive.read(name)) for name in archive.namelist()] == [[101, 102], [104]]


def test_split_extract_returns_single_pdf(client):
    response = post(client, "/api/split", [make_pdf([101, 102, 103, 104])], mode="extract", ranges="1, 3-4")
    assert response.mimetype == "application/pdf"
    assert widths(response.data) == [101, 103, 104]


def test_split_each_page(client):
    response = post(client, "/api/split", [make_pdf([101, 102, 103])], mode="each")
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    assert len(archive.namelist()) == 3


def test_split_out_of_range_is_rejected(client):
    response = post(client, "/api/split", [make_pdf([101, 102])], mode="ranges", ranges="2-5")
    assert response.status_code == 400
    assert "fuera de límites" in response.json["error"]


def test_unlock_removes_password(client):
    response = post(client, "/api/unlock", [make_pdf([101, 102], password="secret")], password="secret")
    assert response.status_code == 200
    reader = PdfReader(io.BytesIO(response.data))
    assert not reader.is_encrypted
    assert widths(response.data) == [101, 102]


def test_unlock_with_wrong_password(client):
    response = post(client, "/api/unlock", [make_pdf([101], password="secret")], password="nope")
    assert response.status_code == 400
    assert response.json["code"] == "wrong_password"


def test_protect_encrypts_with_new_password(client):
    response = post(client, "/api/protect", [make_pdf([101, 102])], new_password="s3cret")
    reader = PdfReader(io.BytesIO(response.data))
    assert reader.is_encrypted
    assert widths(response.data, password="s3cret") == [101, 102]


def test_organize_reorders_rotates_deletes_and_adds_blank(client):
    pages = [
        {"file": 0, "page": 2},
        {"file": 1, "page": 0, "rotate": 90},
        {"blank": True},
        {"file": 0, "page": 0},
    ]  # page 1 of file 0 is deleted
    response = post(client, "/api/organize", [make_pdf([101, 102, 103]), make_pdf([201])], pages=json.dumps(pages))
    assert response.status_code == 200
    reader = PdfReader(io.BytesIO(response.data))
    assert widths(response.data) == [103, 201, 201, 101]
    assert [page.rotation for page in reader.pages] == [0, 90, 0, 0]


def test_thumbnails_respects_limit_and_reports_count(client):
    response = post(client, "/api/thumbnails", [make_pdf([101, 102, 103])], limit="1")
    assert response.json["count"] == 3
    assert len(response.json["pages"]) == 1
    assert response.json["pages"][0].startswith("data:image/png;base64,")


def test_invalid_pdf_is_rejected(client):
    response = post(client, "/api/unlock", [b"not a pdf"], password="x")
    assert response.status_code == 400
