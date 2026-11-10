# Contributing

## Ownership

Edit only files you own. To change someone else's file, ask them first or open a PR that they review.

| Owner | Paths |
|-------|-------|
| **Armand** (A): API and containers | `api/` (except `orders.py`), `api/Dockerfile`, `worker/Dockerfile`, `compose.yaml`, `.dockerignore`, `tests/unit/test_validation.py`, `docs/threat-model.md`, `README.md` |
| **Tristan** (B): orders and CI | `api/orders.py`, `common/db.py`, `db/` (except `002_jobs.sql`), `scripts/reset_test_data.py`, `.github/workflows/`, `tests/conftest.py`, `tests/unit/test_orders.py`, `tests/integration/test_order_flow.py`, `tests/race/`, `docs/ADR-001.md` |
| **Mink** (C): worker and Kubernetes | `worker/` (except `Dockerfile`), `db/migrations/002_jobs.sql`, `infra/`, `scripts/kill_worker_demo.sh`, `scripts/poison_job.sh`, `scripts/measure_p95.py`, `tests/unit/test_worker.py`, `tests/integration/test_worker_recovery.py`, `docs/architecture.md`, `docs/slo.md`, `docs/incident-postmortem.md` |
| **All three** (every member reviews) | `common/contract.py`, `common/models.py`, `common/config.py`, `.env.example`, `pyproject.toml`, `requirements.txt`, `.gitignore` |

## Workflow

1. Branch from an up-to-date `main`: `git switch main && git pull && git switch -c <name>/<topic>`.
2. Keep PRs small and merge them at least daily. Long-lived branches are what cause conflicts.
3. Before opening or updating a PR, rebase it: `git fetch origin && git rebase origin/main`.
4. Change shared files (see table) in a separate small PR, reviewed by everyone.
5. Each PR needs at least one review. Each person reviews at least one PR from each of the other two.

## Conventions

- Python 3.11+. Run from the repo root: `python -m api.app`, `python -m worker.main`.
- Format and lint before committing: `ruff format . && ruff check --fix .`
- Runtime dependencies go in your component's `requirements.txt` with exact pins. Root `requirements.txt` is dev tooling.
- Env var names come from `common/config.py` and `.env.example`; contract values come from `common/contract.py`. Don't hard-code them elsewhere.
- Migrations: never edit one that is merged to `main`; add the next number. Say in the team chat which number you are taking.
- `docs/assistance-log.md` is append-only: add one row at the bottom.
- Never commit `.env` or real secrets. Destructive scripts and the public checker run only on the isolated test stack.
