"""Local PDF toolkit. Binds to 127.0.0.1 only; files are processed in memory and never stored."""

from __future__ import annotations

import io
import json
import sys
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import pdf_tools
from pdf_tools import PageRef, PdfToolError

# When frozen with PyInstaller, bundled data lives under sys._MEIPASS.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
STATIC_DIR = BASE_DIR / "static"
APP_ID = "pdf-local"

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB per request


def _files() -> list[bytes]:
    files = request.files.getlist("files")
    if not files:
        raise PdfToolError("No se recibió ningún archivo.")
    return [f.read() for f in files]


def _passwords(count: int) -> list[str | None]:
    raw = request.form.get("passwords")
    values = json.loads(raw) if raw else []
    return [(values[i] if i < len(values) else None) or None for i in range(count)]


def _pdf_response(payload: bytes, name: str):
    return send_file(io.BytesIO(payload), mimetype="application/pdf", as_attachment=True, download_name=name)


@app.errorhandler(PdfToolError)
def handle_tool_error(exc: PdfToolError):
    return jsonify(error=str(exc), code=exc.code), 400


@app.errorhandler(413)
def handle_too_large(_exc):
    return jsonify(error="Los archivos superan el límite de 500 MB."), 413


@app.after_request
def no_cache(response):
    # Sensitive documents: do not let the browser cache results.
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:name>")
def static_files(name: str):
    return send_from_directory(STATIC_DIR, name)


@app.get("/api/health")
def api_health():
    return jsonify(app=APP_ID)


@app.post("/api/shutdown")
def api_shutdown():
    # Requiring a custom header forces a CORS preflight, so other websites can't close the app.
    if request.headers.get("X-PDF-Local") != "1":
        abort(403)
    hook = app.config.get("SHUTDOWN_HOOK")
    if hook:
        hook()
    return jsonify(ok=True)


@app.post("/api/thumbnails")
def api_thumbnails():
    data = _files()[0]
    limit = request.form.get("limit", type=int)
    pages = pdf_tools.thumbnails(data, request.form.get("password") or None, limit=limit)
    return jsonify(pages=pages, count=pdf_tools.page_count(data, request.form.get("password") or None))


@app.post("/api/merge")
def api_merge():
    files = _files()
    return _pdf_response(pdf_tools.merge(files, _passwords(len(files))), "unido.pdf")


@app.post("/api/split")
def api_split():
    data = _files()[0]
    payload, kind = pdf_tools.split(
        data,
        mode=request.form.get("mode", "ranges"),
        ranges=request.form.get("ranges", ""),
        password=request.form.get("password") or None,
    )
    if kind == "zip":
        return send_file(io.BytesIO(payload), mimetype="application/zip", as_attachment=True, download_name="dividido.zip")
    return _pdf_response(payload, "dividido.pdf")


@app.post("/api/unlock")
def api_unlock():
    data = _files()[0]
    return _pdf_response(pdf_tools.unlock(data, request.form.get("password", "")), "desbloqueado.pdf")


@app.post("/api/protect")
def api_protect():
    data = _files()[0]
    payload = pdf_tools.protect(
        data,
        password=request.form.get("new_password", ""),
        current_password=request.form.get("password") or None,
    )
    return _pdf_response(payload, "protegido.pdf")


@app.post("/api/organize")
def api_organize():
    files = _files()
    try:
        pages = [PageRef(**item) for item in json.loads(request.form.get("pages", "[]"))]
    except (TypeError, ValueError) as exc:
        raise PdfToolError("Lista de páginas inválida.") from exc
    return _pdf_response(pdf_tools.organize(files, pages, _passwords(len(files))), "ordenado.pdf")


@app.post("/api/markdown")
def api_markdown():
    uploads = request.files.getlist("files")
    if not uploads:
        raise PdfToolError("No se recibió ningún archivo.")
    passwords = _passwords(len(uploads))
    advanced_layout = request.form.get("advanced_layout") == "true"
    results = []
    for upload, password in zip(uploads, passwords):
        result = pdf_tools.to_markdown(upload.read(), upload.filename or "documento.pdf", password, advanced_layout)
        results.append({
            "name": upload.filename,
            "markdown": result.markdown,
            "pages": result.pages,
            "empty_pages": result.empty_pages,
        })
    return jsonify(files=results)


if __name__ == "__main__":
    import os
    import threading

    host, port = "127.0.0.1", 5000
    app.config["SHUTDOWN_HOOK"] = lambda: threading.Timer(0.3, os._exit, [0]).start()
    webbrowser.open(f"http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
