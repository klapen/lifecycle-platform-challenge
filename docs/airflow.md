# Part 3 — Airflow DAG Skeleton (Python)

Write an Airflow DAG definition that orchestrates the full campaign pipeline:

1. **Task 1** — Run the BigQuery audience query and export results to a staging table
2. **Task 2** — Validate the audience (count > 0, no obvious anomalies like audience > 2× historical average)
3. **Task 3** — Execute the campaign send (using the function from Part 2)
4. **Task 4** — Log results to a reporting table and send a Slack notification with the summary

## Requirements

- Schedule: Daily at 5:00 AM UTC
- Retries: 2 per task, 5-minute delay between retries
- Task dependencies: linear (1 → 2 → 3 → 4)
- SLA: Alert if the DAG hasn't completed by 8:00 AM UTC
- Use `@task` decorator or `PythonOperator` — either is fine

## Evaluation Criteria

- Correct DAG structure and task dependencies
- Proper retry and SLA configuration
- Validation step (not blindly sending)
- Clean separation of concerns between tasks
- Understanding of Airflow patterns (XComs, task flow, etc.)

# Part 3 — Assumptions & Design Decisions

## 1. Execution Model
- The DAG runs daily at **5:00 AM UTC**.
- `run_date` is derived from Airflow’s `logical_date`.
- All time-based logic must rely on `run_date`, not system time.

---

## 2. Task Structure

```
build_audience
- validate_audience
→ execute_campaign_send
→ log_results_and_notify
```

- Each task represents a clear stage in the pipeline.
- No task should combine multiple responsibilities.

---

## 3. Audience Materialization
- The audience is computed once in BigQuery.
- Results are written to a staging table.
- All downstream tasks read from this table.
- This ensures:
  - deterministic retries
  - reproducibility
  - auditability

---

## 4. Idempotent Execution
- The DAG must guarantee that no renter receives the same campaign twice.
- Deduplication key:

```
campaign_id + renter_id
```

- This must be enforced inside the send task.

---

## 5. Retry Strategy
- Each task is configured with:
  - `retries = 2`
  - `retry_delay = 5 minutes`

- The send task follows an **incremental retry strategy**:
  - Each retry only processes recipients that have **not been successfully sent yet**
  - Successfully processed renters are persisted in the sent log
  - Subsequent retries skip already-sent renters and continue from the remaining subset

- This ensures:
  - no duplicate sends across retries
  - forward progress on partial failures
  - resilience to batch-level errors

- Assumption:
  - The sent log is updated only after successful API responses
  - The remaining audience is recomputed on each retry by excluding already-sent renters

---

## 6. Deduplication (Exercise Constraint)
- A file-based log (`sent_renters.json`) is used.
- This file tracks all successfully sent recipients.
- Assumption:
  - single-node execution
  - not production-safe

---

## 7. Audience Validation
- Must run before sending.
- Conditions:
  - `audience_count > 0`
  - `audience_count <= 2x historical average`

If validation fails:
- stop the pipeline
- do not send messages
- notify via Slack

---

## 8. Batching
- ESP API limit: **100 recipients per request**
- The send task must:
  - enforce batch size
  - split audience into chunks

---

## 9. Rate Limiting
- Handle HTTP 429 errors:
  - exponential backoff
  - jitter
  - maximum 5 retries per batch

---

## 10. Partial Failures
- A failed batch must not stop the DAG.
- The pipeline continues processing remaining batches.
- Must track:
  - sent
  - failed
  - skipped

---

## 11. Send Confirmation
- A recipient is marked as sent only after a successful API response.
- Failed attempts must not be recorded as sent.

---

## 12. SLA
- The DAG must complete before **8:00 AM UTC**.
- Total execution window: **3 hours**
- SLA breaches should trigger alerts.

---

## 13. XCom Usage
- Only small metadata is passed via XCom:
  - `campaign_id`
  - `run_date`
  - `staging_table`
  - `audience_count`
- Large datasets must not be passed via XCom.

---

## 14. Reporting & Notification
- Final task must:
  - persist execution results
  - send Slack notification

Fields to store:

```

campaign_id
run_date
audience_count
total_sent
total_failed
total_skipped
elapsed_seconds
dag_run_id

```

---

## 15. Responsibility Split

```

BigQuery:

* audience computation

Python (send module):

* batching
* ESP integration
* retries
* deduplication

Airflow:

* orchestration
* scheduling
* validation
* retries
* reporting

```

---

## 16. Manual Reruns
- Manual DAG reruns must not trigger duplicate sends.
- Deduplication logic ensures safe re-execution.

---

## 17. Known Limitations
- File-based deduplication is not safe for distributed environments.
- No transactional guarantees between send and log.
- No distributed locking.
- No ESP idempotency keys.

---

## 18. ESP API Assumptions (Iterable)

The SMS provider is assumed to behave similarly to Iterable’s API.

---

### Request Model
- Messages are sent via Iterable’s messaging API (e.g., `/api/sms/target` or batch endpoints).
- Requests are synchronous and return an HTTP status.
- The API accepts batched recipients (up to 100 per request as per exercise constraint).

---

### Success Criteria
- HTTP `2xx` indicates the request was accepted by Iterable.
- Acceptance means messages are queued for delivery, not necessarily delivered.

---

### Rate Limiting (HTTP 429)
- Iterable enforces rate limits per API key.
- HTTP `429` is returned when the rate limit is exceeded.

Behavior:
- May include `Retry-After` header (not guaranteed).
- Limits are typically burst-based and recover over time.

Handling strategy:
- Use exponential backoff with jitter.
- If `Retry-After` is present, respect it.
- Retry up to 5 times per batch.

Example backoff:
```

base_delay = 1s
delay = base_delay * (2 ^ attempt) + jitter

```

---

### Error Handling
- `429` → retryable (rate limit)
- `5xx` → retryable (transient server error)
- `4xx` (non-429) → non-retryable (bad request, invalid data)

---

### Idempotency
- Iterable APIs do **not provide strict idempotency guarantees** for message sends.
- Duplicate requests may result in duplicate messages.

Therefore:
- Idempotency must be enforced client-side.
- Deduplication key:

```

campaign_id + renter_id

```

---

### Partial Failures
- Iterable batch APIs typically return a single status per request.
- No guaranteed per-recipient success breakdown in this simplified model.

Assumption:
- If the request fails, all recipients in the batch are treated as failed.

---

### Timeouts & Unknown State
- If a request times out or connection fails:
  - The delivery state is unknown
  - The system assumes failure and retries

Risk:
- Possible duplicate sends if the request actually succeeded but response was lost.

Mitigation (not implemented in exercise):
- Provider-side idempotency keys
- Delivery callbacks / reconciliation jobs

---

### Ordering
- Iterable does not guarantee message ordering.
- Ordering is not required for this campaign.

---

### Observability
Each batch request should log:
- batch size
- attempt number
- response status
- latency
- error message (if any)

---

### Production Considerations
In a production system using Iterable:
- Use messageId / campaign tracking for reconciliation
- Store provider response IDs
- Use webhooks for delivery and failure tracking
- Implement stronger idempotency guarantees
```

