# Step 1 — BigQuery Audience Query

## Goal

Write a parameterized, idempotent BigQuery SQL query that builds the SMS reactivation campaign audience for a given `run_date`, plus a small pytest covering structural invariants.

## Source doc

[../bigquery.md](../bigquery.md) — read sections "Schema", "Task", and "Part 1 - Assumptions & Design Decisions" before implementing.

## Key constraints from source

- **Idempotency:** Driven by a `run_date` parameter (BigQuery query parameter `@run_date` of type `DATE`). No `CURRENT_TIMESTAMP()` / `CURRENT_DATE()`.
- **Last login:** `last_login < run_date - INTERVAL 30 DAY`. NULL `last_login` does not qualify.
- **Subscription status:** `'churned'`.
- **Search count:** `>= 3` events with `event_type = 'search'` in `[run_date - INTERVAL 90 DAY, run_date)` (exclusive upper bound — partial current-day events are excluded for stability).
- **Phone:** `phone IS NOT NULL AND TRIM(phone) != ''`.
- **Consent:** `sms_consent = TRUE` (explicit; NULL is no consent).
- **Suppression list:** Excluded via `NOT EXISTS` (avoids row duplication if a renter has multiple suppression rows).
- **DND:** `dnd_until IS NULL OR dnd_until < run_date` (compared against `run_date`, not now).
- **Aggregation before join:** Compute search counts in a CTE/subquery first, then join to profiles. Reduces scan cost.
- **Output columns:** `renter_id, email, phone, last_login, search_count, days_since_login`.
- **Time zone:** UTC throughout.

## Files to create

```
src/sql/audience.sql            # the parameterized query
tests/test_audience_sql.py      # structural assertions on the SQL
```

## Implementation steps

1. **Write `src/sql/audience.sql`** as a single statement parameterized by `@run_date` (DATE). Structure:
   - `WITH searches AS (SELECT renter_id, COUNT(*) AS search_count FROM renter_activity WHERE event_type = 'search' AND event_timestamp >= TIMESTAMP(DATE_SUB(@run_date, INTERVAL 90 DAY)) AND event_timestamp < TIMESTAMP(@run_date) GROUP BY renter_id HAVING search_count >= 3)`
   - `SELECT … FROM renter_profiles p JOIN searches s USING (renter_id) WHERE …`
   - Filters in WHERE clause: `last_login < TIMESTAMP(DATE_SUB(@run_date, INTERVAL 30 DAY))`, `subscription_status = 'churned'`, phone non-empty, `sms_consent = TRUE`, DND check.
   - Suppression exclusion via `AND NOT EXISTS (SELECT 1 FROM suppression_list sl WHERE sl.renter_id = p.renter_id)`.
   - `days_since_login` = `DATE_DIFF(@run_date, DATE(last_login), DAY)`.
2. **Decide on materialization wrapper.** Per the source doc §13, results should land in a staging table partitioned by `run_date`. Add a leading SQL comment documenting the expected wrapping pattern (`CREATE OR REPLACE TABLE … PARTITION BY run_date AS …` or `MERGE` into a partition) but **do not** hard-code the staging table name in `audience.sql` — the DAG (Step 3) supplies it. The file holds the SELECT only.
3. **Add file header comment** with: parameters used, output schema, and a one-line note that this file is the canonical audience definition (any change requires updating `docs/bigquery.md`).
4. **Write `tests/test_audience_sql.py`** with structural tests that don't require a live BigQuery connection:
   - `test_no_dynamic_now`: assert the SQL contains neither `CURRENT_TIMESTAMP` nor `CURRENT_DATE` (case-insensitive).
   - `test_uses_run_date_parameter`: assert `@run_date` appears.
   - `test_expected_output_columns`: parse the top-level `SELECT` list (regex on the first SELECT after CTEs) and assert the six required columns are present in order or by name.
   - `test_excludes_suppression_list`: assert `NOT EXISTS` (or `LEFT JOIN … IS NULL`) referencing `suppression_list` is present.
   - `test_search_window_90_days`: assert `INTERVAL 90 DAY` appears in a search-count context.
   - `test_last_login_window_30_days`: assert `INTERVAL 30 DAY` appears.
   - All tests load the SQL via `Path("src/sql/audience.sql").read_text()` — no pytest fixtures needed.

## Tests

```bash
uv run pytest tests/test_audience_sql.py -v
```

Should report 6 passing tests. Tests are intentionally string-based; full semantic validation belongs in BigQuery integration testing (out of scope for this exercise).

## Done when

- `src/sql/audience.sql` parses on visual inspection and follows the structure above
- All 6 tests pass
- File header documents parameters, output schema, and points back to `docs/bigquery.md`

## Commit checkpoint

Before committing: present the SQL file and test output to the user. Wait for explicit approval. Suggested commit message:

```
feat(sql): add parameterized audience query for SMS reactivation campaign
```
