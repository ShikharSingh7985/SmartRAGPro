# ADR 0006: Transactional LangGraph conversations

Accepted for Phase 3, 2026-11-06.

Use a deterministic LangGraph inside the modular monolith. The installed locked
versions are LangGraph 1.2.20 and checkpoint-postgres 3.2.0. API authorization occurs
before any checkpoint access. Thread keys are server-generated
`user:{owner UUID}:conversation:{conversation UUID}`; clients cannot supply threads.

The official PostgresSaver shares the SQLAlchemy session's psycopg connection.
`durability="exit"` avoids concurrent node-level checkpoint transactions. Messages,
topic/references, synopsis, final graph checkpoint and pruning commit together.
On error, the request transaction rolls back. An interrupted uncommitted turn is
retried from the beginning with the same request UUID; there is no partial user turn.
If the response is lost after commit, the same UUID returns the saved answer.
Do not promise mid-generation resumption. This is deliberate atomic turn recovery.

PostgreSQL NOWAIT conversation row locks serialize same-conversation mutations;
contention returns 409. Ready document SHARE locks allow independent conversations
to read a book concurrently while preventing source deletion during publication.
Document deletion takes conversation locks before document locks, clears all derived
history/checkpoints and preserves the shell and remaining scope associations.

Initialize library-owned checkpoint tables using `PostgresSaver.setup()` on an
autocommit connection during `python -m scripts.bootstrap`. Alembic owns application
tables and the PostgreSQL full-text message index. Setup is idempotent; do it before
starting API replicas. Back up both sets of tables. There is no production memory or
SQLite fallback. Isolated lightweight tests explicitly inject a file-backed official
SQLiteSaver, which does not demonstrate PostgreSQL transaction atomicity or locking.
The dedicated service suite checks those properties against PostgreSQL.

SQL messages are the complete user-visible record. Every invocation reconstructs
bounded context from SQL, rather than trusting checkpoint scope or replaying an
unbounded message channel. Summaries are incremental extractive snippets with covered
positions, a high-water mark and provenance; older snippets may be evicted. Complete
older messages remain searchable through PostgreSQL FTS and can be exported. No
additional summarization model call is required. Scope changes increment a version
and prevent previous-scope history from entering new prompts.

Question rewriting resolves common pronouns, numbered methods and explicit distant
references deterministically. Unknown referents ask for clarification. Optional
`CHAT_LLM_REWRITE=true` uses structured Gemini output for follow-ups only, with a
separate optional model setting and bounded context. This incurs provider costs.
Standalone questions never require a rewrite model call.

Memory is untrusted linguistic context, never PDF evidence. Retrieve only selected,
ready, owned, active-run document vectors; check payload provenance, page bounds and
citation indices. Source-number validation cannot prove semantic entailment; Phase 5
evaluates that separately. General-knowledge answers are deliberately not enabled.

Keep one latest graph checkpoint per thread with transaction-local retention SQL.
The real PostgreSQL test exposed that the installed saver `prune(keep_latest)` starts
REPEATABLE READ and fails inside an already active ORM transaction. Therefore use
the existing owned conversation row lock to exclude concurrent same-thread writers,
delete obsolete checkpoint rows/blobs/writes and clear the retained parent pointer
inside the same transaction. The official saver still handles serialization, reads,
writes and deletion. This narrow retention adapter is for our scalar StateGraph only:
no DeltaChannels, pending interrupts or graph forking. Revalidate it against real
PostgreSQL when upgrading the checkpoint library. Do not call the library prune API
inside a request transaction or weaken atomicity to work around its isolation change.
Clear transient history/evidence at exit and disable LangSmith tracing explicitly.
Store only timings, budgets and flags in turn telemetry. Raw query DEBUG logs require
both development mode and explicit local opt-in. No provider exception text is returned.

Sources checked against installed implementations and official documentation:
[PostgresSaver](https://reference.langchain.com/python/langgraph.checkpoint.postgres/PostgresSaver),
[persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
