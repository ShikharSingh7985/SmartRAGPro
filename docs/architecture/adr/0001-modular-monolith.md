# ADR 0001: Modular monolith and durable SQL worker

Accepted. One FastAPI backend and a separate worker share domain code. PostgreSQL
job rows with leases, SKIP LOCKED and retry backoff avoid introducing a second queue
consistency boundary in Phase 1. Redis provides shared rate limiting and is available
for future caching/queue infrastructure. No fake in-process background tasks.

Consequence: transaction locks can span external calls; benchmark before increasing
concurrency. A dedicated queue may be adopted when throughput justifies its complexity.
