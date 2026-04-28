# Part 2 — Pipeline Orchestration (Python)

Write a Python module that processes the audience query result and sends it to an ESP API.

## Requirements

1. **Batching** — The ESP API accepts a maximum of 100 recipients per request
2. **Rate Limiting** — The ESP returns HTTP 429 when rate-limited; implement exponential backoff with jitter (max 5 retries)
3. **Deduplication** — Ensure no renter receives the same campaign twice if the pipeline is re-run; use a simple file-based approach
4. **Error Handling** — Log failed batches with enough context to retry manually; do not let one failed batch stop the entire pipeline
5. **Metrics** — Track and return a summary: total sent, total failed, total skipped (deduped), total time

## Provided Interface (do not modify)

```python
class ESPClient:
    def send_batch(self, campaign_id: str, recipients: list[dict]) -> Response:
        """Sends a batch of recipients to the ESP.
        Returns a Response with .status_code and .json()"""
        pass
```

## Deliverable

```python
def execute_campaign_send(
    campaign_id: str,
    audience: list[dict],
    esp_client: ESPClient,
    sent_log_path: str = "sent_renters.json"
) -> dict:
    """Returns {'total_sent': int, 'total_failed': int, 'total_skipped': int, 'elapsed_seconds': float}"""
```

## Evaluation Criteria

- Clean batching logic
- Correct exponential backoff with jitter
- Idempotency mechanism (checks previously sent `renter_id`s)
- Graceful error handling (no single batch failure aborts the run)
- Logging quality (structured, actionable)
- Code readability and structure

## Part 2 = Pipeline Orchestration Assumptions & Design Decisions

### 1. Execution Schedule
- Runs daily at 5:00 AM UTC
- Uses fixed run_date from Airflow

---

### 2. Idempotency
- No renter receives same campaign twice
- Key: `campaign_id + renter_id`

---

### 3. Audience Materialization
- BigQuery writes to staging table
- Downstream uses snapshot

---

### 4. Task Separation
- Calculate → Validate → Send → Report

---

### 5. Deduplication
- File-based (sent_renters.json)
- Not production-safe

---

### 6. Batching
- Max 100 recipients per request

---

### 7. Rate Limiting
- Retry on 429 with exponential backoff

---

### 8. Partial Failures
- Continue processing other batches

---

### 9. Send Confirmation
- Mark sent only after successful response

---

### 10. Validation
- `audience_count > 0`
- `<= 2x` historical average

---

### 11. SLA
- Must finish before 8:00 AM UTC

---

### 12. Airflow Retries
- 2 retries, 5-minute delay

---

### 13. Reporting
- campaign_id, run_date, sent, failed, etc.

---

### 14. Responsibilities
- BigQuery: data
- Python: send logic
- Airflow: orchestration

---

### 15. Limitations
- File dedupe
- No transactional guarantees
