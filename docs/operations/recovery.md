# Recovery and operating procedures

`/health/live` reports process health, package version and a normalized source digest.
`/health/ready` checks PostgreSQL/checkpoint schema, Redis, Qdrant and the private S3
bucket; it checks model configuration without spending provider tokens. An unavailable
dependency returns 503. Readiness is not proof of Gemini quota or model availability.
Worker/dispatcher health checks use Redis heartbeats with expiry. One worker process
and one thread bound OCR memory; scale only after measuring deployment capacity.

API SQL connections have bounded pools (5 plus 5 overflow by default), ten-second
acquisition timeout, pre-ping and recycling. Gemini requests have 45-second call
timeouts and at most three transient attempts with jitter; permanent provider errors
are not retried. SQL ingestion leases/fencing, job attempt budgets, actor time limits,
page timeouts and upload quotas limit failures. Shutdown stops dispatch and allows
the worker 120 seconds before lease recovery must take over. A forcibly interrupted
job is recovered from durable SQL state; Redis is transport, not the job authority.
The local API container still uses Docker's default stop timeout; an interrupted
in-flight answer rolls back and must be retried with the same request ID. Set a
deployment-specific longer stop grace when a host must drain long provider calls.

For failed deletion, retrieval stays revoked. Inspect the failed job and repair its
dependency before requeueing in the trusted dispatcher role:

```powershell
docker compose exec dispatcher python -m scripts.retry_cleanup DOCUMENT_UUID
```

No infinite retry loop is permitted. This command is privileged, audited and requires
host/container access. Monitor failed jobs and clean temporary files through normal
worker cleanup. Account deletion revokes sessions, removes text/checkpoints and queues
physical cleanup. Keep audit retention configured; successful graph turns keep only
the latest checkpoint while complete SQL messages remain until source/account deletion.
See the security retention policy for limitations and legal retention decisions.

PostgreSQL backup (private dump, never committed):

```powershell
uv run python -m scripts.database_backup backup --project smartragpro --database smartrag --directory .backups/DATE
```

The helper uses `pg_dump -Fc`, a streamed SHA256 checksum and a manifest. Dumps are
unencrypted locally: restrict permissions, encrypt off-host, define retention and
test restores. A checksum proves integrity, not recoverability. The automatic restore
command accepts only disposable `smartrag_test` plus `--confirm-disposable`:

```powershell
uv run python -m scripts.database_backup restore --project smartrag-test --compose docker-compose.test.yml --database smartrag_test --directory .backups/DRILL --confirm-disposable
```

Production restore: stop API/worker/dispatcher; snapshot current volumes; provision an
isolated replacement PostgreSQL instance; verify dump checksum; restore with matching
PostgreSQL tools, reviewed roles/ownership and `pg_restore --exit-on-error`; run
migrations/checkpoint setup; validate row counts and ownership; restore matching object
storage; reindex or restore Qdrant; run private acceptance tests; switch traffic only
after review. Never restore directly over a live database as a first experiment.

Back up S3 originals/derived assets separately using provider versioning and encrypted
off-host replication. Local SeaweedFS volumes need a consistent stopped-service backup;
copying a live directory is not a tested backup. Qdrant snapshots must match collection
embedding model/dimensions/version. Vectors can be rebuilt from originals, but that
costs embedding calls. Retain SQL/object backups consistently; a SQL-only restore does
not restore files. Redis AOF supports restart recovery, but SQL outbox replay remains
necessary. Schedule restore drills, document RPO/RTO and measure them on target hosting.

Rotate JWT secrets by invalidating/reissuing sessions during a controlled window;
rotate DB/Redis/Qdrant/S3/provider credentials in the upstream service, update ignored
role environments, restart consumers and verify least-privilege probes. Never change
only a Compose variable and assume an existing PostgreSQL role password was changed.
