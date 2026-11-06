# Authorization and tenant boundaries

JWT-verified identity is the only authority. Routes use owned SQL lookups and return
404 for foreign IDs; frontend state, filenames, vector payloads and graph state cannot
grant access. Documents/conversations have UUID owner foreign keys. Scope associations
are verified for each request against ready documents owned by that user. SQL ready
state/run versions revoke stale vector retrieval immediately, before physical cleanup.

Qdrant receives mandatory user/document/run filters before searching, followed by
payload/page validation and content policy. SQL BM25 statistics use the same scope.
Thread IDs are constructed from the verified owner's conversation UUID; no public
checkpoint read/write endpoint exists. The conversation is authorized/locked before
PostgresSaver loads state, and checkpoints/messages share the request transaction.

New uploads, conversation creation and retry requests lock/recheck the active owner
before document/scope locks. This serializes them with account deletion and prevents
an already-authenticated in-flight request from creating content after revocation.

Original PDFs and derived images stay in a private bucket. Only server-generated
owner/document keys are used; asset handlers authorize the document and asset and
check the canonical owner prefix. No raw bucket URLs or client-supplied storage paths
are accepted. Previews are worker-generated bounded PNG assets; the API no longer
parses an arbitrary PDF on each preview request. Older documents need authorized
reindexing to generate previews.

Workers are privileged cross-tenant processors: broker IDs load durable SQL jobs and
their document's owner. Inactive/deleting owners cannot ingest; cleanup can continue.
Advisory fencing/run tokens, retry state and owner-prefix checks protect duplicate
delivery and physical removal. These controls do not make a compromised worker a
tenant sandbox: it has cross-tenant document access. No per-PDF container is created.

Local bootstrap provisions smartrag_api and smartrag_worker without superuser,
createdb/createrole/bypassrls privileges or public-schema creation. API runtime has
application/checkpoint DML but no migration DML. Worker gets ingestion/search/asset
tables and only id/is_active/deleted_at from users; no password, session or checkpoint
tables. Migration credentials are present only in the bootstrap environment.
Qdrant's API credential is read-only; the worker/bootstrap credential can index.
Compose clears unused model/vector/object-storage secrets from the dispatcher runtime;
it needs PostgreSQL and Redis access for outbox/retention maintenance.

PostgreSQL RLS is not enabled: explicit ownership checks remain primary. Adding RLS
requires safe transaction-local tenant identity and separate worker policies; enabling
it without that design would break outbox and checkpoint operations. Local S3 uses a
bucket-wide service credential; a hosted installation should use distinct least-
privilege bucket IAM roles. Operator/host compromise remains outside tenant isolation.
