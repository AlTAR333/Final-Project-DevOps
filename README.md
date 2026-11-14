# FulfillOps

Resilient order-processing platform (EPITA DevOps capstone). Specification: [`docs/assignment/`](docs/assignment/).

## Layout

| Path | Contents |
|------|----------|
| `common/` | Contract constants, shared types, env config |
| `api/` | HTTP API (`python -m api.app`) |
| `worker/` | Background worker (`python -m worker.main`) |
| `db/` | SQL migrations and runner (`python -m db.migrate`) |
| `tests/` | `unit/`, `integration/`, `race/` |
| `scripts/` | Test-data reset, fault injection, p95 measurement |
| `infra/` | Kubernetes manifests (`k8s/`) and Argo CD (`argocd/`) |

## Install and run (Docker Compose)

Prerequisites: Docker with Compose v2 and `curl`. Python 3.13 is only needed to run the tests on
your own machine.

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` and set `POSTGRES_PASSWORD`. Use letters and digits only: the value is placed inside a
connection URL. `.env` is git-ignored, never commit it. Compose refuses to start if the password
is missing, so there is no default one.

### 2. Start everything

```bash
docker compose up -d --build --wait
docker compose ps
```

`--wait` returns once every service is healthy. Start order is enforced by health checks:

| Service | Role |
|---------|------|
| `db` | PostgreSQL 16, data in the named volume `pgdata` |
| `migrate` | Applies the migrations once, then exits with code 0 |
| `api-1`, `api-2` | Two API instances, ready when `/health/ready` returns 200 |
| `worker-1`, `worker-2` | Two workers claiming jobs from the database |
| `proxy` | nginx on `127.0.0.1:8080`, balancing between the two APIs |

### 3. Check that it works

```bash
curl -s localhost:8080/health/ready
curl -s localhost:8080/api/v1/catalog
curl -s -X POST localhost:8080/api/v1/orders \
  -H 'Idempotency-Key: demo-key-0001' -H 'Content-Type: application/json' \
  -d '{"customer_id":"CUST-1","items":[{"sku":"KIT-100","quantity":1}]}'
curl -s localhost:8080/metrics | head
```

### 4. Run the public checker (needs a freshly seeded database)

```bash
docker compose down -v && docker compose up -d --build --wait
python fulfillops_public_checker.py --base-url http://localhost:8080 --concurrency --stress
```

### 5. Run the tests

Unit tests need no database:

```bash
pip install -r requirements.txt
python -m pytest tests/unit -q
```

Integration and race tests need PostgreSQL. The Compose database is published on `127.0.0.1:5432`:

```bash
docker compose up -d db
export APP_ENV=test
export DATABASE_URL=postgresql://fulfillops:<your password>@localhost:5432/fulfillops_test
python -m db.migrate
python -m pytest -q
```

The test fixtures refuse to touch any database unless `APP_ENV=test` and its name contains `test`.

Red-to-green demonstration for the API (plants an off-by-one bug, shows the test failing, repairs it):

```bash
bash scripts/red_to_green_api.sh
```

### 6. Stop and clean up (teardown)

```bash
docker compose down        # stops and removes the containers, KEEPS the data volume
docker compose down -v     # also deletes the volume: all orders and stock changes are lost
docker compose down -v --rmi local   # additionally removes the images built here
```

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `set POSTGRES_PASSWORD in .env` | Create `.env` from `.env.example` (step 1) |
| Port 8080 already used | Set `API_PORT=8081` (or another free port) in `.env` |
| Changed the password after the first start, the services cannot connect | PostgreSQL only reads the password when the volume is created: run `docker compose down -v` and start again |
| An API container was recreated and the proxy returns 502 | `docker compose restart proxy` (nginx resolves the API addresses at startup) |
| Something is unhealthy | `docker compose logs <service>`, for example `docker compose logs api-1` |

Kubernetes and Argo CD instructions are in `infra/`.

## Individual contributions

### Armand: API and containers

- **Implemented:** request validation with every contract error code and the 16 KiB body limit
  (`api/validation.py`); catalog and inventory reads, liveness and readiness checks, and the
  `/metrics` endpoint with request counters and a latency histogram (`api/catalog.py`,
  `api/health.py`, `api/metrics.py`); the Flask application, routes and safe JSON error handling
  (`api/app.py`); the multistage non-root Dockerfiles for the API and the worker; `compose.yaml`
  with the nginx proxy; `.env.example`; the API unit tests and the planted-bug red-to-green test
  (`scripts/red_to_green_api.sh`); the threat model (`docs/threat-model.md`).
- **Reviewed:** TODO(Armand): list the pull requests you reviewed.
- **Would improve next:** connection pooling (today each request opens its own connection);
  authentication and rate limiting; pin base images by digest and scan on a schedule; aggregate
  request metrics across replicas with Prometheus.
- **AI assistance:** logged in [`docs/assistance-log.md`](docs/assistance-log.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
