# Release evidence

Only public synthetic measurements and content-free operational results belong here.
Native/unit tests use deterministic model/embedding doubles. Service integration
tests use real disposable PostgreSQL, Redis, Qdrant and S3 with those same test doubles.
`load/` measures 1/5/10/25 in-process ASGI clients with a simulated 30 ms generator,
8-dimensional test vectors, real disposable services and four turns per user. This
does not measure network ingress, live Gemini quota, OCR concurrency or production scale.

`user-acceptance.json`, `security-acceptance.json` and `conversations.json` are explicit
live HTTP/provider checks over public generated PDFs. Word/citation assertions are
deterministic proxies, not independently reviewed semantic answer correctness. The
conversation script restarts the actual API after logout to verify persistence.
`monitoring.json` verifies local scraping, dashboard provisioning and OTLP delivery.

Reproduce after starting the stack:

```powershell
uv run pytest --junitxml=evaluation/release/native-final.xml
./scripts/test_services.ps1
docker compose -p smartrag-test -f docker-compose.test.yml --profile tests run --rm -v "${PWD}/evaluation/release:/results" tests python -m pytest --no-cov --basetemp=/tmp/final -o cache_dir=/tmp/pytest-cache --junitxml=/results/service-final.xml
uv run python -m scripts.release_acceptance
uv run python -m scripts.security_acceptance --output evaluation/release/security-acceptance.json
uv run python -m scripts.live_conversations --restart-api --output evaluation/release/conversations.json
uv run python -m scripts.verify_monitoring
uv run python -m scripts.verify_restore
docker compose -p smartrag-test -f docker-compose.test.yml --profile tests run --rm -v "${PWD}/evaluation/release:/results" -e LOAD_RESULTS_DIR=/results/load tests python -m pytest tests/benchmark_load.py --no-cov --basetemp=/tmp/load -o cache_dir=/tmp/pytest-cache
uv run python -m evaluation.release_report
```

Run load/service tests sequentially: migration tests downgrade the disposable database.
Live calls may incur charges. Never run live-provider load tests without quota/budget
approval. Private PDFs, prompts, credentials, embeddings and raw trace exports stay
outside this directory. XML test-run output is ignored; the generated report records
aggregate results without workstation identifiers.
