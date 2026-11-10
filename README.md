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

## Install and run

TODO(Armand)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
