# CI/CD pipeline and quality gates

Owner: Tristan

Workflow: `.github/workflows/ci.yml`. Runs on every pull request to `main` and on every push to `main`.

## Stages

| Job | Runs | Blocks merge / release when |
|-----|------|-----------------------------|
| `lint` | `ruff check`, `ruff format --check` | any lint or formatting error |
| `test` | migrations + unit, integration and race tests against a throwaway PostgreSQL 16 service; JUnit report uploaded | any test fails |
| `contract` | `docker compose up`, then `fulfillops_public_checker.py --concurrency --stress` on the fresh stack; output and logs uploaded | any public check fails or is skipped |
| `build-scan` | builds the API and worker images, generates an SPDX SBOM per image (Syft), runs Trivy | the blocking scan finds a fixable HIGH or CRITICAL vulnerability |
| `publish` | `main` only, after everything above passes: pushes `ghcr.io/<repo>/<component>:<commit-sha>` and records the digest in the run summary | never runs if any earlier job failed |

## Vulnerability policy

- **Blocking:** HIGH or CRITICAL findings that have a fixed version available (`--ignore-unfixed`). These fail the build; fix by upgrading the base image or dependency.
- **Informational:** everything else (LOW, MEDIUM, and HIGH/CRITICAL with no fix yet). Reported in `trivy-<component>.txt`, reviewed but not blocking, because there is nothing actionable to upgrade to.
- A blocking finding may only be waived with a `.trivyignore` entry that names the CVE, the reason and a review date, merged through a reviewed PR.

## Supply chain

- Every image is tagged with the full commit SHA; tags are never reused or overwritten (`latest` is not used).
- SBOMs (`sbom-api.spdx.json`, `sbom-worker.spdx.json`) are stored as CI artifacts for every run.
- Third-party actions are pinned to release tags; scanner images are pinned to exact versions.
- The workflow has `contents: read` by default; only `publish` gets `packages: write`, and it uses the short-lived `GITHUB_TOKEN`, not a stored secret.
- The test database password is a CI-only throwaway value, not a real credential.

## Red-to-green evidence

1. Branch `demo/red`: remove `AND available >= %s` from the stock `UPDATE` in `api/orders.py`. The race tests fail (stock oversold / negative stock rejected by the CHECK constraint). PR shows a red `test` job and `publish` never runs.
2. Restore the condition and push. All jobs go green; on merge, `publish` pushes the SHA-tagged images.

Links to both runs: _add after running_.
