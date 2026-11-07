# Operations release candidate 0.6.0

Adds content-free OpenTelemetry instrumentation and durable API-to-worker trace
propagation, optional consent-gated Langfuse OTLP export, Prometheus metrics,
provisioned Grafana/Tempo monitoring, safe JSON logs and consistent error categories.
Adds bounded provider retry with jitter, finite cleanup recovery, connection-pool
limits, worker/dispatcher health, version/source fingerprints, backup/restore tools,
synthetic concurrent-load experiments and live release acceptance scripts.

Database migration `20261108_operations` adds nullable ingestion-job trace context.
Apply migrations/bootstrap before starting new workers. Existing jobs without traces
continue normally. Regenerate private role environments after changing `.env`.
The monitoring overlay is optional and publishes dashboards on loopback only.

Validation commands:

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
./scripts/test_services.ps1
uv run python -m evaluation.security.run
uv run pip-audit
uv run python -m evaluation.release_report
```

See the generated final report for measured native/service/load results and live
provider evidence. The readiness checklist remains the release gate. No production
deployment or `v1.0.0` release is claimed while required operational checks are open.
Git commit/push details are recorded in the roadmap after independent verification.

Executed local gate: frozen install, Ruff lint/format, mypy, complete native and
real-service suites (counts in the generated report), four load cases, 14 live acceptance
checks, four live conversation turns across an API restart, eight live security
checks and 32 deterministic policy cases. Installed and full optional lock audits
found no known vulnerabilities. Local OTLP/Prometheus/Grafana and a disposable
PostgreSQL restore canary passed. Earlier fourth-turn failures remain in the evidence
directory; partial-answer policy and grouped-source validation resolved that regression.
Further semantic review corrected stale ordinal lists when the latest answer uses
prose or descriptive labels. The live check now verifies the intended method, not
only that some citation exists; the final run correctly explains early stopping and
identifies its missing source example. Those earlier failures are also retained.
The optional production overlay and host Caddyfile have syntax validation, including
a network-isolated CI check. They require real domains and explicit trusted proxy
configuration before use; no public deployment or certificate issuance was performed.
