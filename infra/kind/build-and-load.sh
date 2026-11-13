#!/usr/bin/env bash
# Owner: Mink. Build both images tagged with the current commit SHA, load them into the kind
# cluster, and point kustomization.yaml at that tag. Commit the kustomization change to
# release it: Argo CD deploys whatever tag Git says.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
CLUSTER="${CLUSTER:-fulfillops}"
KUSTOMIZATION=infra/k8s/base/kustomization.yaml

if [[ -n "$(git status --porcelain -- . ":(exclude)$KUSTOMIZATION")" ]]; then
  echo "Working tree has uncommitted changes: the image would not match the commit SHA." >&2
  echo "Commit or stash them first." >&2
  exit 1
fi
TAG="$(git rev-parse --short=12 HEAD)"

docker build -f api/Dockerfile -t "fulfillops-api:$TAG" .
docker build -f worker/Dockerfile -t "fulfillops-worker:$TAG" .
kind load docker-image "fulfillops-api:$TAG" "fulfillops-worker:$TAG" --name "$CLUSTER"

sed -i.bak -E "s/^([[:space:]]*newTag:).*/\1 \"$TAG\"/" "$KUSTOMIZATION"
rm -f "$KUSTOMIZATION.bak"

echo "Loaded fulfillops-api:$TAG and fulfillops-worker:$TAG into kind cluster '$CLUSTER'."
echo "Release it: git add $KUSTOMIZATION && git commit -m \"deploy: images $TAG\" && git push"
