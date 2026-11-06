# Phase 5 security validation

Executed on 2026-11-06 against the existing application. This report distinguishes
application enforcement, live model behavior, deployed-service acceptance and residual
risks. A passing synthetic fixture is not a claim of general attack resistance.

## Controls delivered

Argon2id/password rehashing; fully validated access JWTs and active account versions;
opaque hashed refresh credentials with absolute expiry, rotation, replay revocation
and owner-lock serialization; generic account failures; account/IP rate limits;
password-change revocation; disabled-account and durable account deletion handling.
Already-revoked credentials cannot repeatedly revoke newly established sessions.

Tenant/document/run filters remain mandatory before vector/SQL retrieval. Owned
asset/job/page/security endpoints, canonical storage keys, actual request-byte limits,
upload/derived-data/job quotas, PDF active-object and resource checks, optional
fail-closed malware scanning and worker-generated previews strengthen the boundaries.
The worker has a read-only root, nonroot UID, no capabilities, no-new-privileges and
CPU/memory/PID/tmp limits. Runtime DB grants and authenticated Redis/Qdrant replace
shared administrator/anonymous runtime access. The API's Qdrant key is read-only.

Versioned ingestion/retrieval/memory inspection, deterministic capability boundaries,
bounded untrusted context, citation ownership checks, output gates and plain Streamlit
rendering provide layered poisoning protection. See [design](prompt-injection-defense.md),
[threat model](threat-model.md), [authentication](authentication.md) and
[authorization](authorization.md). No autonomous tools or URL fetchers were added.

## Adversarial evidence and false positives

[cases.json](../../evaluation/security/cases.json) contains 24 distinct synthetic attacks
and eight benign negative controls. Categories include role spoofing, exfiltration,
scope escalation, answer/retrieval manipulation, encoding/obfuscation, metadata and
memory poisoning. Every record identifies its payload, expected behavior and provenance.
[policy-results.json](../../evaluation/security/policy-results.json) records current v3
actual reason codes, decisions, timestamps, configuration, pass/fail and limitations.
All 32 raw-policy classifications pass; none of the eight benign controls hard-blocks.
These are rule classification results, not 24 independent successful live model attacks.

The [preserved v1 live baseline](../../evaluation/security/adversarial-baseline-v1.json)
made six actual Gemini calls. Five passed the synthetic canary/fact/citation checks;
one forced-answer payload produced the canary instead of the revenue while retaining
a citation. This demonstrates that valid citation syntax alone does not ensure grounding.
Policy v2 classified direct forced-answer instructions as high-confidence quarantine.
Its [six-case rerun](../../evaluation/security/adversarial-results.json) passed all six
checks: four real Gemini calls passed the checks and
two attempts were blocked before a provider request. Quarantine is explicitly not
reported as model resistance. Model: gemini-3.5-flash-lite; temperature 0 was requested
but the installed integration reports that the provider uses fixed sampling defaults.
These checks do not replace human semantic review or adaptive red teaming.

The real HTTP workflow passed seven of eight checks: refresh rotation, benign digital
PDF ingestion, worker PNG preview, a real cited Gemini answer, malicious-PDF rejection,
refresh reuse revocation and queued account cleanup. Its educational PDF falsely
failed. [Diagnostic evidence](../../evaluation/security/live-education-probe.json)
shows override/evidence_override score 95 at ingestion, with metadata allowed. The
deployed inspector flattened JSON-escaped source content and lost quotation context.
The current v3 source preserves literal quotations during structured inspection and
includes the exact educational text as an integrated PDF regression. Both educational
PDF regressions and revoked-session recovery pass locally. A final application rebuild
was declined, so the corrected source is **not claimed live-deployed or live-verified**.
The failing [HTTP report](../../evaluation/security/live-http-acceptance.json) is preserved.

Earlier deterministic failures also exposed ASCII85-before-Flate compatibility,
duplicate ASGI terminal body messages, negated educational scope statements and an
S3 integration assertion that incorrectly assumed the in-memory test store. The parser,
middleware/rules and storage-specific verification were corrected; failures were not
suppressed. Real S3 cleanup now checks absence of each original and asset object.

## Validation scope

Frozen dependency installation, Ruff lint/format and mypy run against the current
source. Final native execution passed 128 tests, with five expected skips (host OCR
and PostgreSQL-only checks), in 167.04 seconds. The complete disposable-service run
passed 132 tests with no failures/skips in 531.08 seconds. Five focused final-v3 service
checks also passed in 31.00 seconds, including both educational fixtures. See
[native case results](../../evaluation/security/native-test-results.json),
[service results](../../evaluation/security/service-test-results.json) and
[final focused results](../../evaluation/security/focused-service-test-results.json).
Tests include authentication, invalid/expired/purpose-mismatched JWTs, rotation
and replay, disabled accounts, password changes, upload abuses, quarantined legacy
vectors, summary poisoning, account cleanup, foreign objects/jobs/chats, real PostgreSQL
rotation concurrency, runtime role grants, migrations and persistent conversations.
All automated model/embedding doubles remain confined to isolated tests. Windows denied
the initial report/temp directory; those nonzero artifact/setup failures were resolved
by using a workspace-owned temp directory and rerunning successfully, not suppressing
failed tests. The final native command used --basetemp=.pytest_cache/security-native-final.
The dedicated security module has 56 native passes and two PostgreSQL-only skips;
the latter checks pass against real PostgreSQL. Cross-user access and storage isolation
regressions pass in the complete native/service suites.

[Live API probes](../../evaluation/security/infrastructure-api.json): 4/4 passed.
[Live worker probes](../../evaluation/security/infrastructure-worker.json): 5/5 passed.
They verify non-admin runtime accounts, worker denial of password/session/checkpoint
reads, Redis/Qdrant auth, API read-only vector access and process capability restrictions.
Docker inspection separately confirmed read-only root and the 4 GiB memory limit.

The retrieval regression reran all 108 synthetic questions using cached **real Google
embeddings**, actual in-process Qdrant and unchanged relevance labels. Held-out dense
Recall@5 remains 1.0 on 53 answerable questions; BM25 remains 0.990566. This is metric
regression over an unreviewed synthetic corpus, not security accuracy or a new provider
latency measurement. Cached provider timings retain their earlier provenance. See
[machine-readable rankings](../../evaluation/security/retrieval-regression/retrieval.json).

## Dependency and secret scanning

pip-audit 2.10.1 reported no known vulnerabilities among audited installed packages:
174 records, one skipped local project (the application itself). The all-extras lock
audit has 233 records and no known findings among audited versions, with torch
2.15.0+cpu and torchvision 0.29.2+cpu explicitly skipped because those exact CPU builds
are absent from PyPI. Platform markers limit each host's scope. Reports are
[installed](../../evaluation/security/dependency-audit.json) and
[optional lock](../../evaluation/security/dependency-audit-all-extras.json).
This does not scan native image/OS packages, model weights or prove vulnerability absence.
CI performs frozen install, full tests, deterministic adversarial checks, dependency
audits and tracked-source secret/artifact scanning; live model calls are separate.
Final staged-byte scanning and Git verification are recorded with the milestone.

## Remaining gates and priorities

1. Rebuild/restart the final source and rerun the HTTP acceptance workflow; the declined
   rebuild blocks verification of the educational false-positive fix in deployment.
   Commands and the secure configuration flow are in [local hardening](local-hardening.md).
2. Before Internet deployment, provision TLS/trusted proxy settings, external secret
   management, least-privilege S3 IAM, native image/OS/CPU-wheel scanning, encrypted
   backup retention and independent adversarial review. Local bridge traffic is trusted.
3. If malware scanning is required, provision ClamAV and execute a real scanner test.
   The INSTREAM protocol and unavailable-service behavior are tested with isolated mocks;
   no running antivirus/signature effectiveness is claimed.
4. Model-grounding failures, multilingual/steganographic instructions, parser/container
   exploits and compromised operators/workers remain risks. RLS is not enabled; current
   explicit authorization and role separation do not contain a compromised API host.

Phase 5 deployment acceptance remains open. No Phase 6 work is authorized or started.
