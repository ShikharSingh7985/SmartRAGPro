# Content poisoning defenses

Policy content-2026-11-v3 is an explainable triage heuristic. Scores are sums of reason
weights capped at 100, not probabilities or proof of maliciousness. The default block
threshold is 80. Single weak indicators enter review and remain usable; explicit
educational quotations and negative statements avoid automatic phrase-based rejection.
Attackers may exploit these exceptions; deterministic authorization and capabilities
remain mandatory for every decision.

Layer A inspects raw embedded text, extracted/OCR/table/figure content and PDF metadata.
Unicode normalization/control removal and bounded single-layer base64/hex/ROT13 checks
identify some obfuscation. Active PDF objects are rejected separately. Hard-blocked
pages/chunks are not embedded; all-blocked documents fail instead of becoming ready.
Original content stays private for owner review/deletion. Model-derived captions remain
untrusted. Inspection rows contain only object IDs, policy version, reason codes,
decision and score. GET /documents/{id}/security is owner authorized.

Layer B re-inspects retrieved text and headings, including legacy vectors, without
trusting stored safety labels. Concurrent inspection writes use SQL upserts. High-risk
content is excluded before evidence selection or Gemini. Mandatory owner/scope/run/page
checks apply independently. Review is a triage state, not a safety endorsement.

Layer C labels source and conversation data as untrusted, bounds context, gives the
model no tools, and verifies citation membership in authorized selected evidence.
Output checks reject active images/HTML, recognizable credential leakage and requests
to send secrets to external URLs. Streamlit renders model/user text as plain text;
source images are explicitly fetched through authenticated endpoints. Citation markers
do not prove semantic faithfulness; forged facts with valid citation numbers remain a
known risk requiring human/quality evaluation.

History, recalled turns, old synopses, active topics and answer-reference maps are
re-inspected before reconstruction/rewrite. Unsafe input cannot mutate selected
document IDs or security state. Summaries are reference aids, never PDF evidence.
Durable raw messages remain owner-controlled records until deletion, but identified
poison is excluded from reconstructed context. Checkpoint state is overwritten with
server-authorized scope and sanitized state at every invocation; no tools read arbitrary
checkpoint instructions. Authentication is not part of the graph.

Rules cover a bounded set of patterns. They do not solve multilingual attacks,
steganography, deep recursive encodings, colluding documents, factual poisoning or
model training attacks. Never interpret the synthetic regression pass rate as a
percentage of real attacks blocked. Live model tests are separately recorded.
