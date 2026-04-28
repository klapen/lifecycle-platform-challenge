# Step 3 — Airflow DAG

## Goal

Wire the four pipeline stages into a single Airflow DAG with the schedule, retries, SLA, and validation gate the source doc specifies. Pass only small metadata via XCom; large data lives in the BigQuery staging table.

## Source doc

[../airflow.md](../airflow.md) — read both the original problem statement and the assumption list.

## Key constraints from source

- **Schedule:** `0 5 * * *` UTC (daily at 5:00 AM UTC).
- **Retries:** `retries=2`, `retry_delay=timedelta(minutes=5)` per task.
- **SLA:** DAG must finish by 8:00 AM UTC → `sla=timedelta(hours=3)` on the final task (or DAG-level if Airflow version supports it).
- **Linear dependencies:** `build_audience >> validate_audience >> execute_campaign_send >> log_results_and_notify`.
- **`run_date` derived from `logical_date`** (not system clock). Pass as `ds` (YYYY-MM-DD) string via XCom.
- **XCom contents only:** `campaign_id`, `run_date`, `staging_table`, `audience_count`. No audience rows.
- **Validation gate:** `audience_count > 0` AND `audience_count <= 2 × historical_avg`. Failure → stop pipeline, send Slack notification, do not invoke send.
- **Send task uses incremental retry semantics:** on retry, only renters not yet in `sent_renters.json` are processed (the dedup filter inside `execute_campaign_send` already handles this — the DAG just re-invokes the same call).
- **Final task** persists results to a reporting table and posts a Slack summary with: `campaign_id, run_date, audience_count, total_sent, total_failed, total_skipped, elapsed_seconds, dag_run_id`.

## Files to create

```
src/dags/__init__.py            # already exists from Step 0
src/dags/campaign_dag.py        # the DAG
tests/test_dag.py               # structural tests
```

## Implementation outline

Use the TaskFlow API (`@task` decorators) — cleaner than `PythonOperator` for this size. Use `@dag(...)` decorator for the DAG itself.

### `default_args`

```python
default_args = {
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "owner": "lifecycle-platform",
}
```

### Tasks

1. **`build_audience(run_date: str, campaign_id: str) -> dict`**
   - Loads `src/sql/audience.sql`, wraps with `CREATE OR REPLACE TABLE {staging_table} PARTITION BY run_date AS …`, executes via `BigQueryInsertJobOperator` (or a `@task` that uses `google.cloud.bigquery.Client`). Either is acceptable; prefer the operator if it keeps the code shorter.
   - Returns `{"campaign_id": ..., "run_date": ..., "staging_table": ..., "audience_count": ...}`.
   - `staging_table` follows pattern `<project>.<dataset>.audience_{campaign_id}_{run_date_compact}`.

2. **`validate_audience(meta: dict) -> dict`**
   - Reads `audience_count` from `meta`.
   - Looks up historical average over the last N (e.g. 14) successful runs from a reporting table.
   - On failure (count == 0 OR count > 2 × historical_avg): post Slack alert, raise `AirflowFailException` (non-retryable) so the DAG halts cleanly.
   - On success: return `meta` unchanged.

3. **`execute_campaign_send_task(meta: dict) -> dict`**
   - Reads the staging table → list[dict] (recipient projection: at minimum `renter_id` and `phone`).
   - Calls `pipeline.send.execute_campaign_send(campaign_id, audience, esp_client, sent_log_path)`. The `sent_log_path` should be a deterministic per-campaign-per-run-date path so manual reruns continue from where the prior attempt stopped. The dedup file is shared across retries within a run but **scoped to `campaign_id`** so different campaigns don't collide.
   - Merges the metrics dict into `meta` and returns it.

4. **`log_results_and_notify(meta: dict) -> None`**
   - Inserts a row into the reporting table with the documented fields.
   - Posts a Slack summary via `SlackWebhookOperator` or a thin `requests.post` wrapper (Slack webhook URL from Airflow Connections / Variables).
   - SLA decorator (`sla=timedelta(hours=3)`) applied here so SLA breach is reported even if the rest succeeded late.

### DAG declaration

```python
@dag(
    dag_id="campaign_pipeline",
    schedule="0 5 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    default_args=default_args,
    tags=["campaign", "lifecycle"],
)
def campaign_pipeline():
    meta = build_audience(run_date="{{ ds }}", campaign_id="reactivation_sms")
    validated = validate_audience(meta)
    sent = execute_campaign_send_task(validated)
    log_results_and_notify(sent)

dag = campaign_pipeline()
```

Note: `campaign_id` is a constant for this exercise. Real systems would pull it from a config table or DAG params.

### Configuration touch points (do not hard-code)

- BigQuery project/dataset/staging-table prefix
- Slack webhook URL / channel
- ESP API base URL & credentials
- `sent_log_path` root
- `historical_window_days` for the validation comparison

Use Airflow `Variable.get` or `Connection` for these. Mention this in the file header so future maintainers know what to wire up.

## Tests (`tests/test_dag.py`)

These are import/structure tests — they don't run the DAG. If `apache-airflow` isn't installed in the dev env, mark these tests with `pytest.importorskip("airflow")`.

1. **`test_dag_imports`** — DAG file imports without error.
2. **`test_dag_id_and_schedule`** — `dag.dag_id == "campaign_pipeline"`, `dag.schedule_interval == "0 5 * * *"` (or the property name your Airflow version uses).
3. **`test_default_args`** — `retries == 2`, `retry_delay == timedelta(minutes=5)`.
4. **`test_task_dependencies`** — task IDs in topological order match `[build_audience, validate_audience, execute_campaign_send_task, log_results_and_notify]`. Use `dag.topological_sort()` or check `task.upstream_task_ids` per task.
5. **`test_sla_set`** — final task has `sla == timedelta(hours=3)` (or DAG-level if applicable).
6. **`test_no_audience_in_xcom`** — inspect `validate_audience` and `execute_campaign_send_task` source / signatures via `inspect.signature` and confirm parameters are scalar/dict, not `list` of audience rows. Best-effort sanity check.

Run:
```bash
uv run pytest tests/test_dag.py -v
```

## Done when

- DAG imports cleanly under `apache-airflow` (or skips gracefully if not installed)
- All structure tests pass
- DAG file documents required Airflow Variables/Connections in its header
- The send task delegates to `pipeline.send.execute_campaign_send` (no logic duplicated)

## Commit checkpoint

Before committing: show the DAG file and test output to the user. Wait for explicit approval. Suggested commit message:

```
feat(dags): add campaign_pipeline DAG (build → validate → send → report)
```

If `apache-airflow` is added as a dependency in this step, mention that to the user explicitly so they can decide whether to mark it `[dev]` / optional given the install footprint.
