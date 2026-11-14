# PDFVoice AI

Upload a PDF and have it read aloud, word for word, by a natural voice, with the current sentence highlighted.
Text is **never summarised or rewritten**: the audio is generated from exactly the sentences that were extracted,
and extraction problems are reported rather than papered over.

- **Frontend:** React + Vite + Tailwind, PDF.js, Axios, HTML5 Audio, SSE progress
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL, Celery + Redis
- **Extraction:** PyMuPDF (text layer, column-aware reading order) and Tesseract OCR (scanned pages)
- **Voice:** Kokoro TTS (local, primary); Edge TTS and Coqui XTTS-v2 as optional engines. No OpenAI key needed
- **Orchestration:** LangGraph (analyze → extract → validate → [OCR retry] → chunk)

## 1. Architecture

```
Upload ─► FastAPI ─► PDF Analyzer ─► text PDF ─► PyMuPDF ─┐
            │         (quick check at upload:  scanned ─► OCR ─┤
            │          corrupt / encrypted /                   ▼
            │          too many pages)               Text Validation ──(garbled pages)──► OCR retry
            ▼                                                │
     Celery / BackgroundTasks                         Chunk Manager  (sentences → chunks, integrity-checked)
     runs the LangGraph workflow                             │
                                                  pages + audio_segments rows in PostgreSQL
                                                             │
        browser asks for a segment ─► Voice Agent (Kokoro/Edge/XTTS) ─► per-sentence clips
                                      + pauses ─► one audio file + exact sentence timings (cached)
                                                             │
        <audio> plays the blob; requestAnimationFrame maps currentTime → sentence → highlight
                                                             │
                                  Playback Agent saves page/sentence/percentage ("resume")
```

The six agents live in `backend/app/agents/`:

| Agent | File | Job |
|---|---|---|
| PDF Analyzer | `pdf_analyzer.py` | validity, encryption, page count, text-vs-scanned per page |
| Text Extraction | `text_extraction.py` | PyMuPDF / OCR, reading order, headings, paragraphs with bounding boxes |
| Text Validation | `text_validation.py` | empty pages, extraction gaps, garbled text, duplicates. Reports only, never edits |
| Chunk Manager | `chunk_manager.py` | sentences → chunks; `verify_chunks` proves no sentence is lost or duplicated |
| Voice Generation | `voice_agent.py` | TTS per sentence, caching, 3 retries, idempotent (no duplicate segments) |
| Playback Management | `playback_agent.py` | position, next/prev sentence & page, progress %, resume |
| Workflow | `workflow.py` | LangGraph graph that wires the first four together |

Design decisions worth knowing:

- **Audio is generated lazily.** Processing extracts text and creates `audio_segments` rows (status `pending`). Audio for
  a segment is generated the first time it is requested, and the player prefetches the next two segments.
  "Pre-generate all audio" (button / `POST /voice/generate`) fills the cache in the background.
- **Highlight sync is exact.** Each sentence is synthesised separately and concatenated with known pauses, so the
  server knows every sentence's start/end time (`timings`). The browser just looks up `currentTime`.
- **Speed is client-side** (`audio.playbackRate`), so changing speed never regenerates audio.
- **Highlight on the PDF is paragraph-level** (the bounding box of the paragraph containing the sentence).
  The *Text* tab highlights the exact sentence.
- **`DELETE /history/{id}` resets reading progress only.** `DELETE /pdf/{id}` deletes the document, its audio and its progress.

## 2. Quick start with Docker (recommended)

```bash
docker compose up --build
```

Open http://localhost:3000, create an account, upload a PDF. API docs: http://localhost:8000/docs.
The first play downloads the Kokoro model (~330 MB) into the `models` volume; later runs are instant.
Set `SECRET_KEY` in your shell (or a `.env` next to `docker-compose.yml`) for anything beyond local use.

## 3. Local development without Docker

Prerequisites: Python 3.12, Node 20+, Tesseract (`tesseract-ocr`, plus `tesseract-ocr-hin` / `-mar` for Hindi/Marathi OCR),
FFmpeg, espeak-ng, libsndfile. PostgreSQL is optional locally: SQLite works for development.

**Backend** (`backend/`)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu     # CPU build; skip --index-url for GPU
pip install -r requirements.txt && pip install -r requirements-tts.txt
cp .env.example .env
# For zero-setup local dev, in .env use:  DATABASE_URL=sqlite:///./pdfvoice.db   and   TASK_BACKEND=inline
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

With `TASK_BACKEND=celery` also run Redis and a worker: `celery -A app.tasks.processing_tasks:celery_app worker --loglevel=INFO`.

**Frontend** (`frontend/`)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, /api is proxied to http://localhost:8000
```

## 4. Deploying the backend on Render

Render web services have an ephemeral filesystem unless a persistent disk is attached. This app refuses to start on
Render with SQLite configured, because a restart would erase accounts and uploaded documents. Use a persistent
PostgreSQL database and set these backend environment variables in the Render dashboard:

- `DATABASE_URL`: the Render PostgreSQL internal connection URL
- `SECRET_KEY`: a strong random value; keep it unchanged across deploys so existing login tokens remain valid
- `APP_ENV=production`
- `CORS_ORIGINS=https://project-ai-fourteen-pdfvoice.onrender.com`

After connecting PostgreSQL, accounts and documents from an ephemeral SQLite database cannot be recovered; users must
register again and upload their PDFs again. If the frontend shows a 502 while the backend is starting, check the
backend's Render deploy logs and retry after the service is live. A 502 generated by Render's proxy cannot be fixed by
the API's CORS headers.

## 5. Staged verification (matches the build order in the spec)

Run these in order; each stage should work before you trust the next.

1. **Upload + extraction** (no TTS needed)
   ```bash
   cd backend && pytest tests/test_upload.py tests/test_extraction.py tests/test_chunking.py -v
   ```
   Then, with the API running, open http://localhost:8000/docs → register → upload → `POST /pdf/{id}/process` →
   `GET /pdf/{id}/text?page=1`. You should see your text split into sentences with bounding boxes.
2. **TTS in isolation** (needs the Kokoro model, downloaded on first use)
   ```bash
   python - <<'PY'
   from app.services.tts_service import get_provider
   import soundfile as sf
   audio, sr = get_provider("kokoro").synthesize("Hello from PDFVoice AI.", "af_heart", "en")
   sf.write("hello.wav", audio, sr); print(len(audio) / sr, "seconds")
   PY
   ```
   Play `hello.wav`. If this works, segment generation will work.
3. **Playback + sync:** `pytest tests/test_tts_audio.py tests/test_playback.py -v` (uses a tone generator in place of a real
   voice, so it checks the timing/caching/retry logic, not voice quality).
4. **Everything:** `pytest -v` (69 tests), then use the UI.

Expected UI flow: upload → "Process & read" → progress bar (SSE) → reader opens → press ▶ → first sentence is
spoken and highlighted → pause/resume/next/previous work → close the tab → reopen → *Continue* resumes at the saved sentence.

## 6. API summary (all under `/api/v1`, JWT bearer auth except `auth/*`, `health`, `voice/available-voices`)

| Area | Endpoints |
|---|---|
| Auth | `POST auth/register`, `POST auth/login`, `GET auth/me` |
| PDF | `POST pdf/upload`, `GET pdf/{id}`, `GET pdf/{id}/file`, `GET pdf/{id}/pages`, `GET pdf/{id}/text?page=&start=&limit=`, `DELETE pdf/{id}` |
| Processing | `POST pdf/{id}/process`, `GET pdf/{id}/status`, `GET pdf/{id}/progress`, `GET pdf/{id}/progress/stream` (SSE) |
| Voice | `POST voice/generate`, `GET voice/{id}/segments`, `GET voice/{id}/segments/{seg}` (timings), `GET voice/{id}/audio/{seg}`, `GET voice/available-voices`, `GET/PUT voice/settings` |
| Playback | `POST playback/start`, `pause`, `resume`, `stop`, `seek` |
| History | `GET history`, `GET history/{id}`, `PUT history/{id}/progress`, `DELETE history/{id}` |

Errors always look like `{"error": {"code": "file_too_large", "message": "...", "details": [...]}}`.

## 7. Configuration

See `backend/.env.example` (every setting is documented there). Most useful: `TASK_BACKEND`, `DATABASE_URL`,
`STORAGE_BACKEND` (`local` or `s3`), `CORS_ORIGINS` (include the exact frontend origin),
`ACCESS_TOKEN_EXPIRE_MINUTES` (defaults to four days),
`MAX_UPLOAD_MB`, `OCR_LANGUAGES`, `CHUNK_MAX_CHARS`, `AUDIO_FORMAT`. Uploaded PDF bytes are stored in the
database; audio files continue to use the configured storage backend. Existing PDFs stored before this change
remain readable from their original storage location.

## 8. Languages and voices

| Language | Kokoro (local) | Edge TTS (online) |
|---|---|---|
| English (US/UK) | yes | yes (incl. en-IN) |
| Hindi | yes | yes |
| Marathi | **no** | yes |

Choosing Marathi automatically switches to Edge TTS (needs `pip install edge-tts` and internet access).
OCR language packs: install `tesseract-ocr-hin` / `-mar`; missing packs are skipped, falling back to English.

## 9. Security notes

Uploads are checked by extension **and** `%PDF-` magic bytes, size-capped while streaming, filename-sanitised and stored under
random keys; storage paths never appear in API responses; every document query is scoped to its owner (other users get a
404); passwords use scrypt; the API refuses to start in production with the default `SECRET_KEY`. PDFs are parsed, never executed.
Before going public also add: HTTPS, rate limiting on `auth/*` and upload, and a malware scan if you accept files from strangers.

## 10. Known limitations

- Real Kokoro / Edge / XTTS audio could not be exercised in the environment this project was generated in (no model
  downloads); the engine adapters follow each library's documented API. Run stage 2 above first.
- The browser UI was compiled (`npm run build`) but not driven in a real browser; expect to polish small things.
- PDF highlighting is per paragraph, and assumes unrotated pages.
- Sentences that run across a column or page break are read as separate sentences.
- XTTS-v2 has no Marathi voice; its Hindi entry reuses an English speaker and is experimental.
- S3 storage is implemented but untested against a real bucket.
