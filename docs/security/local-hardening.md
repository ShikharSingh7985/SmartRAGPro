# Apply and verify local hardening

Keep the existing .env and provider selections. Install the frozen dependencies, then:

```powershell
uv run python -m scripts.configure_security
docker compose up -d --build
docker compose ps
docker compose exec -T api python -m scripts.security_infrastructure
docker compose exec -T worker python -m scripts.security_infrastructure
```

The helper only supports the existing internal postgres/redis development endpoints.
It generates random local credentials, preserves provider keys and unrelated settings,
and writes ignored .docker-local/{api,worker,dispatcher,bootstrap}.env plus redis.conf.
It does not print secrets. Rerun it after editing .env; Compose uses the generated
role files, so editing .env alone no longer updates application settings. Protect
both .env and .docker-local with your OS account permissions. Do not share them or
run docker compose config in public logs: expanded output contains credentials.

Bootstrap runs Alembic/checkpointer migrations as the original database owner and
grants runtime roles before the API/worker start. It preserves the existing database
volume and history. Runtime users cannot perform schema creation or modify migration
tables. Worker cannot read password hashes, sessions or checkpoints. Redis persists
with requirepass; Qdrant has separate write/read-only credentials. Internal services
have no host ports; only API/UI bind to loopback. The separate disposable test stack
uses intentionally public test-only credentials on loopback.

Bootstrap uses a client-generated SCRAM verifier in ALTER ROLE rather than sending
plaintext passwords in SQL statements. See the installed psycopg interface's
[primary documentation](https://www.psycopg.org/psycopg3/docs/api/pq.html).

The worker is UID 10001, read-only root, all capabilities dropped, no-new-privileges,
PID 128, CPU 1, memory 4 GiB and a bounded 1 GiB /tmp. The model-cache volume remains
writable. Its single process/thread avoids uncontrolled OCR/model concurrency.
Cancellation/deadlines are cooperative between stages; an uninterruptible native
parser relies on container resource limits and operator restart, not a guaranteed
per-page process kill. Do not expose this development stack directly to the Internet.

For hosted services, provision equivalent credentials through a secret manager;
do not run the local helper against them. Run migrations in a separate bootstrap
identity, use least-privilege runtime DB/IAM roles, TLS and network policies. Set
ALLOWED_HOSTS, CORS_ORIGINS and REQUIRE_HTTPS for the actual deployment. The default
server ignores forwarded headers; a TLS reverse proxy requires an explicit trusted
proxy/transport configuration. Do not trust arbitrary X-Forwarded-* values.

Optional malware scanning: provision a maintained ClamAV clamd service with current
signatures on the private network, enable INSTREAM TCP access only for the worker,
then set CLAMAV_ENABLED=true, CLAMAV_HOST and CLAMAV_PORT in .env and regenerate envs.
Confirm a harmless industry test signature is rejected in a disposable environment.
ClamAV software is free; hosting, memory, downloads and signature operations can cost
resources. Enabled scanner outages fail ingestion closed. Protocol tests use mocks;
no live antivirus effectiveness claim is made without a real scanner run.

Repeatable validation:

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
./scripts/test_services.ps1
uv run python -m evaluation.security.run
uv run pip-audit --format json --output evaluation/security/dependency-audit.json
# Optional real provider calls: Gemini free quotas or paid API usage may apply.
uv run python -m evaluation.security.run --live --output evaluation/security/adversarial-results.json
docker compose exec -T api python -m scripts.security_acceptance
```

On this Windows host set UV_CACHE_DIR=.uv-cache if the global cache is inaccessible.
The live acceptance creates only synthetic PDFs/accounts and queues their deletion.
Copy /tmp/security-acceptance.json from the API container for review. It performs
real Gemini generation; deterministic tests always identify their isolated providers.
Native image/OS and model-weight vulnerability scanning remains a deployment gate.
