# Deployment guide

No public cloud deployment is performed by the local release scripts. Choose a host,
region, budget, domain and backup destination before provisioning. OCR workers need
long-running processes, native dependencies, model-cache storage and adequate RAM;
do not assume a small free web tier supports this image or background workload.

A practical first topology is a paid Linux VM with Docker Compose, a persistent
encrypted data disk and private infrastructure ports, plus an HTTPS reverse proxy.
Start capacity planning at 4 vCPU/16 GiB when running OCR and monitoring together;
this is a provisioning suggestion, not a measured capacity guarantee. Alternatively,
run API/frontend and worker separately with managed PostgreSQL, Redis, Qdrant and S3.
Use private TLS-enabled service endpoints and least-privilege accounts. Persistent
volumes or managed services are required; ephemeral container storage is insufficient.

1. Install supported Docker Engine/Compose on the host and restrict SSH access.
2. Clone the authorized repository and select a reviewed commit. Keep secrets outside
   Git; use a secret manager or root-readable local environment configuration.
3. Configure Gemini and embedding provider/model/dimensions, storage and database
   credentials. Usage can incur provider charges; free quotas are account/model
   dependent. Preserve embedding-space compatibility or reindex into a fresh collection.
4. Run configure_local only for a fresh local-style installation, then configure_security
   to generate role-specific environments. For managed databases provision equivalent
   roles through a reviewed administrative migration step; local helper assumptions
   must not overwrite managed connection settings. Keep the migration role out of API.
5. Build API, frontend and worker targets. Bootstrap applies migrations/checkpointer
   schema, creates storage/vector resources and configures local least-privilege roles.
   Use an explicit release job for managed services rather than every replica running DDL.
6. Put an authenticated-network reverse proxy on the host in front of loopback ports
   8501 and 8000. Configure certificates for the domain and route WebSockets to Streamlit.
   Deny public `/metrics`, operational dashboards and API documentation as appropriate.
   Keep PostgreSQL, Redis, Qdrant, S3, collector and Tempo ports unpublished.
7. For HTTPS scheme enforcement, use TLS directly in Uvicorn with mounted certificates,
   or explicitly configure proxy-header trust for the exact ingress IP. The supplied
   local command uses `--no-proxy-headers`; do not enable `REQUIRE_HTTPS=true` behind
   an unconfigured HTTP hop. Configure `ALLOWED_HOSTS`, CORS and Streamlit's API URL
   consistently, then validate redirects, certificate trust and request limits.
8. Start the stack with persistent volumes and resource limits. Verify readiness,
   worker heartbeats, migrations, synthetic end-to-end workflows, restart recovery,
   access isolation and private telemetry through the actual HTTPS endpoint.
9. Configure encrypted off-host PostgreSQL/object/vector backups, restore drills,
   retention, disk monitoring, Alertmanager notifications and on-call ownership.
10. Record image digests, release commit, endpoint and rollback procedure. Rollback
    code only after checking migration compatibility; never blindly downgrade a live DB.

The local Compose configuration is reproducible deployment input, not a verified public
TLS installation or managed-service credential provisioner. Platform-specific changes
and the live endpoint must be tested after the operator supplies the destination.
Hosted Langfuse is optional, disabled by default and requires separate export consent.
GitHub Actions builds/checks code without cloud credentials; deployment is deliberately
not automatic. Use GitHub Secrets or workload identity for any future release job.

Costs include VM/RAM, durable disks, backups, egress, embeddings, Gemini generation,
optional vision and hosted tracing. Price configuration is operator-supplied; no
unverified dollar estimate is presented. Start with low concurrency and measured quotas.

## Concrete Linux VM ingress example

`ops/deployment/Caddyfile` is for a host-managed Caddy service; it proxies only to
the existing loopback-published ports, supports Streamlit WebSockets and denies
public monitoring/docs/readiness endpoints. Install Caddy using its supported host
package, copy the file to `/etc/caddy/Caddyfile`, and configure `PUBLIC_DOMAIN` and
`API_DOMAIN` in its systemd service environment. Point both DNS records at the VM,
allow only 80/443 plus restricted administrative access, validate the configuration
and reload Caddy. Certificate issuance requires working public DNS/network access.

The optional `docker-compose.production.yml` enables HTTPS enforcement, explicit
proxy-header trust and a 240-second API drain grace. On a standard Linux Compose
bridge, inspect its gateway with `docker network inspect smartragpro_default` to
identify the host peer. Set `TRUSTED_PROXY_IP` to the actual proxy peer seen by API,
never `*`; validate the topology before Internet exposure. Set `API_DOMAIN` locally
to the same API hostname as Caddy, then start:

```sh
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

Add the observability overlay when desired. Keep generated role envs private and
rerun configure_security after secret/settings changes. Streamlit reaches the API
through its HTTPS hostname in this topology; do not replace that URL with an internal
HTTP hop while `REQUIRE_HTTPS=true`. Verify API scheme enforcement, `/health/live`,
authentication, browser chat and WebSockets on the actual domain before release.
The example receives syntax validation only locally; public DNS, certificates and
this Linux-host proxy topology remain NOT VERIFIED without a deployment destination.

References: [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[Caddy environment substitution](https://caddyserver.com/docs/caddyfile/concepts#environment-variables).
