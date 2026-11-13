#!/usr/bin/env bash
# Owner: Mink. Install a pinned Argo CD release into the kind cluster.
set -euo pipefail

ARGOCD_VERSION="${ARGOCD_VERSION:-v3.5.7}"
CTX="kind-${CLUSTER:-fulfillops}"  # never touch any other cluster
k() { kubectl --context "$CTX" "$@"; }

k create namespace argocd --dry-run=client -o yaml | k apply -f -
k apply -n argocd --server-side --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

k -n argocd rollout status deploy/argocd-repo-server --timeout=300s
k -n argocd rollout status deploy/argocd-server --timeout=300s
k -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
echo "Argo CD ${ARGOCD_VERSION} is running in namespace argocd (context ${CTX})."
