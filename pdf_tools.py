"""Pure PDF operations. Everything works on bytes in memory; nothing touches disk."""

from __future__ import annotations

import base64
import io
import re
import threading
import zipfile
from dataclasses import dataclass

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


class PdfToolError(ValueError):
    """User-facing error (bad input, wrong password, invalid range...)."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _open(data: bytes, password: str | None = None) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise PdfToolError("El archivo no es un PDF válido.") from exc
    if reader.is_encrypted:
        if not password:
            raise PdfToolError("El PDF está protegido: ingresá la contraseña.", code="password_required")
        if not reader.decrypt(password):
            raise PdfToolError("Contraseña incorrecta.", code="wrong_password")
    return reader


def _to_bytes(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def parse_ranges(spec: str, page_count: int) -> list[list[int]]:
    """Parse '1-3, 5, 8-' into zero-based page groups, one group per range."""
    groups: list[list[int]] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        match = re.fullmatch(r"(\d*)\s*-\s*(\d*)|(\d+)", part)
        if not match:
            raise PdfToolError(f"Rango inválido: '{part}'.")
        if match.group(3):
            start = end = int(match.group(3))
        else:
            start = int(match.group(1) or 1)
            end = int(match.group(2) or page_count)
        if start < 1 or end > page_count or start > end:
            raise PdfToolError(f"Rango fuera de límites: '{part}' (el PDF tiene {page_count} páginas).")
        groups.append(list(range(start - 1, end)))
    if not groups:
        raise PdfToolError("Indicá al menos un rango de páginas.")
    return groups


def merge(files: list[bytes], passwords: list[str | None] | None = None) -> bytes:
    if len(files) < 2:
        raise PdfToolError("Seleccioná al menos dos PDFs para unir.")
    passwords = passwords or [None] * len(files)
    writer = PdfWriter()
    for data, password in zip(files, passwords):
        writer.append(_open(data, password))
    return _to_bytes(writer)


def split(data: bytes, mode: str, ranges: str = "", password: str | None = None) -> tuple[bytes, str]:
    """Return (payload, kind) where kind is 'pdf' or 'zip'.

    modes:
      - 'ranges':  one PDF per range, zipped (single range -> single PDF)
      - 'extract': all pages from the ranges merged into one PDF
      - 'each':    every page as its own PDF, zipped
    """
    reader = _open(data, password)
    total = len(reader.pages)
    if mode == "each":
        groups = [[i] for i in range(total)]
    elif mode in ("ranges", "extract"):
        groups = parse_ranges(ranges, total)
    else:
        raise PdfToolError(f"Modo de división desconocido: '{mode}'.")

    if mode == "extract":
        groups = [[page for group in groups for page in group]]

    outputs = []
    for group in groups:
        writer = PdfWriter()
        for index in group:
            writer.add_page(reader.pages[index])
        name = f"paginas_{group[0] + 1}" + (f"-{group[-1] + 1}" if len(group) > 1 else "") + ".pdf"
        outputs.append((name, _to_bytes(writer)))

    if len(outputs) == 1:
        return outputs[0][1], "pdf"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in outputs:
            archive.writestr(name, payload)
    return buffer.getvalue(), "zip"


def unlock(data: bytes, password: str) -> bytes:
    reader = _open(data, password)
    writer = PdfWriter(clone_from=reader)
    return _to_bytes(writer)


def protect(data: bytes, password: str, current_password: str | None = None) -> bytes:
    if not password:
        raise PdfToolError("Ingresá una contraseña para proteger el PDF.")
    reader = _open(data, current_password)
    writer = PdfWriter(clone_from=reader)
    writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
    return _to_bytes(writer)


@dataclass
class PageRef:
    """One page in the organized output: a page of a source file, or a blank page."""

    file: int | None = None
    page: int | None = None
    rotate: int = 0
    blank: bool = False


def organize(files: list[bytes], pages: list[PageRef], passwords: list[str | None] | None = None) -> bytes:
    if not pages:
        raise PdfToolError("El documento resultante no tiene páginas.")
    passwords = passwords or [None] * len(files)
    readers = [_open(data, pw) for data, pw in zip(files, passwords)]
    writer = PdfWriter()
    last_size = (612, 792)  # US Letter, used for blank pages before any real page
    for ref in pages:
        if ref.blank:
            writer.add_blank_page(width=last_size[0], height=last_size[1])
            continue
        if ref.file is None or not 0 <= ref.file < len(readers):
            raise PdfToolError("Referencia de archivo inválida.")
        reader = readers[ref.file]
        if ref.page is None or not 0 <= ref.page < len(reader.pages):
            raise PdfToolError("Referencia de página inválida.")
        page = writer.add_page(reader.pages[ref.page])
        if ref.rotate % 360:
            page.rotate(ref.rotate % 360)
        last_size = (float(page.mediabox.width), float(page.mediabox.height))
    return _to_bytes(writer)


def thumbnails(data: bytes, password: str | None = None, width: int = 180, limit: int | None = None) -> list[str]:
    """Render pages (all, or the first `limit`) as base64 PNG data URLs."""
    _open(data, password)  # validates format and password with friendly errors
    document = pdfium.PdfDocument(data, password=password or None)
    try:
        result = []
        count = len(document) if limit is None else min(limit, len(document))
        for index in range(count):
            page = document[index]
            scale = width / page.get_width()
            image = page.render(scale=scale).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            result.append("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode())
            page.close()
        return result
    finally:
        document.close()


def page_count(data: bytes, password: str | None = None) -> int:
    return len(_open(data, password).pages)


@dataclass
class MarkdownResult:
    markdown: str
    pages: int
    empty_pages: list[int]  # 1-based pages with no extractable text (likely scanned images)


# PyMuPDF is not thread-safe and Flask serves requests on several threads.
_mupdf_lock = threading.Lock()


def _clean_markdown(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def to_markdown(data: bytes, name: str, password: str | None = None, advanced_layout: bool = False) -> MarkdownResult:
    """Convert a PDF to Markdown, keeping headings, lists and tables, with page markers.

    The full content is preserved (no summarization) so it can be pasted into an AI chat.
    `advanced_layout` uses PyMuPDF's layout model: better for multi-column pages and
    borderless tables, but roughly 50x slower.
    """
    page_total = len(_open(data, password).pages)  # friendly errors for bad files/passwords

    import pymupdf  # heavy imports: only loaded when this tool is used
    import pymupdf4llm

    with _mupdf_lock:  # use_layout() is global state, so it must be set under the lock too
        pymupdf4llm.use_layout(advanced_layout)
        document = pymupdf.open(stream=data, filetype="pdf")
        try:
            if document.needs_pass:
                document.authenticate(password or "")
            chunks = pymupdf4llm.to_markdown(document, page_chunks=True, show_progress=False)
        finally:
            document.close()

    sections = [f"# {name}", f"_{page_total} páginas_"]
    empty_pages = []
    for number, chunk in enumerate(chunks, start=1):
        body = _clean_markdown(chunk["text"])
        if not body:
            empty_pages.append(number)
            body = "_(Página sin texto extraíble; posiblemente es una imagen escaneada.)_"
        sections.append(f"<!-- Página {number} / {page_total} -->\n\n{body}")
    return MarkdownResult("\n\n".join(sections) + "\n", page_total, empty_pages)
