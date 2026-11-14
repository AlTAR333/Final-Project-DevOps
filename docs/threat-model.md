# Threat model

Owner: Armand

Scope: the FulfillOps order API, the worker, PostgreSQL, their container images, the Compose
stack, the Kubernetes manifests and the CI pipeline. Method: list what an attacker (or a plain
failure) could do to each part, then record the control that stops it and where it is proven.

## Assets and trust boundaries

| Asset | Why it matters |
|-------|----------------|
| Stock levels and orders in PostgreSQL | Overselling or losing an order is the core business failure |
| Database credentials | Full read/write access to all of the above |
| Customer identifiers in order payloads | Personal data that must not leak |
| Container images and CI pipeline | What actually runs in production |

```text
 untrusted client ──► [ proxy / Service ] ──► API (stateless) ──► PostgreSQL ◄── worker
                       boundary 1              boundary 2          boundary 3
 boundary 1: everything from the network is untrusted input
 boundary 2: the API is the only component that talks to clients; it validates before any database call
 boundary 3: the database is never published beyond 127.0.0.1 (Compose) or the cluster network
```

## Threats

Likelihood and impact use Low / Medium / High. "Residual" is what is still open after the control.

| ID | Threat (category) | Impact | Mitigation | Evidence | Residual |
|----|-------------------|--------|------------|----------|----------|
| T1 | **Overselling or negative stock** under concurrent orders (tampering with business data) | High: customers are promised stock that does not exist | One transaction per order. Stock is reserved with `UPDATE ... WHERE available >= qty`. `CHECK (available >= 0)` as last line of defence. SKUs locked in sorted order to avoid deadlocks (ADR-001) | `tests/race/test_distinct_keys.py` (12 and 30 competing requests); public checker `--concurrency --stress` | Low |
| T2 | **Duplicate orders** from client retries or two replicas receiving the same request (repudiation, integrity) | High: double charge, double shipment | `Idempotency-Key` is mandatory (`api/validation.py`). `UNIQUE (idempotency_key)` with `ON CONFLICT DO NOTHING` makes the database the arbiter across all replicas. Same key with a different payload is refused with 409 | `tests/race/test_same_key.py`; unit tests for the key rules | Low |
| T3 | **Oversized or malformed request body** used to exhaust memory or CPU (denial of service) | Medium: API slow or down | 16 KiB limit enforced by reading at most limit + 1 byte; strict ordered validation before any database call; 1 MiB hard cap in Waitress and nginx; deeply nested JSON and `NaN` rejected cleanly | `tests/unit/test_validation.py`, `tests/unit/test_app.py` (413 JSON body) | Medium: no rate limiting and no per-client quota |
| T4 | **SQL injection** through SKU, order id or customer id (tampering, information disclosure) | High: data theft or destruction | Every query uses bound parameters; no SQL is built from input. SKUs are checked against a fixed allow-list before reaching the database | `tests/unit/test_catalog.py` (injection string is bound, not interpolated); code search finds no formatted SQL | Low |
| T5 | **Secrets committed to Git, baked into images or printed in logs** (information disclosure) | High: database takeover | `.env` is git-ignored and `.dockerignore`d; only `.env.example` with placeholders is committed. Compose refuses to start when `POSTGRES_PASSWORD` is missing (`${VAR:?}`), so there is no default password. Kubernetes reads credentials via `secretKeyRef`; only `secret.example.yaml` is committed. The CI database password is a throwaway. Logs record method, route template, status and duration only: never headers, bodies, keys or customer ids | `.gitignore`, `compose.yaml`, `infra/k8s/base/`, `docs/ci.md` | Medium: no automated secret scanner in CI |
| T6 | **Compromised container escalates privileges** (elevation of privilege) | High: attacker controls the host or neighbours | Non-root numeric user 10001; read-only root filesystem; all Linux capabilities dropped; `no-new-privileges` (Compose) and `allowPrivilegeEscalation: false` (Kubernetes); service-account token not mounted; memory and CPU limits | `compose.yaml` (`x-hardening`), `infra/k8s/base/*-deployment.yaml`; `docker compose exec api-1 id` shows uid 10001 | Low |
| T7 | **Information leaked through errors, logs or metrics** (information disclosure) | Medium: stack traces or personal data exposed | Error messages are fixed strings that never echo input. Any unexpected exception becomes a generic 500 `INTERNAL_ERROR`; the traceback stays in the server log. Metric labels use the route template, never real ids, which also bounds label cardinality. `nosniff` and `no-store` headers on every response | `tests/unit/test_app.py` (safe 500, no secret in body, route-template labels) | Low |
| T8 | **Vulnerable dependency or tampered image** (supply chain) | High: remote code execution inside the app | Exact version pins; Trivy scan blocks fixable HIGH/CRITICAL findings; SBOM per image stored as a CI artifact; images tagged with the commit SHA, never `latest`; pip removed from runtime images; third-party actions pinned | `docs/ci.md`. The gate already caught pip and Waitress, which were fixed (Waitress 3.0.2) | Medium: unfixed CVEs are reported but not blocking; base images are pinned by tag, not by digest |
| T9 | **Poison job or crashed worker** leaves an order stuck or processed twice (denial of service, integrity) | Medium: orders never complete, or inventory is wrongly restored | Jobs are claimed with `SKIP LOCKED` plus a lease, so a dead worker's job is reclaimed. Completion is a no-op if it runs twice. Failures use backoff and an attempt counter; after the last attempt the job is dead-lettered and the order marked failed, with no restock | `tests/integration/test_worker_recovery.py`, `tests/unit/test_worker.py`, `scripts/kill_worker_demo.sh`, `scripts/poison_job.sh` | Low |
| T10 | **Test-data reset run against real data** (tampering) | High: production stock wiped | `scripts/reset_test_data.py` refuses unless `APP_ENV=test` **and** the database name contains `test`. The test fixtures use the same guard | `check_safe` in the script; `tests/conftest.py` | Low |
| T11 | **Database reachable from outside the host** (spoofing, information disclosure) | High | Compose publishes PostgreSQL only on `127.0.0.1`; the APIs and workers are not published at all; only the proxy exposes port 8080, also on `127.0.0.1` | `compose.yaml` ports | Low |
| T12 | **Unauthenticated API** lets anyone place orders or read inventory (spoofing) | Medium | None, by design: the contract defines public endpoints and no credentials. Accepted risk for this assignment | `docs/assignment/API_CONTRACT_EN.md` | **Accepted**: add authentication and rate limiting before any real deployment |

## Accepted risks and next steps

- **T12 and the T3 residual:** the first improvement for a real deployment is authentication plus
  rate limiting at the proxy.
- **T5 residual:** add a secret scanner (for example gitleaks) as a CI job.
- **T8 residual:** pin base images by digest and run the scan on a schedule, so new CVEs in old
  images are noticed without a push.
- Request metrics (counter and histogram) are per instance; business counters are read from the
  database. This is an observability limit, not a security one.
