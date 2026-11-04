# Local development

Requires Python 3.12, uv, Git, and Docker Desktop using Linux containers. Commands below
are PowerShell from repository root. No model credentials are required for automated tests.

## Install and test

```powershell
uv sync --frozen --python 3.12
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run pre-commit install
```

Run real infrastructure tests in a disposable database/bucket/vector collection:

```powershell
./scripts/test_services.ps1
# After testing, stop only these containers:
./scripts/test_services.ps1 -Stop
```

The script builds a Linux test image and starts dedicated services with explicit
nonproduction test credentials, avoiding host sandbox/cache permission differences.
It uses PostgreSQL at localhost:55432, Qdrant at 56333, Redis at 56379, S3 at 59000.
Tests migrate up/down the dedicated `smartrag_test` database; never point them at
application data. Without TEST_* variables, pytest uses temporary SQLite, in-process
Qdrant, an object-store double and a Redis double. Both modes mock only the model
and embeddings; infrastructure mode uses real datastore services. Unix equivalents:
run `docker compose -p smartrag-test -f docker-compose.test.yml --profile tests run --build --rm tests`.
Native tests may instead set `TEST_DATABASE_URL`, `TEST_QDRANT_URL`, `TEST_REDIS_URL`,
`TEST_S3_ENDPOINT` to the exposed local test ports before pytest. Use only this
disposable test stack: the test fixture resets its database, bucket and collection.

## Configure the real app

1. Run `uv run python -m scripts.configure_local` to create an ignored `.env` with
   unique random local JWT/database/S3 credentials. It preserves any existing `.env`.
   Alternatively copy `.env.example` to `.env` and configure the values yourself.
   Never paste secrets in chat.
2. Generate separate random values locally using `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   Put one in `JWT_SECRET`, one in `POSTGRES_PASSWORD` and the password segment of
   `DATABASE_URL`, and another in `S3_SECRET_KEY`. URL-encode special database password
   characters (token_urlsafe avoids this problem). Keep service hostnames for Compose.
3. Obtain a Gemini key in [Google AI Studio](https://aistudio.google.com/apikey),
   selecting/creating your own project. Enter it only in `.env` as `GEMINI_API_KEY`.
   Availability and free quotas depend on account, region and model; paid billing may
   be required. Check [current pricing](https://ai.google.dev/gemini-api/docs/pricing).
4. Confirm `GEMINI_MODEL` is available to your account. Default: `gemini-3.8-flash`.
   Embedding defaults: google, `models/gemini-embedding-001`, 768 dimensions.
5. For OpenAI embeddings set `EMBEDDING_PROVIDER=openai`, `OPENAI_API_KEY`,
   `EMBEDDING_MODEL=text-embedding-3-small`, and a fresh `QDRANT_COLLECTION`.
   This may incur OpenAI charges. Gemini is still used for generation.

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health/ready
```

Open http://localhost:8501. Register, sign in, upload a small text PDF under Documents,
refresh until ready, select ready PDFs in Chat, create a conversation, ask a question,
and inspect sources. Open http://localhost:8000/docs for API exploration.
Bootstrap runs migrations, creates the private bucket, initializes the vector collection,
and checks Redis before API/worker start. No API keys are needed to build images.

Stop with `docker compose down`; named volumes preserve data. Do not remove volumes
unless you intend to erase the local application data. API and worker must use identical
embedding settings. A provider/model/dimension change requires a new collection and
reuploading documents. Never enable LangSmith tracing for private documents casually.

## Migrations and troubleshooting

```powershell
docker compose run --rm bootstrap
docker compose logs --tail 60 worker
docker compose logs --tail 60 api
```

Live readiness is 503 if a datastore is unavailable or the Gemini key is absent.
Readiness does not spend tokens or prove key validity. Worker errors intentionally
omit provider details; verify configured endpoints/credentials locally. Three ingestion
failures mark a document failed. Delete/reupload after repairing configuration. Cleanup
retries indefinitely. A model outage returns 503 without partial conversation records.

After supplying real keys, explicitly probe the actual configured providers with
`docker compose run --rm api python -m scripts.live_providers`. This spends real
provider quota and must pass before claiming live Gemini acceptance. It tests real
document/query embeddings and a cited Gemini response using synthetic public evidence.
Then perform the UI PDF/chat workflow above for full live acceptance.

For native API/worker development expose infrastructure ports using the dedicated
test stack only with disposable data, set application URLs to localhost endpoints,
run `uv run alembic upgrade head`, initialize the bucket/collection using
`uv run python -m scripts.bootstrap`, then use separate terminals:

```powershell
uv run uvicorn backend.app.main:app --reload --no-access-log --no-proxy-headers
uv run python -m backend.app.workers.ingestion
$env:API_BASE_URL='http://localhost:8000'
uv run streamlit run frontend/app.py
```

## GitHub milestone

Provide your intended user-owned HTTPS or SSH repository URL. Create an empty private
repository in GitHub (no generated README/license) if necessary; basic repositories
can use a free account. Authenticate locally with `gh auth login` or your Git credential
manager/SSH agent. Never send a personal token, password or private key in chat.
After the destination is confirmed: preserve/fetch remote history, reconcile without
force, push main and `v0.1.0-mvp`, and compare `git ls-remote` with the local commit/tag.
