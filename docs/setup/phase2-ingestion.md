# Phase 2 operation and validation

## Installation

The standard image includes Tesseract and English language data. The worker target
adds the locked `parsing` extra (Docling, CPU Torch). Keep its model-cache volume;
the first conversion downloads public layout/table artifacts and takes longer.
No Hugging Face account is needed for those public artifacts. Network availability
is required until cached. Set `DOCLING_ARTIFACTS_PATH` to predownloaded artifacts for
controlled/offline deployments. `HF_HOME` points at the worker's persistent cache.

```powershell
uv sync --frozen
# Native structural parsing, optional local embeddings:
uv sync --frozen --extra parsing
uv sync --frozen --extra parsing --extra local
docker compose up --build -d
```

For native OCR, install Tesseract and the language packs you need, then set
`TESSERACT_CMD` to its executable or keep it on PATH. Windows tests skip actual OCR
when it is absent; the Linux test image runs it. Configure `OCR_LANGUAGE=eng` or an
installed combination such as `eng+hin`. `OCR_BACKEND=disabled` disables OCR explicitly;
unreadable pages then fail rather than receiving fabricated text. Additional language
packs are an operator installation; they are not silently downloaded by the app.

## Extraction modes

| Mode | Behavior |
| --- | --- |
| auto | Inspect embedded text, primary Docling structure, selective OCR on weak text, figure label OCR where applicable |
| text-first | Structure and embedded text without OCR or vision; unresolved images remain explicit visual-only sources |
| ocr-enabled | Request OCR even when embedded text is usable |
| enhanced-multimodal | Auto behavior plus budgeted Gemini figure descriptions only when VISION_ENABLED=true |

PDFs retain their original private S3 object. Digital text quality uses transparent
indicators (characters, replacement characters, usability flag), not a fabricated
confidence score. Tesseract reports its own mean word confidence when available;
it is not a calibrated document accuracy percentage. Inspect page quality/warnings in
the UI. Docling failures are recorded as fallback warnings.

Vision is disabled by default. Enable locally with `VISION_ENABLED=true`, select an
available `VISION_MODEL`, set `MAX_VISION_CALLS`, then upload in enhanced mode. It uses
the locally configured `GEMINI_API_KEY`; calls may be paid. OCR/layout models run locally
and have no per-page API fee; CPU time, RAM, model downloads and storage still cost
resources. Do not equate OCR labels or a figure caption with visual understanding.

## Limits and scaling

`MAX_PDF_PAGES` defaults to 1000 (older `.env` files may still set 300; update that
nonsecret value for 500+ pages). Upload bytes remain configurable and capped at 100 MB;
the default is 20 MB. Streamlit and API upload caps must agree for larger files.
`RENDER_MAX_DIMENSION`, `RENDER_DPI`, `MAX_FIGURES_PER_PAGE`, `OCR_TIMEOUT_SECONDS`,
`PAGE_TIMEOUT_SECONDS`, `INGESTION_TIMEOUT_SECONDS` and `MAX_EXTRACTED_CHARACTERS`
are safety limits. Original raster streams over 16 million pixels remain in the
original PDF; bounded rendered source assets are retained instead.

The worker runs one process/thread with a 4 GiB container ceiling and CPU-only models.
This ceiling is not a claim that all documents fit. Increase concurrency only after
measuring total model memory and provider quotas. Document locks serialize jobs for a
single document across processes; SQL lease recovery is ten minutes after the last
heartbeat. Native-library timeouts are cooperative; container restart recovers crashes.
Full hard isolation per page and multi-host load testing remain future operational work.

Redis uses AOF persistence. SQL dispatch happens every two seconds, with a 30-second
redelivery interval for unclaimed messages. Redis/Dramatiq dead letters are not the
durable recovery record: failed SQL jobs remain visible and can be retried by their
owner. Ingestion attempts are bounded; invalid/encrypted PDFs fail without pointless
retries. Transient provider/storage/OCR failures back off. Cancellation is checked at
stage/page boundaries; it cannot instantly interrupt an executing native call.

## API additions

All endpoints require verified ownership; foreign resources return 404.

- Multipart upload now accepts `extraction_mode`. An exact owner/hash/mode duplicate
  returns the existing document ID without re-embedding.
- `GET /api/v1/documents/{id}/jobs` returns stages, page progress, attempts and safe errors.
  Public statuses are queued, processing, completed and failed; SQL retains legacy
  running/succeeded names for migration compatibility.
- `POST /api/v1/documents/{id}/retry`, `/cancel`, `/reindex` perform authorized control.
- `GET /api/v1/documents/{id}/pages/{page}` returns structured extraction and quality.
- `GET /api/v1/documents/{id}/preview/{page}` returns a bounded source image.
- `GET /api/v1/documents/{id}/assets` and `/assets/{asset_id}` expose owned image assets.

Assets are delivered through authenticated server requests; tokens are never put in
image URLs. Deletion removes derived conversations, every recorded asset/page, original
PDF, and vectors from every index referenced by the document's ingestion history.

## Embeddings and reindexing

Default Google embeddings use configurable `models/gemini-embedding-001` with 768
dimensions, as exercised in Phase 1. The adapter uses installed LangChain integration
APIs and records provider/model/dimension/EMBEDDING_VERSION fingerprints. OpenAI remains
supported. Optional `EMBEDDING_PROVIDER=local` requires the `local` extra in the worker
and API, `LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`, dimensions 384,
and a **new QDRANT_COLLECTION**. Local inference needs an initial model download.
The default Docker images do not install the optional local extra. Its adapter must
be validated in the intended environment before claiming that model accepted.

For a model/dimension/version change: pause new ingestion, configure identical settings
on API/worker, choose a fresh collection, bootstrap it, restart services, and request
Reindex on each owned ready document. The API rejects incompatible document indexes.
Existing Phase 1 files/accounts/chats are preserved by the additive migration. Reindex
old documents to obtain Phase 2 extraction metadata. Unchanged chunks in the same
embedding space reuse vectors; new spaces must be embedded anew. Old index data stays
private until document cleanup; index retirement needs an operator retention policy.

## Repeatable checks

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
./scripts/test_services.ps1
$env:TIKTOKEN_CACHE_DIR = "$PWD/.uv-cache/tiktoken"
uv run python -m scripts.benchmark_ingestion --pages 520 --engine pymupdf
```

Install/cache token data once with `uv run python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"`.
The Docker image caches it during build. Tests use generated synthetic PDFs and mock
embeddings/generation; the integration mode uses real SQL, Redis/Dramatiq, Qdrant, S3
and Tesseract. The primary Docling model probe is separately recorded in the Phase 2
validation report. No private benchmark documents are committed.

For explicit live vision, provide a locally stored image, enable vision as above and
run `uv run python -m scripts.live_vision path/to/image.png`. This consumes real quota.
For full real ingestion use `scripts.live_ingestion` against a running API and **synthetic
PDFs only**: it registers a synthetic account, uploads/monitors files, and queues
document deletion afterward. Account metadata remains until an administrator removes
that synthetic account. Do not feed this utility private evaluation datasets casually.
