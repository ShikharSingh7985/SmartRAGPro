# Security boundaries and credential lifecycle

Decision: preserve the modular monolith and durable SQL outbox. Add opaque, hashed,
one-use refresh credentials; PostgreSQL owner locks serialize rotation and compromise
revocation. Keep authorization outside LangGraph. Use the existing session version
for global access revocation rather than a process-local JWT denylist.

Keep PDF parsing in the isolated worker, including preview rendering. Bound extraction
and derived storage. Use PostgreSQL ready state and owner scope as the authority for
retrieval, then inspect untrusted content again before generation. Store explainable
inspection reasons without source text in security audits. Scores are triage only.

Provide no LLM tools or side effects. Render user/model replies as plain text and
fetch preview images only through authorized API routes. This sacrifices Markdown
formatting to eliminate model-supplied tracking-image requests. Existing citation
membership checks remain mandatory but do not establish semantic faithfulness.

Use separate migration/API/worker DB roles and Qdrant read/write credentials in local
Compose. Worker does not receive the JWT signing secret. RLS is deferred until a
transaction-local tenant context and privileged worker policies can be designed and
tested; enabling it superficially would not improve an unsafe context propagation.

Evidence: native and PostgreSQL regression suites, live infrastructure probes,
synthetic adversarial results and their preserved failed baseline. Residual risks and
operational prerequisites are in docs/security/threat-model.md and local-hardening.md.
