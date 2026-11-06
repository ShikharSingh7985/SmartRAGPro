# Incident response

1. Restrict ingress and preserve UUID-only audit events, timestamps, affected policy
   versions and deployed commit. Do not paste private PDFs, bearer tokens or keys into
   tickets. Preserve encrypted evidence only in an approved restricted location.
2. For a stolen account credential, disable the user and increment token_version in a
   reviewed administrator transaction; revoke all refresh rows. Password change/logout
   already perform revocation. A user-supplied consumed refresh triggers this response
   automatically. Do not delete reuse evidence before investigating its expiry window.
3. For malicious source content, revoke its ready SQL state, use authorized deletion
   or reindex after policy review, and purge affected conversations/checkpoints. Do not
   restore ready status based solely on heuristic scores or intact vector records.
4. For service compromise, isolate the host/worker, rotate JWT/Gemini/S3/Qdrant/Redis
   and database credentials in a secret manager, regenerate local private runtime envs,
   and restart affected services. Changing PostgreSQL image environment alone does
   not rotate an existing initialized database password; use reviewed ALTER ROLE.
5. Verify physical cleanup retries, provider access/billing logs and storage access
   before returning service. Restore encrypted backups only into a quarantined stack;
   apply revocations/deletions again before enabling reads.
6. Rerun isolation, refresh, upload, poisoning and real-service acceptance tests, record
   the failure and remediation, and obtain an independent review for significant leaks.

The application has no public administrative endpoint. Production alert routing,
forensic export, incident paging, notification obligations and recovery drills require
operator arrangements. This document does not claim those operational systems exist.
