# Part 1 — Audience Segmentation Query (SQL)

## Schema

```sql
CREATE TABLE renter_activity (
  renter_id STRING,
  event_type STRING,        -- 'page_view', 'search', 'application_start', 'application_complete', 'lease_signed'
  event_timestamp TIMESTAMP,
  property_id STRING,
  channel STRING,           -- 'web', 'ios', 'android'
  utm_source STRING
);

CREATE TABLE renter_profiles (
  renter_id STRING,
  email STRING,
  phone STRING,
  last_login TIMESTAMP,
  subscription_status STRING,  -- 'active', 'churned', 'never_subscribed'
  sms_consent BOOLEAN,
  email_consent BOOLEAN,
  dnd_until TIMESTAMP,         -- Do Not Disturb until this date (NULL = no restriction)
  created_at TIMESTAMP
);

CREATE TABLE suppression_list (
  renter_id STRING,
  suppression_reason STRING,  -- 'unsubscribed', 'bounced', 'complained', 'dnc_registry'
  suppressed_at TIMESTAMP
);
```

## Task

Write a BigQuery query that builds the audience for an **SMS reactivation campaign** with the following criteria:

1. Last login was more than 30 days ago
2. Subscription status is `'churned'`
3. Renter has performed **at least 3 searches** in the past 90 days (showing latent intent)
4. Renter has a phone number on file
5. Renter has `sms_consent = TRUE`
6. Renter is NOT in the suppression list
7. Renter's `dnd_until` is either NULL or in the past
8. The query must be **idempotent** — running it twice on the same day produces the same result

Return: `renter_id`, `email`, `phone`, `last_login`, `search_count`, `days_since_login`

## Evaluation Criteria

- Correct joins and filtering logic
- Proper NULL handling (`phone`, `dnd_until`)
- Use of `CURRENT_TIMESTAMP()` or parameterized date for idempotency
- Suppression list exclusion (`LEFT JOIN + IS NULL` or `NOT EXISTS`)
- Clean, readable SQL

## Part 1 - Assumptions & Design Decisions

### 1. Deterministic Execution (Idempotency)
- The query uses a fixed `run_date` parameter provided by Airflow.
- No use of `CURRENT_TIMESTAMP()` or dynamic “now” values.
- Running the query multiple times on the same `run_date` must return identical results.

---

### 2. Data Freshness & Stability
- Source tables (especially `renter_activity`) may receive new data during the day.
- The query applies a strict cutoff based on `run_date` to avoid drift between executions.
- Recommended approach: materialize results into a staging table per `run_date`.

---

### 3. Time Window Definitions
- “Past 90 days” is interpreted as a fixed window relative to `run_date`.
- The window excludes partial current-day data to ensure consistency.

---

### 4. `last_login` Handling
- `last_login IS NULL` does not qualify as “more than 30 days ago”.
- Only users with a valid timestamp are considered.

---

### 5. Consent Logic
- `sms_consent` must be explicitly `TRUE`.
- `NULL` is treated as no consent.

---

### 6. Phone Validity
- A valid phone is defined as:
  - `phone IS NOT NULL`
  - `TRIM(phone) != ''`
- No further validation (e.g., E.164) is assumed due to schema limitations.

---

### 7. Do Not Disturb (`dnd_until`)
- Evaluated against `run_date` (not execution time).
- Users are eligible only if:
  - `dnd_until IS NULL`, or
  - `dnd_until < run_date`

---

### 8. Suppression List
- Any user present in `suppression_list` is excluded.
- `NOT EXISTS` is used to avoid duplication issues from multiple suppression records.

---

### 9. Event Deduplication Limitation
- `renter_activity` includes `renter_id` but no `event_id`.
- Event-level deduplication is not possible.
- Assumption: each row represents a valid unique event.

---

### 10. Profile Uniqueness
- Assumes `renter_profiles` contains one current row per `renter_id`.
- No deduplication logic is applied at the profile level.

---

### 11. Query Execution Strategy
- Aggregations (e.g., search count) are computed before joins.
- This minimizes data scanned and improves performance.

---

### 12. BigQuery Performance Considerations
- Assumes `renter_activity` is large and partitioned by `event_timestamp`.
- Filtering by time is applied early to reduce scan cost.
- Clustering by `event_type` and `renter_id` is recommended.

---

### 13. Output Materialization
- Query results should be written to a staging table:
  - Partitioned by `run_date`
  - Includes campaign metadata
- Downstream systems should consume the materialized dataset, not rerun the query.

---

### 14. Timezone Assumption
- All time-based logic is evaluated in UTC.
- No timezone normalization is applied.

---

### 15. Event Semantics
- `event_type = 'search'` is assumed to represent a valid user search.
- No additional validation or filtering is applied.
