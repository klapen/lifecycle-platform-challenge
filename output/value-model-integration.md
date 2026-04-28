# Proposal design

I would integrate the model as an additional filtering layer on top of the existing audience by joining on `renter_id`, selecting the latest score per renter (based on `scored_at`), and applying a configurable threshold (e.g., `predicted_conversion_probability` >= `threshold`). To keep the system deterministic, I would only use scores generated for the same `run_date`, ensuring consistent results across retries. I would also parameterize both the threshold and model version to support future use cases with multiple models or segments without changing the query structure.

On the orchestration side, I would introduce a dependency on the model scoring table by adding a freshness check (e.g., a sensor verifying that scores exist for the current `run_date`) before validation and sending. I would treat the model as a soft dependency with bounded waiting: wait up to a defined timeout for fresh scores, and if they are not available, default to skipping the campaign (with a Slack alert), while allowing an override to send without model filtering if needed. This balances targeting quality with operational reliability and business impact.

## Proposal details

---

### 1. BigQuery query modification

Add a CTE that resolves the latest score per renter for the current `run_date` and a specific `model_version`, then inner-join it into the existing audience query. Renters without a score are excluded (no fallback score — see tradeoff in §3).

```sql
-- Parameters: run_date DATE, model_version STRING, score_threshold FLOAT64
WITH latest_scores AS (
  SELECT
    renter_id,
    predicted_conversion_probability
  FROM (
    SELECT
      renter_id,
      predicted_conversion_probability,
      ROW_NUMBER() OVER (
        PARTITION BY renter_id
        ORDER BY scored_at DESC
      ) AS rn
    FROM `ml_predictions.renter_send_scores`
    WHERE DATE(scored_at) = @run_date
      AND model_version = @model_version
  )
  WHERE rn = 1
    AND predicted_conversion_probability >= @score_threshold
),
-- ... existing audience CTEs unchanged ...
eligible_audience AS (
  SELECT a.*
  FROM base_audience AS a
  INNER JOIN latest_scores AS s USING (renter_id)   -- 1:1 join; no duplicates
)
SELECT renter_id, email, phone, last_login, search_count, days_since_login
FROM eligible_audience
```

The `ROW_NUMBER()` deduplication ensures the 1:1 join invariant even when the scoring job runs multiple times in a day. Filtering on `DATE(scored_at) = @run_date` pins the query to the same `run_date` window on retries. Note: if `renter_send_scores` is TIMESTAMP-partitioned on `scored_at`, this predicate won't use partition pruning — prefer a range predicate for production scale:

```sql
WHERE scored_at >= TIMESTAMP(@run_date)
  AND scored_at <  TIMESTAMP(DATE_ADD(@run_date, INTERVAL 1 DAY))
  AND model_version = @model_version
```

To support a second model for a different segment (arriving in ~6 weeks), `model_version` and `score_threshold` are Airflow Variables — one set per campaign. Adding a new segment means adding a new DAG instance (or parameterized DAG run) with different Variable values, with no query or code changes required.

---

### 2. Airflow DAG modification

Insert a `check_model_freshness` task *before* `build_audience`. Since §1 places the model JOIN inside the audience SQL that `build_audience` materializes, scores must be confirmed available before that query runs — checking freshness after the materialization would gate nothing. `check_model_freshness` queries the scores table and verifies that at least one row exists for `(run_date, model_version)`.

```python
@task
def check_model_freshness(meta: dict) -> dict:
    from google.cloud import bigquery

    project   = Variable.get("CAMPAIGN_BQ_PROJECT")
    model_ver = Variable.get("CAMPAIGN_ML_MODEL_VERSION")
    run_date  = meta["run_date"]

    client = bigquery.Client(project=project)
    row = next(client.query(
        """
        SELECT COUNT(*) AS cnt
        FROM `ml_predictions.renter_send_scores`
        WHERE scored_at >= TIMESTAMP(@run_date)
          AND scored_at <  TIMESTAMP(DATE_ADD(@run_date, INTERVAL 1 DAY))
          AND model_version = @model_version
        """,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("run_date",      "DATE",   run_date),
            bigquery.ScalarQueryParameter("model_version", "STRING", model_ver),
        ]),
    ).result())

    if row.cnt == 0:
        raise _ModelNotReadyError(f"No scores for {model_ver} on {run_date}")

    return meta
```

The updated pipeline is:

```
check_model_freshness → build_audience → validate_audience → execute_campaign_send_task → log_results_and_notify
```

`check_model_freshness` uses task-level retry overrides (see §3) rather than the DAG-wide defaults, to support the longer bounded-waiting window without holding a worker slot for the full duration.

---

### 3. Handling model scoring delay

**Bounded waiting via task-level retries.** `check_model_freshness` raises a custom `_ModelNotReadyError` on each miss, which triggers Airflow's standard retry mechanism. The task overrides the DAG-wide defaults with a longer delay and more attempts sized to the bounded window (e.g., 4 retries × 15 min = 60 min):

```python
class _ModelNotReadyError(Exception):
    pass

@task(retries=4, retry_delay=timedelta(minutes=15))
def check_model_freshness(meta: dict) -> dict:
    ...
    if row.cnt == 0:
        raise _ModelNotReadyError(f"No scores for {model_ver} on {run_date}")
    return meta
```

The retry count and delay can be made configurable via Airflow Variables if operational flexibility is needed:

```python
MAX_FRESHNESS_RETRIES = int(Variable.get("CAMPAIGN_ML_MAX_RETRIES", default_var="4"))
FRESHNESS_RETRY_DELAY = timedelta(minutes=int(Variable.get("CAMPAIGN_ML_RETRY_DELAY_MIN", default_var="15")))
```

**On timeout — configurable fallback.** When all freshness retries are exhausted, the behavior is driven by `CAMPAIGN_ML_TIMEOUT_ACTION` (Airflow Variable):

| Value | Behavior |
|---|---|
| `skip` | Raise `AirflowSkipException`; DAG run marked skipped; Slack info alert sent |
| `send_unfiltered` | Return `meta` with `ml_filtered=False`; downstream SQL omits the score JOIN |
| `fail` | Raise `AirflowFailException`; pages oncall |

Default is `skip` — preserves SMS budget at the cost of lost revenue for that day. `send_unfiltered` can be set by oncall during incidents to recover revenue at the cost of targeting quality; this tradeoff (wasted volume vs. lost revenue) is the documented rationale from the source spec.

**Slack alert on timeout:**

```python
_post_slack(
    f":warning: `{campaign_id}` ML scores not ready after {MAX_FRESHNESS_RETRIES} retries "
    f"for {run_date} ({model_ver}). Action: `{timeout_action}`."
)
```

**Consistency on retry.** Because the freshness check filters on `DATE(scored_at) = @run_date`, a late-arriving scoring job that completes between DAG retries will be picked up automatically on the next attempt. The audience query then uses the same `run_date`-pinned snapshot, so a successful retry produces an identical audience to a first-attempt run.
