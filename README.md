# PDF Local

Local PDF toolkit inspired by iLovePDF: merge, split, unlock, protect and organize PDFs
without uploading anything to third parties.

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
| Thumbnails | `POST /api/thumbnails` | optional `limit`, `password` |

## Tests

```bash
.venv\Scripts\python -m pytest
```
