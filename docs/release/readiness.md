# Release-readiness checklist

This is a local release candidate, not a claim of public production deployment.
PASS means the described scope was executed; NOT VERIFIED is an open gate.
Machine-readable evidence is under `evaluation/release/`; earlier adversarial model
failures remain in `evaluation/security/` rather than being deleted.

| Requirement | Status | Evidence / limit |
|---|---|---|
| Register/login/upload/cited answer | PASS | Real HTTP/provider synthetic acceptance |
| Ownership, JWT and refresh lifecycle | PASS | Native + real-service security tests; live security rerun recorded separately |
| PostgreSQL migrations and schema drift | PASS | Full service suite, migration round trip |
| Persistent checkpoint/history restoration | PASS | PostgreSQL deterministic tests; live API restart restores history |
| Four live contextual turns after restart | PASS | Expected method and page verified for all four turns; prose/description/stale-list fixes; earlier failures preserved |
| Text/scans/tables/figure assets | PASS | Synthetic mixed PDF: table and figure-label questions with real citations |
| Advanced image interpretation/OCR accuracy on real research corpus | NOT VERIFIED | OCR-visible synthetic labels do not prove advanced vision |
| Scoped dense/BM25/hybrid/reranking evaluated | PASS | Fixed synthetic corpus and held-out labels; dense retained |
| Independent human-reviewed answer faithfulness | NOT VERIFIED | Deterministic answer/citation proxies only |
| Prompt-injection enforcement | PASS | 32 deterministic policy cases; live mixed-poison normal question |
| General prompt-injection immunity | NOT VERIFIED | Not a finite-suite guarantee; heuristics have residual risk |
| Local OTel, private OTLP delivery and correlated logs | PASS | Export-failure/privacy tests; traces reach Tempo |
| Prometheus targets and Grafana dashboard | PASS | Three healthy scrape targets; provisioned dashboard API |
| Hosted Langfuse delivery | NOT VERIFIED | Disabled; endpoint credentials and export consent required |
| Non-root API/worker/frontend builds and startup | PASS | Actual Compose build and health checks |
| Local PostgreSQL backup and restore | PASS | Checksum and restored canary in disposable smartrag_test |
| Full off-host SQL/S3/Qdrant restore with RPO/RTO | NOT VERIFIED | Operator backup destination and drill needed |
| Finite retries, timeout handling and cleanup recovery | PASS | Provider/Redis/recovery tests; failed cleanup stays inaccessible |
| 1/5/10/25 synthetic concurrent clients | PASS | Four load cases, isolated models, real disposable services |
| Real-provider concurrent capacity / quota validation | NOT VERIFIED | No budget-approved Gemini load performed |
| Formatting/static/type checks | PASS | Ruff and mypy; final commands recorded in release notes |
| Dependency/secret scanning | PASS | Installed advisory scan and staged-source review; no universal absence guarantee |
| Expanded GitHub Actions execution | PASS | Source 88f43de passed both jobs in run 42342857874, including container integration and proxy validation |
| Final source pushed and verified | PASS | origin/main independently matched 88f43dec3e5d46b38d957e81e502678d3f6f9d11; subsequent documentation records this milestone |
| Public HTTPS deployment | NOT VERIFIED | No hosting destination/domain/budget configured |
| Host proxy / production Compose syntax | PASS | Caddy 2.11.9 network-isolated validation and Compose config check; no certificate issued |
| Browser-driven Streamlit interaction | NOT VERIFIED | Frontend container health verified; acceptance exercises its authenticated REST backend |
| Production alert notifications | NOT VERIFIED | Prometheus rules supplied; receiver/on-call setup pending |
| v1.0.0 tag | NOT VERIFIED | Withheld while release gates remain open |

Production next actions: select hosting and region/budget, configure TLS/secret
management, provision durable private services and encrypted backup destination,
route alert notifications, execute full restore and target-host acceptance, review
representative relevance/answer labels, then reconsider the production version tag.
