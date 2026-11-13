# SLOs and measurement

Owner: Mink

These are objectives for the isolated local lab (kind or Docker Compose on one laptop). They
show how the service would be held to account and how each number is computed; they are not
claims about production capacity. See [Limitations](#limitations).

## Targets

| SLI | Definition | Objective | Window |
|-----|------------|-----------|--------|
| Availability | Share of API requests that do not end in a 5xx. Client errors (4xx) count as successes: the service answered correctly | **99.5 %** | Per test run; 30 days in a real deployment |
| Latency | p95 server time for API requests, and p95 client-observed time from `scripts/measure_p95.py` | **p95 < 300 ms** | At least 200 samples per measurement |
| Order completion | Share of accepted orders that reach `completed` within 15 s of acceptance (the contract's healthy-setup expectation) | **99 %** | Per test run; fault-drill orders excluded |
| Durability | Accepted orders (202 with a new `order_id`) that can no longer be found | **0**, no error budget | Always |
| Rollout availability | Failed samples of the 30 s readiness probe during a rolling update | **0 of ~120** | Per rollout |

### Error budget and policy

A 99.5 % availability objective leaves 0.5 % of requests, or 5 per 1,000, as the error budget.
If a run or window spends more than that, releases stop and the next change is a reliability
fix. Durability has no budget: any lost order is an incident and gets a postmortem.

## Measurement method

### Latency

Client side, `scripts/measure_p95.py` sends at least 200 sequential requests to
`GET /api/v1/catalog` on `http://localhost:8080`. That endpoint is read-only, so the measurement
never consumes stock. It stores every raw sample (UTC timestamp, HTTP status, duration in ms)
under `docs/evidence/` and reports p50, p95 and p99 using the nearest-rank method:
the p95 is the value at position `ceil(0.95 * n)` of the sorted samples.

Server side, each API replica exports the histogram `fulfillops_http_request_duration_seconds`.
Its buckets are dense around the target (100, 200, 300, 500 ms), so whether the p95 is under
300 ms can be read directly. With Prometheus scraping both replicas:

```promql
histogram_quantile(0.95,
  sum by (le) (rate(fulfillops_http_request_duration_seconds_bucket[5m])))
```

Without Prometheus, take a `/metrics` snapshot from **each** API pod, since the counters are per
process, and add the bucket counts. The p95 lies in the first bucket whose cumulative count
reaches `0.95 * total`, and linear interpolation inside that bucket gives the estimate.

### Availability

```promql
1 - sum(rate(fulfillops_http_requests_total{status=~"5.."}[30d]))
  / sum(rate(fulfillops_http_requests_total[30d]))
```

For a single test run: the 5xx count divided by the total from the summed `/metrics` snapshots,
cross-checked against the raw status codes recorded by the measurement script.

### Order completion and durability

Both come from the database, which is the source of truth. The worker sets `orders.updated_at`
when it completes an order.

```sql
-- share of accepted orders completed within 15 s (exclude fault-drill orders)
SELECT avg((status = 'completed'
            AND updated_at - created_at <= interval '15 seconds')::int) AS within_15s
FROM orders
WHERE customer_id NOT LIKE 'poison-%';

-- orders waiting for an operator (dead letter), with the reason
SELECT o.order_id, j.attempts, j.last_error, j.dead_lettered_at
FROM jobs j JOIN orders o USING (order_id)
WHERE j.dead_lettered_at IS NOT NULL;
```

`fulfillops_orders_created_total`, `fulfillops_orders_failed_total` and
`fulfillops_worker_retries_total` are read from the same tables, so every API replica reports
identical values, and the values survive pod restarts.

### Rollout availability

`fulfillops_rollout_probe.py` polls `/health/ready` every 0.25 s for 30 s through
`localhost:8080`, while the API Deployment rolls. The CSV is kept as
`docs/rolling_update_probe.csv`. The probe goes through the kind port mapping and the NodePort
Service, so it measures what a client sees while pods are replaced. A `kubectl port-forward`
would pin a single pod and break when that pod is replaced.

## Results

To be filled in from the evidence runs: sample count, p50, p95 and p99 from
`scripts/measure_p95.py`, the histogram-based p95, the 5xx share, the share completed within
15 s, and the number of failed rollout-probe samples.

## Limitations

- **One machine.** The client, both API replicas, both workers and Postgres share the same
  laptop CPU inside the Docker Desktop VM. Latency includes contention between them and no
  real network, so the numbers say nothing about capacity elsewhere.
- **Sequential, light load.** The script measures latency at one request at a time, not
  throughput or behaviour under saturation. 200 samples give a stable p95 but say little about
  the p99 tail.
- **Read path only.** The p95 run uses `GET /api/v1/catalog` so it does not consume the seeded
  stock (only 24 units). Order creation latency is visible in the histogram from checker and
  test runs, which have far fewer samples.
- **Bucket resolution.** The server-side p95 is only as precise as the histogram buckets
  (for example, anything between 200 and 300 ms falls in one bucket).
- **Per-process counters.** HTTP counters reset when an API pod restarts. `rate()` handles that,
  but a raw snapshot covers only the current process lifetime.
- **Completion time includes polling.** The worker polls every 0.5 s and the lab may add an
  artificial processing delay for the kill-a-worker drill. A worker crash adds up to one lease
  (30 s), so orders hit by a crash are expected to miss the 15 s objective.
- **No long-term monitoring.** No Prometheus or alerting is deployed in the lab, so the 30-day
  windows describe how the SLO would be run, while the measured values come from individual
  runs. `/metrics` is unauthenticated and must only be reachable inside the lab network; in
  production it would sit behind a network policy and be scraped only by Prometheus.
