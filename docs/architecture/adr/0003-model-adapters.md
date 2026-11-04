# ADR 0003: LangChain adapters with real Gemini and configurable embeddings

Accepted. LangChain Google generation and embedding adapters are used directly,
along with its recursive text splitter. Google embeddings default to configurable
`gemini-embedding-001`, 768 dimensions. OpenAI embeddings are an optional selectable
provider. Gemini generation remains mandatory. Do not switch embedding models on an
existing vector collection. Deterministic doubles are confined to `tests/`.

LangGraph is deferred to Phase 3; a graph adds no value to a single retrieval/generation
step. Question history is durable but not used for query rewriting in Phase 1.
Citation numbers and provenance are validated; semantic entailment needs later evals.

Generation defaults to stable `gemini-3.8-flash`, verified against Google's model
deprecation page on 2026-11-04; 2.5 Flash is deprecated and limited to existing users.
Account-level availability still requires a live credentialed probe.

References: [Google embeddings](https://ai.google.dev/gemini-api/docs/embeddings),
[Google model lifecycle](https://ai.google.dev/gemini-api/docs/deprecations),
[LangChain adapter](https://reference.langchain.com/python/langchain-google-genai/embeddings/GoogleGenerativeAIEmbeddings),
[Qdrant multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/).
