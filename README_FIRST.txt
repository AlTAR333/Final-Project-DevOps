FULFILLOPS — THE RESILIENT ORDER-PROCESSING PLATFORM | EXPERT CAPSTONE 9.5/10

AUDIENCE: Entire class, teams of 2–3, one project built from an EMPTY repo.
SCHEDULE: Proposed 9–15 Nov 2026, deadline subject to instructor confirmation.
EFFORT: 40–55 shared team-hours, including SIX supervised classroom hours
        in two 3-hour project work blocks (34–49 additional shared team-hours).

READ IN THIS ORDER:
  1. FulfillOps_95_Student_Assignment_EN.pdf — objectives, higher-level engineering tasks, evidence and grading.
  2. FulfillOps_95_API_Contract_EN.pdf — exact API contract (unchanged from 9/10 edition).
  3. FulfillOps_95_Setup_Guide_EN.pdf — tools, Kubernetes/Argo CD, preflight, classroom blocks, rollback probe.
  4. fulfillops_public_checker.py — 15 black-box API checks, stdlib Python, destructive to test stock.
  5. fulfillops_rollout_probe.py — 30-second timestamped HTTP availability sampling during Kubernetes rollout.

NO APPLICATION SOURCE / SOLUTIONS PROVIDED. Create API, worker, schema, database,
queue, tests, Dockerfile, compose, CI, Kubernetes manifests, Argo CD and evidence.

FINAL CHECKER (fresh, isolated test DB only):
  python fulfillops_public_checker.py --base-url http://localhost:8080 --concurrency --stress
Expected when complete: 15 passed / 0 failed / 0 skipped

LOCAL ROLLING-UPDATE PROBE (start before deployment, use own localhost port-forward):
  python fulfillops_rollout_probe.py --base-url http://localhost:8080 --duration 30 --output rollout_probe.csv

NEVER run destructive checks against production, shared systems or other student services.
The grader will also examine failure recovery, bounded retries, CI SBOM and GitOps.
Instructor answer files must NEVER be distributed to students.
