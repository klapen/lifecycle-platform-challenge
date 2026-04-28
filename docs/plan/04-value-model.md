# Step 4 — Value Model Integration (Design)

## Goal

Produce a written design document at `output/value-model.md` describing how to fold ML scoring into the audience query, add a freshness dependency in the DAG, and handle the case where the model job is late. **No code in this step** — the implementation would happen in a follow-up cycle.

## Source doc

[../value-model.md](../value-model.md) — read the original problem statement and the design considerations list.

## Key constraints from source

- ML scores live in `ml_predictions.renter_send_scores (renter_id, predicted_conversion_probability, model_version, scored_at)`.
- Use **only same-`run_date` scores** — stale scores degrade targeting.
- The table may have multiple rows per renter — pick the latest `scored_at` per `renter_id` (and per `model_version`).
- Threshold (e.g., `0.3`) must be configurable, not hard-coded.
- A second model is coming in ~6 weeks — design must support **multiple models with different thresholds per segment** without rearchitecture.
- Renters without a score → excluded (assumption documented in source).
- Score dependency is **soft with bounded waiting** (30–60 min), not a hard block. Tradeoff: wait risks SLA, skip loses revenue, fallback (no filtering) lowers targeting quality.

## Files to create

```
output/value-model.md
```

No code, no tests.

## Document structure

Mirror the `docs/*.md` style: original problem statement verbatim at the top, then numbered design decisions with `---` separators. Add code/SQL examples only as illustrative blocks — they're design sketches, not runnable artifacts.

### Section outline for `output/value-model.md`

1. **Original problem statement** (verbatim from `docs/value-model.md`).
2. **Design Decisions** (numbered):
   1. **Configuration model.** A campaign config (YAML or dict, sourced from a Variable / config table) drives:
      ```yaml
      campaigns:
        reactivation_sms:
          model_version: "v3.2.0"
          score_threshold: 0.30
          segment: "churned_renters"
      ```
      Adding a new model = adding a new entry, not changing code.
   2. **SQL modification** — show the SELECT enhancement: a `latest_scores` CTE that picks the most recent score per `(renter_id, model_version)` filtered to `@model_version`, then `INNER JOIN` to the audience and filter by `predicted_conversion_probability >= @score_threshold`. Both `@model_version` and `@score_threshold` are query parameters. Example pseudocode:
      ```sql
      WITH latest_scores AS (
        SELECT renter_id, predicted_conversion_probability,
               ROW_NUMBER() OVER (PARTITION BY renter_id ORDER BY scored_at DESC) AS rn
        FROM ml_predictions.renter_send_scores
        WHERE model_version = @model_version
          AND DATE(scored_at) = @run_date
      )
      …
      INNER JOIN latest_scores ls ON ls.renter_id = p.renter_id AND ls.rn = 1
      WHERE ls.predicted_conversion_probability >= @score_threshold
      ```
      Inner join → renters without a score are excluded (matches the assumption).
   3. **DAG dependency on freshness** — add a `BigQueryTablePartitionExistenceSensor` (or equivalent freshness check using a `@task` that runs `SELECT 1 FROM … WHERE DATE(scored_at) = @run_date AND model_version = @model_version LIMIT 1`) before `build_audience`. Sensor in `reschedule` mode to free the worker slot. `timeout=timedelta(minutes=45)` (within the 3-hour SLA budget).
   4. **Bounded-wait fallback** — when the sensor times out, branch on a config flag `on_score_unavailable` with three values:
      - `skip` — fail the DAG run (no campaign today). Default.
      - `send_unfiltered` — proceed with the unfiltered audience and tag the run as degraded.
      - `fail` — treat as a hard failure (page oncall).
      Use `BranchPythonOperator` or TaskFlow `@task.branch` to pick the path. Slack notification fires on any non-default outcome.
   5. **Determinism / consistency** — once a run starts, snapshot the score table to a per-run materialized table or rely on partition pinning so a re-scoring mid-day cannot change the audience. The audience staging table from Step 1 already provides this guarantee, as long as `build_audience` materializes after the score sensor passes.
   6. **Multi-model support** — config-driven, no code change. Each campaign points at its own `model_version` and `threshold`. A future segment-2 campaign is a new config entry consuming the same DAG (or a parameterized DAG factory if segments diverge structurally).
   7. **Observability** — emit metrics: `audience_size_pre_filter`, `audience_size_post_filter`, `score_filter_ratio`, `score_distribution_p50/p95`, `model_version_used`. These feed the Step 5 observability design.
   8. **Tradeoff note** — explicitly call out the wait/skip/fallback decision as a business call, not a technical one. Default to `skip` because false sends are more expensive than missed sends in this domain (assumption — flag for product confirmation).
   9. **Limitations / not in scope** — fallback to a different model version, A/B holdout groups, score backfill jobs, alerting on score drift.

## Done when

- `output/value-model.md` exists and follows the structure above
- Each section is concrete enough to translate to code in a future step (SQL fragments, sensor params, config schema)
- Document references `docs/value-model.md` as the source of constraints

## Commit checkpoint

Before committing: have the user read `output/value-model.md` end-to-end. Wait for explicit approval. Suggested commit message:

```
docs: add design for ML value-model integration into campaign pipeline
```
