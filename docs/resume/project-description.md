# SmartRAG Pro — Persistent document-grounded AI assistant

Python 3.12 · FastAPI · Streamlit · LangGraph · Gemini · PostgreSQL/SQLAlchemy/Alembic ·
Qdrant · Redis/Dramatiq · S3 · Docling/PyMuPDF/Tesseract · OpenTelemetry · Prometheus ·
Grafana · Docker · GitHub Actions

- Built a multi-user conversational RAG application with transactional PostgreSQL
  messages/checkpoints, document-scoped retrieval, source citations and durable
  asynchronous PDF ingestion across text, OCR, tables and figure assets.
- Implemented rotating refresh sessions, tenant authorization, private storage,
  bounded processing and layered content-policy enforcement, validated through
  deterministic adversarial tests and real-service integration workflows.
- Added privacy-preserving distributed tracing, operational dashboards, recoverable
  cleanup and backup/restore tooling; benchmarked 1–25 synthetic concurrent clients
  against real infrastructure with explicitly isolated test providers.

SmartRAG Pro integrates a modular monolith and independent ingestion worker rather
than disconnected demos. SQL leases and fencing coordinate Redis-delivered jobs;
structured page provenance connects extracted text, tables and figures to verified
citations. A deterministic LangGraph reconstructs finite conversational context from
durable history, summaries and recalled turns while keeping PDF evidence authoritative.
Dense, BM25, rank-fusion and bounded reranking configurations share an evaluation
framework with fixed synthetic labels and recorded regressions. Dense remains the
default because the measured synthetic comparison did not justify replacing it.

Content-free telemetry spans API, database, worker, retrieval and generation stages.
Bounded export queues isolate monitoring outages. Hosted tracing is opt-in; no source
text or tokens are exported as trace payloads. Container builds use non-root processes
and private infrastructure services. The release checklist explicitly distinguishes
local verification from pending cloud deployment and independently reviewed quality.

Quantitative results and limitations are in the [measured engineering report](../benchmarks/final-report.md).
Synthetic retrieval scores and simulated-model load results must retain those qualifiers
when used in a resume; they are not independently reviewed production accuracy or scale.

Repository: [ShikharSingh7985/SmartRAGPro](https://github.com/ShikharSingh7985/SmartRAGPro).
