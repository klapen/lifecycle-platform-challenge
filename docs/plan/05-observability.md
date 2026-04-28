# Step 5 — Observability & Reliability (Design)

## Goal

Produce a written design at `output/observability.md` answering the three observability questions in the source doc: Datadog metrics & alerts, double-send detection/prevention, and ESP outage strategy. **No code in this step.**

## Source doc

[../observability.md](../observability.md) — currently contains only the prompt. The three questions to answer:

1. What Datadog metrics and alerts would you set up for this pipeline? (DAG latency, audience size anomalies, ESP error rates, send completion rates.)
2. How would you detect and prevent double-sends if the pipeline runs twice (Airflow retry or manual re-trigger)?
3. What happens if the ESP goes down mid-send? Describe the circuit-breaker or recovery strategy.

## Key constraints to honor

These come from the broader design (`/CLAUDE.md` and other docs):
- `run_date` is the time anchor — observability must use it consistently
- Idempotency key is `campaign_id + renter_id`
- Validation gate already exists: `count > 0` AND `count <= 2× historical_avg` (the audience-size anomaly question already has a starting answer in the DAG)
- ESP retry budget per batch is 5; total run window is 3 hours

## Files to create

```
output/observability.md
```

No code, no tests.

## Document structure

Mirror `docs/*.md` style: prompt verbatim at the top, then three numbered sections (one per question), each with concrete metric/alert/recovery specifications. Use code blocks for metric names, alert thresholds, and pseudocode where it sharpens the design.

### Section 1 — Datadog Metrics & Alerts

Metric naming convention: `lifecycle.campaign.<dimension>.<metric>` with tags `campaign_id`, `run_date`, `dag_run_id`, `env`.

**Metrics to emit (from the DAG and send module):**

- **DAG-level**
  - `lifecycle.campaign.dag.duration_seconds` (gauge, per run)
  - `lifecycle.campaign.dag.task_duration_seconds` (gauge, tagged `task_id`)
  - `lifecycle.campaign.dag.status` (count, tagged `status=success|failed|sla_miss`)
- **Audience**
  - `lifecycle.campaign.audience.size` (gauge)
  - `lifecycle.campaign.audience.size_vs_historical_ratio` (gauge — current / 14-day avg)
  - `lifecycle.campaign.audience.score_filter_ratio` (gauge — post-filter / pre-filter)
- **Send pipeline**
  - `lifecycle.campaign.send.batches_total` (count)
  - `lifecycle.campaign.send.batch_latency_ms` (histogram, tagged `status_code`)
  - `lifecycle.campaign.send.recipients_sent` (count)
  - `lifecycle.campaign.send.recipients_failed` (count)
  - `lifecycle.campaign.send.recipients_skipped` (count — already-deduped)
  - `lifecycle.campaign.send.completion_ratio` (gauge — sent / (sent + failed))
  - `lifecycle.campaign.send.retries_total` (count, tagged `reason=429|5xx|timeout`)
  - `lifecycle.campaign.send.esp_5xx_rate` (rate)
  - `lifecycle.campaign.send.esp_429_rate` (rate)

**Alerts (with thresholds):**

| Alert | Condition | Severity |
| --- | --- | --- |
| DAG SLA miss | `dag.duration_seconds > 10800` (3h) | P1 |
| DAG failure | `dag.status:failed` count >= 1 | P1 |
| Audience anomaly | `audience.size == 0` OR `audience.size_vs_historical_ratio > 2` | P2 (already gated in code; alert is belt-and-braces) |
| ESP error rate | `esp_5xx_rate > 0.10` over 5 min | P2 |
| Rate-limit pressure | `esp_429_rate > 0.20` over 5 min | P3 (signals throttle, not failure) |
| Low send completion | `send.completion_ratio < 0.95` for a finished run | P2 |
| Retry exhaustion spike | `send.retries_total{reason=*}` > N% baseline | P3 |

Dashboards: one DAG-run drill-down, one campaign-trend (week-over-week) view.

### Section 2 — Double-Send Prevention

Layered defense:

1. **Client-side dedup (already in Step 2):** `sent_renters.json` keyed by `campaign_id`. Filtered before every batch. This is the authoritative single-node defense.
2. **Per-batch persistence** (decided in Step 2): partial-progress survives crashes mid-run.
3. **Manual re-trigger handling:** Airflow's `dag_run_id` is unique per logical run; the dedup file is keyed by `campaign_id` (not `dag_run_id`), so a manual re-trigger of the same run-date sees the prior progress and skips already-sent renters.
4. **Cross-host weakness (acknowledged):** file-based dedup is single-node. Production upgrade path:
   - Move dedup state to a write-behind store: BigQuery `sent_log` table partitioned by `campaign_id, run_date`, with a `MERGE … WHEN NOT MATCHED INSERT` semantic.
   - Or Redis/DynamoDB with TTL, keyed by `campaign_id:renter_id`.
5. **Provider idempotency keys (future):** when the ESP supports them, pass `idempotency_key = sha256(campaign_id || renter_id)` per recipient. Eliminates duplicate messages even if the network response is lost.
6. **Reconciliation job (future):** nightly compare ESP delivery log to local `sent_log`; emit alert on diff > threshold.
7. **Detection metric:** `lifecycle.campaign.dedup.skipped_total` (count of renters filtered before send) — a sudden spike on retry runs is the expected signature of this guard working.

### Section 3 — ESP Outage Mid-Send

Phased response:

1. **In-batch retries (already in Step 2):** 5 retries with backoff handles transient blips.
2. **Circuit breaker** wrapping `send_batch`:
   - **Closed** (normal): forward calls.
   - **Open** (after `N` consecutive failures or `M%` failure rate over a window — e.g., 5 in a row, or 50% of last 20): short-circuit; fail subsequent batches fast without hitting the ESP.
   - **Half-open** (after `cooldown` seconds — e.g., 60s): allow a single probe batch. Success → close. Failure → re-open.
3. **Pipeline behavior on open circuit:** stop dispatching new batches in the current run, persist progress so far, mark run as **partially completed**, exit cleanly with an explicit failure code. The next scheduled run (or a manual retry) will pick up exactly where we left off because dedup state is on disk.
4. **Recovery strategy:**
   - Airflow retry with 5-minute delay (already configured) often resolves short outages.
   - If outage exceeds the 3-hour SLA window: notify oncall, do not auto-roll-forward. The campaign is missed for the day; document the business decision (default: skip rather than send late, because reactivation messages have implicit time relevance).
5. **Operator runbook items** (linked from the alert):
   - How to re-trigger the DAG once ESP is healthy
   - How to inspect `sent_renters.json` for partial progress
   - How to verify circuit-breaker state if running across multiple workers (open question for distributed execution)
6. **Future hardening:**
   - Move circuit-breaker state to Redis so it's shared across workers
   - Provider health endpoint poll as a secondary signal
   - Automated reconciliation against ESP delivery webhooks

## Done when

- `output/observability.md` exists with three sections answering the three prompt questions
- Each metric and alert has a concrete name and threshold
- Circuit-breaker states and transitions are spelled out
- Document links back to `docs/observability.md` as the prompt source

## Commit checkpoint

Before committing: have the user read `output/observability.md` end-to-end. Wait for explicit approval. Suggested commit message:

```
docs: add observability and reliability design for campaign pipeline
```
