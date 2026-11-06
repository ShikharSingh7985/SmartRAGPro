# Data retention and deletion

Messages and private documents are retained until owner deletion by default. This is
an explicit application policy, not a legal retention recommendation. Use synthetic
data until the operator has approved private document and external-provider handling.

Document deletion immediately removes ready retrieval eligibility and derived
conversation text/summaries/checkpoints, then queues retryable physical deletion of
original/asset objects, vectors and SQL extraction/search records. Temporary parser
directories use context-managed cleanup. Orphan uploads have durable compensation jobs.

DELETE /api/v1/auth/account requires the password and current JWT. It disables the
account, revokes sessions, pseudonymizes its address, replaces the password hash,
removes conversations/checkpoints and marks every document deleting in one transaction.
The owner tombstone survives storage failures so cleanup jobs cannot be cascaded away.
Hourly dispatcher maintenance removes the account only after all document rows are
physically cleaned. Cleanup retries may extend retention during dependency outages.

Audit events contain only actor/resource UUIDs and event codes and expire after
SECURITY_AUDIT_RETENTION_DAYS (default 90); deleted actors become null. Content
inspections contain reason metadata and cascade with document deletion. Refresh rows
expire at their absolute expiry; consumed credentials remain until then for reuse
detection. Dispatcher maintenance is idempotent. Embedding caches are bounded, expire
within the configured TTL, and remain inaccessible to revoked users; memory copies
are not guaranteed cryptographically erased.

S3 versioning, backups, database WAL, provider retention and host snapshots can retain
copies beyond application deletion. The local stack does not configure backup expiry
or provider zero-retention. Production requires documented encrypted backup retention,
restore-time deletion replay and a provider agreement. No legal-compliance claim is made.
