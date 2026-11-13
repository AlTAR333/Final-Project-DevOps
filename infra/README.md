# Kubernetes and GitOps runbook

Owner: Mink. Local lab only: a kind cluster named `fulfillops`, reconciled by Argo CD from
`infra/k8s/base` on `main` of https://github.com/AlTAR333/Final-Project-DevOps (public, so
Argo CD needs no repository credentials).

Tested with kind v0.33.0, kubectl v1.36, Argo CD v3.5.7.

## Layout

| Path | What |
|------|------|
| `kind/cluster.yaml` | Cluster config; maps `localhost:8080` to the API NodePort 30080 |
| `kind/build-and-load.sh` | Builds both images tagged with the commit SHA, `kind load`s them, sets the tag in Git |
| `argocd/install.sh` | Installs the pinned Argo CD release |
| `argocd/application.yaml` | The Argo CD Application (auto-sync, prune, self-heal) |
| `bootstrap.sh` | Cluster, Argo CD, DB Secret and Application in one re-runnable step |
| `k8s/base/` | Namespace, ConfigMap, Postgres + PVC, migrate Job, 2 API + 2 worker Deployments, Service |

## Fresh install

Stop the compose stack first (`docker compose down`): both use host port 8080.

```bash
infra/bootstrap.sh             # kind cluster + Argo CD + Secret + Application
infra/kind/build-and-load.sh   # needs a clean working tree; prints the commit to make
git add infra/k8s/base/kustomization.yaml && git commit -m "deploy: images <sha>"
# merge to main; Argo CD syncs within ~3 minutes (or click Refresh in the UI)

kubectl --context kind-fulfillops -n argocd get application fulfillops   # Synced / Healthy
kubectl --context kind-fulfillops -n fulfillops get pods                 # 2 api, 2 worker, db
curl -s localhost:8080/health/ready
```

`kubectl -n fulfillops port-forward svc/fulfillops-api 8080:80` also works, but it attaches to
a single pod and drops when that pod is replaced, so the rolling-update probe uses the
NodePort mapping above instead.

Argo CD UI: `kubectl -n argocd port-forward svc/argocd-server 8443:443`, user `admin`,
password from `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`.

## Secrets

`fulfillops-db` (`POSTGRES_PASSWORD`, `DATABASE_URL`) is created by `bootstrap.sh` with a
random password and is never in Git; `k8s/base/secret.example.yaml` documents its shape only.
Argo CD does not manage it, so a sync never overwrites or deletes it.

## Teardown

```bash
kind delete cluster --name fulfillops   # deletes everything, including the database volume
```

Deleting only the Application (`kubectl -n argocd delete application fulfillops`) leaves the
stack and its data running, because the Application has no cascading finalizer.

## When self-healing is safe, and when a human decides

Argo CD runs with `selfHeal: true` and `prune: true`:

- **Safe to self-heal:** stateless, declarative objects whose desired state is fully in Git:
  Deployments (replicas, image, probes), Services and the ConfigMap. A manual `kubectl scale` or
  `kubectl edit` is drift and is reverted. Git stays the only way to change production.
- **Human approval required:** anything that destroys or rewrites data. The Namespace is
  annotated `Prune=false,Delete=false`, so removing it from Git cannot delete the Postgres PVC.
  The Secret is outside Git on purpose. Schema migrations only run through the reviewed
  `db/migrations` files, as a sync hook after Postgres is healthy. Restoring a dead-lettered
  order (stock kept reserved) is a manual operator decision, never an automatic sync.
- **Incident response:** a broken release is fixed by `git revert` of the bad commit, not by
  patching the cluster. A manual hotfix would be undone by self-heal, and Git would not show
  what is actually running.
