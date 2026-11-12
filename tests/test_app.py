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


def make_table_pdf(password: str | None = None) -> bytes:
    """Page 1: heading, paragraph and a ruled table. Page 2: blank (no text, like a scan)."""
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 60), "Reporte de inventario", fontsize=20)
    page.insert_text((50, 90), "Este documento lista el inventario actual.", fontsize=11)
    rows = [["Producto", "Cantidad"], ["Manzanas", "100"], ["Peras", "80"]]
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = pymupdf.Rect(50 + c * 120, 120 + r * 22, 170 + c * 120, 142 + r * 22)
            page.draw_rect(cell, color=(0, 0, 0), width=0.8)
            page.insert_text((cell.x0 + 5, cell.y1 - 7), value, fontsize=10)
    document.new_page()
    options = {}
    if password:
        options = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": password, "owner_pw": password}
    return document.tobytes(**options)


def test_markdown_keeps_tables_text_and_page_markers(client):
    response = post(client, "/api/markdown", [make_table_pdf()])
    assert response.status_code == 200
    result = response.json["files"][0]
    markdown = result["markdown"]
    assert result["pages"] == 2
    assert markdown.startswith("# f0.pdf")
    assert "Este documento lista el inventario actual." in markdown
    assert "|Producto|Cantidad|" in markdown.replace(" ", "")
    assert "|Manzanas|100|" in markdown.replace(" ", "")
    assert "<!-- Página 1 / 2 -->" in markdown
    assert "<!-- Página 2 / 2 -->" in markdown


def test_markdown_flags_pages_without_text(client):
    result = post(client, "/api/markdown", [make_table_pdf()]).json["files"][0]
    assert result["empty_pages"] == [2]
    assert "sin texto extraíble" in result["markdown"]


def test_markdown_handles_several_files_and_passwords(client):
    files = [make_table_pdf(), make_table_pdf(password="secret")]
    response = post(client, "/api/markdown", files, passwords=json.dumps([None, "secret"]))
    assert response.status_code == 200
    assert [f["name"] for f in response.json["files"]] == ["f0.pdf", "f1.pdf"]
    assert "Manzanas" in response.json["files"][1]["markdown"]


def test_markdown_protected_without_password(client):
    response = post(client, "/api/markdown", [make_table_pdf(password="secret")])
    assert response.status_code == 400
    assert response.json["code"] == "password_required"


def test_markdown_advanced_layout_keeps_table(client):
    response = post(client, "/api/markdown", [make_table_pdf()], advanced_layout="true")
    assert response.status_code == 200
    assert "|Manzanas|100|" in response.json["files"][0]["markdown"].replace(" ", "")


def test_health_identifies_the_app(client):
    response = client.get("/api/health")
    assert response.json == {"app": "pdf-local"}


def test_shutdown_calls_registered_hook(client):
    calls = []
    app.config["SHUTDOWN_HOOK"] = lambda: calls.append(True)
    try:
        response = client.post("/api/shutdown", headers={"X-PDF-Local": "1"})
    finally:
        app.config.pop("SHUTDOWN_HOOK")
    assert response.status_code == 200
    assert calls == [True]


def test_shutdown_requires_custom_header(client):
    # A custom header forces a CORS preflight, so other websites cannot close the app.
    calls = []
    app.config["SHUTDOWN_HOOK"] = lambda: calls.append(True)
    try:
        response = client.post("/api/shutdown")
    finally:
        app.config.pop("SHUTDOWN_HOOK")
    assert response.status_code == 403
    assert calls == []


SAMPLE_MD = """# Informe de Gestión

<!-- Página 1 / 2 -->

Texto con **negrita** y acentos: ñ á é í ó ú.

| Producto | Cantidad |
|---|---:|
| Manzanas | 100 |

1. Primero
2. Segundo:
   - Sub ítem A
   - Sub ítem B

- [x] Hecha
- [ ] Pendiente

![Logo de la empresa](https://example.com/logo.png)
"""


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def post_md(client, files=(), **form):
    data = dict(form)
    data["files"] = [(io.BytesIO(content.encode("utf-8")), name) for name, content in files]
    return client.post("/api/md-to-pdf", data=data, content_type="multipart/form-data")


def test_md_to_pdf_keeps_content_tables_and_lists(client):
    response = post_md(client, [("informe.md", SAMPLE_MD)])
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    text = pdf_text(response.data)
    for expected in ["Informe de Gestión", "negrita", "ñ á é í ó ú", "Producto", "Manzanas", "100",
                     "Primero", "Sub ítem A", "Hecha", "Pendiente"]:
        assert expected in text, expected
    assert "Página 1 / 2" not in text  # HTML comments are not printed


def test_md_to_pdf_never_fetches_images_and_keeps_alt_text(client):
    text = pdf_text(post_md(client, [("informe.md", SAMPLE_MD)]).data)
    assert "Logo de la empresa" in text


def test_md_to_pdf_adds_page_numbers_and_title(client):
    long_md = "# Largo\n\n" + "\n\n".join(f"Párrafo número {i}." for i in range(150))
    response = post_md(client, [("largo.md", long_md)])
    reader = PdfReader(io.BytesIO(response.data))
    total = len(reader.pages)
    assert total > 1
    assert f"1 / {total}" in reader.pages[0].extract_text()
    assert f"{total} / {total}" in reader.pages[-1].extract_text()
    assert reader.metadata.title == "Largo"


def test_md_to_pdf_from_pasted_text(client):
    response = post_md(client, text="# Pegado\n\nContenido pegado desde un chat.")
    assert response.status_code == 200
    assert "Contenido pegado desde un chat." in pdf_text(response.data)


def test_md_to_pdf_several_files_returns_zip(client):
    response = post_md(client, [("uno.md", "# Uno"), ("dos.md", "# Dos")])
    assert response.mimetype == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    assert archive.namelist() == ["uno.pdf", "dos.pdf"]
    assert "Dos" in pdf_text(archive.read("dos.pdf"))


def test_md_to_pdf_without_content_is_rejected(client):
    response = post_md(client, text="   ")
    assert response.status_code == 400
