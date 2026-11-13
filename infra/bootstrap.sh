#!/usr/bin/env bash
# Owner: Mink. One-time lab setup: kind cluster -> Argo CD -> DB Secret -> Application.
# TARGET_REVISION=<branch> infra/bootstrap.sh points Argo CD at a branch instead of main.
# Safe to re-run. The Secret is created only if missing (Postgres keeps its first password)
# and its value is never printed or written to disk.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
CLUSTER="${CLUSTER:-fulfillops}"
CTX="kind-$CLUSTER"
k() { kubectl --context "$CTX" "$@"; }

if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --config infra/kind/cluster.yaml --wait 120s
fi

CLUSTER="$CLUSTER" infra/argocd/install.sh

k apply -f infra/k8s/base/namespace.yaml
if ! k -n fulfillops get secret fulfillops-db >/dev/null 2>&1; then
  pw="$(openssl rand -hex 16)"
  k -n fulfillops create secret generic fulfillops-db \
    --from-literal=POSTGRES_PASSWORD="$pw" \
    --from-literal=DATABASE_URL="postgresql://fulfillops:${pw}@fulfillops-db:5432/fulfillops" \
    >/dev/null
  unset pw
  echo "Created Secret fulfillops/fulfillops-db with a generated password."
fi

k apply -f infra/argocd/application.yaml
if [[ -n "${TARGET_REVISION:-}" ]]; then  # try an unmerged branch; re-run without it to go back
  k -n argocd patch application fulfillops --type merge \
    -p "{\"spec\":{\"source\":{\"targetRevision\":\"$TARGET_REVISION\"}}}"
fi
echo "Application applied. Images must exist in kind: run infra/kind/build-and-load.sh,"
echo "commit the new tag, then watch: kubectl --context $CTX -n argocd get application fulfillops"
