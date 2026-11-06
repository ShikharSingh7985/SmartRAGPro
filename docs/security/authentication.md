# Authentication and session lifecycle

Passwords use Argon2id with library defaults and login-time rehashing. Emails are
trimmed and casefolded before validation/unique storage. Unknown, incorrect, disabled
and deleted accounts share a generic login failure and perform password verification.
Registration always returns the same 201/body for an existing or newly created email;
this reduces enumeration but does not guarantee identical timing. There is no email
verification or password-reset delivery in this phase.

Access JWTs require HS256 signature, issuer, audience, expiry, issued/not-before times,
UUID subject/JTI, access purpose and integer session version. Every protected request
loads the active account and checks its version. Existing pre-hardening JWTs lack the
purpose claim and require a fresh sign-in. JWT_SECRET must have at least 32 characters;
generate it with a cryptographic generator. Length is not an entropy proof.

Login returns access_token, refresh_token, expires_in and token_type. Refresh credentials
contain a UUID selector and 48 random bytes; PostgreSQL stores only SHA-256 of the
complete credential, owner, family, absolute expiry, consumed and revoked timestamps.
POST /api/v1/auth/refresh atomically consumes one credential and issues its successor
with the same absolute expiry (default 14 days). Mutations lock the user before the
token. A valid consumed credential signals reuse and revokes all that owner's refresh
credentials and access JWTs. A wrong secret cannot trigger revocation. Concurrent
refreshes are intentionally treated as reuse; clients must serialize rotation.

POST /auth/logout revokes all sessions. POST /auth/password requires current_password
and new_password, then rehashes/revokes all sessions; sign in again. Disabled/deleted
accounts cannot refresh. Expired refresh rows are removed by hourly dispatcher
maintenance; consumed rows remain until expiry to preserve reuse detection.

Streamlit holds credentials only in its server-side session, proactively refreshes
before access expiry and performs at most one refresh after 401. Uncertain refresh
outcomes require sign-in rather than retrying a consumed secret. A server/session
restart requires login; SQL conversations remain persistent. Forms clear password
fields after submit. No browser cookies, localStorage or URL tokens are introduced,
so no cookie-based CSRF flow is claimed. A compromised Streamlit server can read its
sessions; protect its host and WebSocket transport with TLS. Do not enable debug logs.

Login and registration have shared Redis limits by real peer IP and keyed normalized
email. Limits fail closed on Redis failure. Reverse proxies must supply a documented
trusted-peer configuration; the default Uvicorn command ignores forwarded headers.
Rate limits are abuse controls, not a defense against distributed credential stuffing.
