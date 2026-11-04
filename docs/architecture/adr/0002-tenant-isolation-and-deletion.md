# ADR 0002: Server-owned resources and compensating deletion

Accepted. JWT identity scopes every SQL resource lookup. Qdrant queries require both
tenant ID and server-authorized ready document IDs. Storage keys use tenant/UUID,
never filenames. Deletion immediately removes derived conversation content, blocks
retrieval and queues retryable physical cleanup. Pending upload records allow
compensation after external write failures or process crashes.

Consequence: deleting one document removes a multi-document conversation in full.
This deliberate privacy-first behavior is disclosed by the UI.
