# Observability desing proposal

I would implement observability at both the DAG and pipeline levels, focusing on key metrics that reflect data quality, delivery performance, and system health. At the DAG level, I would rely on Airflow task success/failure signals and SLA monitoring, while at the pipeline level I would emit metrics such as audience size, send latency, success rate, and error rate per batch (especially 429s and 5xx). These metrics would be sent to Datadog with low-cardinality tags (e.g., campaign_id, status) and used to define alerts for anomalies like unusually small/large audiences, high failure rates, or SLA breaches.

To prevent double sends, I would combine client-side idempotency (tracking sent renters per campaign) with provider-level safeguards where possible (e.g., idempotency keys). Additionally, I would implement a reconciliation check post-run to detect duplicates across runs. In case of ESP outages, I would introduce a circuit breaker in the send pipeline that stops sending after repeated failures, alerts the team, and relies on the existing idempotency mechanism to safely resume on retry. This ensures the system degrades safely while preserving correctness and recoverability.

## Proposal details

---

### 1. Datadog metrics and alerts

#### Pipeline metrics

Emitted from task code via the `datadog` Python client (DogStatsD), tagged with `campaign_id`, `run_date`, and `dag_run_id`:

| Metric | Type | Description |
|---|---|---|
| `campaign.audience_size` | gauge | Row count from `build_audience` |
| `campaign.send.sent` | count | Recipients successfully delivered |
| `campaign.send.failed` | count | Batches dropped after max retries |
| `campaign.send.skipped` | count | Recipients filtered by dedup |
| `campaign.send.elapsed_seconds` | gauge | Wall-clock time of the send task |
| `campaign.esp.http_status` | count | Per-status-code counter (tagged `status:2xx`, `status:429`, `status:5xx`) |
| `campaign.esp.retry_count` | count | Total retry attempts across all batches |
| `campaign.dag.task_duration_seconds` | gauge | Per-task wall time (tagged `task_id`) |
| `campaign.circuit_breaker.open` | count | Incremented each time the circuit breaker trips |

#### Infrastructure metrics

Collected by the Datadog Agent on the Airflow worker nodes (no code changes required). Tagged with `host`, `worker_pool`, and `campaign_id` where Airflow passes it via environment:

| Metric | Type | Why it matters |
|---|---|---|
| `system.cpu.user` | gauge | High CPU during the send loop signals batch size or retry logic needs tuning |
| `system.mem.used` / `system.mem.pct_usable` | gauge | The audience dict and sent log are held in memory; growth here tracks audience scale |
| `system.disk.in_use` | gauge | Sent log files accumulate on the worker; alerts before disk pressure causes write failures |
| `system.io.await` | gauge | High I/O wait during `persist_sent` indicates the file-based dedup is becoming a bottleneck |
| `kubernetes.cpu.requests` / `kubernetes.memory.requests` | gauge | If workers run on Kubernetes (KubernetesExecutor), tracks requested vs. actual resource use — key input for right-sizing pods and reducing cost |

#### Alert configuration

| Alert | Condition | Threshold | Window | Severity | Action |
|---|---|---|---|---|---|
| Audience size anomaly | `campaign.audience_size` vs. 14-day avg | > 2× or < 0.5× | Per run | P2 | Slack `#campaign-alerts` |
| High ESP 5xx rate | `campaign.esp.http_status{status:5xx}` / total | > 5% | 10 min rolling | P1 | Page oncall |
| Sustained 429s | `campaign.esp.http_status{status:429}` / total | > 15% | 5 min rolling | P2 | Slack `#campaign-alerts` |
| Low send completion | `campaign.send.sent` / `campaign.audience_size` | < 90% | Post-run | P2 | Slack `#campaign-alerts` |
| SLA breach | Cumulative DAG run time | > 3 h | Per run | P1 | Page oncall |
| DAG failure | Last run status | `failed` | Per run | P1 | Page oncall |
| High worker CPU | `system.cpu.user{worker_pool:campaign}` | > 85% | 5 min sustained | P3 | Slack `#infra-alerts` |
| Worker memory pressure | `system.mem.pct_usable{worker_pool:campaign}` | < 15% | 5 min sustained | P2 | Slack `#infra-alerts` |
| Disk usage | `system.disk.in_use{worker_pool:campaign}` | > 80% | 5 min sustained | P2 | Slack `#infra-alerts` |
| High I/O wait | `system.io.await{worker_pool:campaign}` | > 200 ms | 5 min sustained | P3 | Slack `#infra-alerts` |

Infrastructure alerts at P3 are non-paging — they feed a capacity-review process rather than waking oncall. Sustained CPU or memory anomalies during campaign runs are the primary signal for tuning batch size, worker pod sizing, or right-sizing reserved capacity.

---

### 2. Detecting and preventing double-sends

Double-sends can arise from two sources: **retries within a run** (task retry after a mid-batch crash) and **re-triggers across runs** (a second DAG run for the same `run_date`).

**Within a run — file-based dedup.** `execute_campaign_send_task` writes sent `renter_id`s to a JSON file keyed by `campaign_id + run_date` after each successful batch. On retry, the task loads this file and filters out already-sent recipients before processing the remaining audience. A crash mid-batch loses at most the current in-flight batch, because persistence happens per batch immediately after a successful ESP response — not at the end of the full run.

**Across runs — composite key guard.** Before sending any batch, the task checks whether the `run_date` entry in the sent log already exists and is non-empty. If a second DAG run is triggered for the same `run_date`, the entire audience is filtered out and the run completes with `total_sent=0` and a Slack warning. A human must explicitly clear the sent log to intentionally re-send for a date.

**Reconciliation.** `log_results_and_notify` writes a row to the BigQuery reporting table tagged with `dag_run_id`. A scheduled query groups by `(campaign_id, run_date)` and flags any date with more than one `success` row — the detection layer sitting below the prevention layer above.

**Known limitation.** The file-based sent log is not safe for distributed workers. In production this should be replaced with an atomic BigQuery `MERGE` or a Redis SET, but the dedup key (`campaign_id + renter_id + run_date`) is the same regardless of backend.

---

### 3. ESP outage strategy

**Circuit breaker in the send loop.** The per-batch retry logic (exponential backoff, max 5 retries) handles transient errors. A circuit breaker operates at the task level: after a configurable number of *consecutive* batch failures, the pipeline stops processing further batches, emits `campaign.circuit_breaker.open` to Datadog, posts a Slack alert, and raises `AirflowFailException` to hand off to Airflow's task-level retry.

```python
CIRCUIT_BREAKER_THRESHOLD = int(Variable.get("CAMPAIGN_CIRCUIT_BREAKER_THRESHOLD", default_var="3"))

consecutive_failures = 0
for batch in batches:
    success = _send_batch_with_retries(esp_client, campaign_id, batch, logger)
    if success:
        consecutive_failures = 0
        persist_sent(...)
    else:
        consecutive_failures += 1
        if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            _post_slack(f":rotating_light: Circuit breaker open for `{campaign_id}` — ESP unresponsive.")
            raise AirflowFailException("Circuit breaker threshold reached; aborting send.")
        logger.batch_dropped(batch_size=len(batch))
```

**Recovery.** When Airflow retries the task, it reloads the sent log and resumes from the first unsent recipient — only the unsent tail of the audience is re-attempted. If the ESP has recovered, the run completes normally. If not, the task exhausts its retries, the DAG run is marked failed, and oncall is paged via the Datadog DAG-failure alert.

**Partial-state safety.** Because the sent log is written per batch, a circuit-breaker trip preserves all previously persisted sends. No recipient who already received the message is contacted again on retry — recovery is identical to a normal mid-run crash recovery.