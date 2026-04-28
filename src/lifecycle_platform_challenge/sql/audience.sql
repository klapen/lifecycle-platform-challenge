-- Audience query for SMS reactivation campaign
--
-- Parameters:
--   @run_date DATE  — logical execution date sourced from Airflow logical_date.
--                     All time windows are evaluated relative to this value.
--                     Never substitute CURRENT_DATE() or CURRENT_TIMESTAMP().
--
-- Output columns:
--   renter_id        STRING    — unique renter identifier
--   email            STRING    — renter email address
--   phone            STRING    — validated non-empty phone number
--   last_login       TIMESTAMP — most recent login timestamp
--   search_count     INT64     — search events in the past 90 days
--   days_since_login INT64     — days elapsed since last_login as of run_date
--
-- Materialization:
--   This file contains the SELECT only. The DAG wraps it as:
--     CREATE OR REPLACE TABLE <staging_table>
--     PARTITION BY run_date AS (<this query>)
--   Downstream tasks read from the staging snapshot — they do not re-run this query.
--
-- Performance assumptions:
--   renter_activity is partitioned by event_timestamp and clustered by
--   (event_type, renter_id). The time-window filters below enable partition
--   pruning; changing @run_date's type or removing the range filter breaks that.
--
-- Canonical definition: changes to audience criteria must be reflected in
--   docs/bigquery.md (assumptions & design decisions).

WITH searches AS (
    -- Aggregate activity first, before joining to profiles.
    -- HAVING filters here to keep only qualifying renters, reducing join input.
    -- Partition pruning on event_timestamp requires @run_date to resolve at plan time.
    SELECT
        renter_id,
        COUNT(*) AS search_count
    FROM
        renter_activity
    WHERE
        event_type = 'search'
        -- Closed-open window [run_date - 90d, run_date) excludes partial current-day
        -- data so results are stable across retries within the same run_date.
        AND event_timestamp >= TIMESTAMP(DATE_SUB(@run_date, INTERVAL 90 DAY))
        AND event_timestamp < TIMESTAMP(@run_date)
    GROUP BY
        renter_id
    HAVING
        COUNT(*) >= 3
),

qualified_profiles AS (
    -- Pre-filter profiles before the join to reduce scan cost.
    -- QUALIFY guard defends against duplicate renter_id rows (e.g. future SCD-2
    -- migration); assumption of uniqueness is documented in docs/bigquery.md §10.
    SELECT
        renter_id,
        email,
        phone,
        last_login
    FROM
        renter_profiles
    WHERE
        subscription_status = 'churned'
        -- Explicit TRUE required; NULL is treated as no consent.
        AND sms_consent = TRUE
        -- Phone must be present and non-empty.
        AND phone IS NOT NULL
        AND TRIM(phone) != ''
        -- "Inactive for 30+ days" is enforced at date-level granularity:
        -- last_login must be before midnight UTC of the day 30 days before run_date.
        -- A renter who logged in at 23:59 UTC on that day is excluded.
        -- This is intentional — day-level semantics match the run_date anchor.
        AND last_login IS NOT NULL
        AND last_login < TIMESTAMP(DATE_SUB(@run_date, INTERVAL 30 DAY))
        -- DATE() comparison matches the source doc intent: "dnd_until < run_date"
        -- as a date-level check, regardless of any time component in the column.
        AND (dnd_until IS NULL OR DATE(dnd_until) < @run_date)
    QUALIFY
        ROW_NUMBER() OVER (PARTITION BY renter_id ORDER BY last_login DESC) = 1
)

SELECT
    qp.renter_id,
    qp.email,
    qp.phone,
    qp.last_login,
    s.search_count,
    DATE_DIFF(@run_date, DATE(qp.last_login), DAY) AS days_since_login
FROM
    qualified_profiles qp
    INNER JOIN searches s USING (renter_id)
WHERE
    -- NOT EXISTS avoids output duplication when a renter has multiple suppression rows.
    NOT EXISTS (
        SELECT 1
        FROM suppression_list sl
        WHERE sl.renter_id = qp.renter_id
    )
