# PDF Local

Local PDF toolkit inspired by iLovePDF: merge, split, unlock, protect, organize PDFs and convert
them to Markdown, without uploading anything to third parties.

## Privacy

- The server listens on `127.0.0.1` only (not reachable from your network).
- Files are processed in memory and never written to disk.
- The UI loads no external resources (no CDN, fonts or analytics).
- Responses are sent with `Cache-Control: no-store`.

## Run

Double-click `iniciar.bat`, or:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

The browser opens at http://127.0.0.1:5000.

## Tools

| Tool | Endpoint | Notes |
|------|----------|-------|
| Merge | `POST /api/merge` | `files` in order, optional `passwords` (JSON list) |
| Split | `POST /api/split` | `mode`: `ranges` (zip, one PDF per range), `extract` (one PDF), `each` (zip) |
| Unlock | `POST /api/unlock` | `password` |
| Protect | `POST /api/protect` | `new_password` (AES-256), `password` if already protected |
| Organize | `POST /api/organize` | `pages` JSON: `{file, page, rotate}` or `{blank: true}` |
| PDF to Markdown | `POST /api/markdown` | Full text with headings, lists and tables as Markdown, with `<!-- Página N / M -->` markers. Returns JSON. |
| Thumbnails | `POST /api/thumbnails` | optional `limit`, `password` |

## PDF to Markdown

Built for feeding documents to AI chats: the output is the **complete** content (not a summary)
in a lightweight `.md`, usually a fraction of the PDF size. Tables become Markdown tables and
every page is marked so the AI can cite page numbers.

The UI option *Análisis de diseño avanzado* (`advanced_layout=true`) enables PyMuPDF's layout
model for multi-column pages and borderless tables; it is much slower.

Limitation: scanned PDFs (pages that are images) have no extractable text. Those pages are
flagged in the UI and in the `.md`; OCR is not included.

## Tests

```bash
.venv\Scripts\python -m pytest
```
