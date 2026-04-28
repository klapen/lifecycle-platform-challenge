# Step 2 — Python Send Pipeline

## Goal

Implement `execute_campaign_send()` — the module that takes the materialized audience and sends it through the ESP in batches, handling rate limiting, dedup, and partial failures, while never aborting on a single batch failure.

## Source doc

[../pipeline-orchestration.md](../pipeline-orchestration.md) — both the original problem statement and the assumption list. The function signature is exercise-mandated and **must not change**.

## Key constraints from source

- **Signature (do not modify):**
  ```python
  def execute_campaign_send(
      campaign_id: str,
      audience: list[dict],
      esp_client: ESPClient,
      sent_log_path: str = "sent_renters.json",
  ) -> dict:
      """Returns {'total_sent': int, 'total_failed': int, 'total_skipped': int, 'elapsed_seconds': float}"""
  ```
- **`ESPClient.send_batch(campaign_id, recipients) -> Response`** is the only ESP entry point. We do not modify or wrap the class beyond what the function needs.
- **Batch size:** 100 recipients per request.
- **Dedup:** `sent_renters.json` contains `renter_id`s already sent for this `campaign_id`. Filter the audience against it before batching; record successes back to the file. Composite key is conceptually `campaign_id + renter_id`, so the file should be either keyed by `campaign_id` (`{"campaign_id": [...renter_ids]}`) or scoped to a single campaign per file. Choose the keyed-by-campaign-id form so multiple campaigns can share a path.
- **Rate limiting (HTTP 429):** Exponential backoff with jitter. Max 5 retries per batch. Respect `Retry-After` header when present.
- **Status code semantics (per `docs/airflow.md` §"ESP API Assumptions"):**
  - `2xx` → success
  - `429` → retryable (rate limit)
  - `5xx` → retryable (transient)
  - `4xx` (non-429) → non-retryable (bad request)
  - timeout / connection error → treat as failure (will retry within budget)
- **Partial failures:** A failed batch must not abort the run. Continue with remaining batches.
- **Send confirmation:** Mark a renter as sent only after a `2xx`. On failure, do not append to the dedup log.
- **Per-batch granularity:** Iterable batches return a single status — if a batch fails, all recipients in that batch are counted as failed (not partially sent).
- **Logging:** Each batch attempt logs batch size, attempt number, response status, latency, error message.

## Files to create

```
src/pipeline/__init__.py        # already exists from Step 0
src/pipeline/send.py            # main module
src/pipeline/esp.py             # ESPClient stub class (provided interface) for typing/imports
tests/test_send.py              # pytest suite
```

## Implementation outline (`src/pipeline/send.py`)

Internal helpers (private, prefixed `_`):

- `_load_sent_log(path, campaign_id) -> set[str]` — returns previously-sent renter_ids for this campaign. Missing file → empty set. Corrupt file → raise (we do not silently overwrite history).
- `_persist_sent(path, campaign_id, renter_ids) -> None` — append-merge into the JSON, write atomically (write to `path + ".tmp"` then `os.replace`).
- `_chunked(iterable, size)` — yields lists of length ≤ `size`.
- `_compute_backoff(attempt, retry_after) -> float` — `min(retry_after, base * 2**attempt + jitter)` if `retry_after` present, else `base * 2**attempt + jitter`. `base = 1.0`, `jitter = uniform(0, 1)`.
- `_send_batch_with_retries(client, campaign_id, batch) -> bool` — up to 5 attempts. Returns True on first 2xx; False on permanent failure or retries exhausted. Logs each attempt.

Public function flow:
1. Record `start = time.monotonic()`.
2. Load already-sent set; filter audience → `(to_send, skipped_count)`.
3. Chunk `to_send` into batches of 100.
4. For each batch:
   - Call `_send_batch_with_retries`
   - On success: collect `renter_id`s as newly sent, increment `total_sent`
   - On failure: increment `total_failed` by batch size; log batch context for manual retry
5. After all batches: persist newly-sent ids in one write (single fsync, not per-batch — but consider per-batch persistence for crash safety; default to per-batch persistence to reduce data loss on mid-run crash).
6. Return metrics dict including `elapsed_seconds = time.monotonic() - start`.

**Decision: persist per-batch.** Crash safety > write throughput at this volume. Document this in a one-line code comment if non-obvious.

## Tests (`tests/test_send.py`)

Use `pytest-mock` (`mocker`) and a fake `ESPClient` (or `MagicMock`) with a configurable `send_batch` side effect. Tempdir for `sent_log_path` (`tmp_path` fixture).

Required tests:

1. **Happy path** — 250 recipients, all 200 OK → 3 batches (100/100/50), `total_sent = 250`, `total_failed = 0`, `total_skipped = 0`.
2. **Dedup filter** — pre-populate `sent_renters.json` with 50 ids overlapping the audience; expect `total_skipped = 50` and only the unsent batched.
3. **Dedup persistence** — after a successful run, the JSON contains every newly-sent id under the campaign key.
4. **Retry on 429** — first attempt returns 429 (no `Retry-After`), second returns 200. Single batch, eventually succeeds, `total_sent` matches batch size. Patch `time.sleep` and `random.uniform` to keep test fast and deterministic.
5. **`Retry-After` honored** — 429 with `Retry-After: 2` → assert sleep called with 2 (or near 2 with jitter — pick the form your `_compute_backoff` produces).
6. **Retry exhaustion** — 5 consecutive 429s on the same batch → batch counted as failed, no ids persisted, run continues.
7. **Retry on 5xx** — same as #4 but with 503.
8. **No retry on 4xx (non-429)** — first attempt returns 400 → no retry, batch marked failed.
9. **Partial failure across batches** — 200 recipients in 2 batches; first batch 200, second batch 4xx → `total_sent = 100`, `total_failed = 100`, only first batch persisted.
10. **Empty audience** — all recipients already sent → 0 batches dispatched, returns zero counts (with `total_skipped` = audience size).
11. **`elapsed_seconds` is non-negative and increasing across runs** — patch `time.monotonic` to return `[0, 1.5]` and assert `elapsed_seconds == 1.5`.
12. **Atomic persistence** — simulate a crash mid-write by patching `os.replace` to raise on second batch; first batch's ids should still be on disk (verifies temp-file pattern).

Run:
```bash
uv run pytest tests/test_send.py -v
```

## Done when

- All 12 tests pass
- `execute_campaign_send` signature exactly matches the source doc
- `sent_renters.json` is keyed by `campaign_id` and persisted per-batch
- Logs for failed batches include enough context (campaign_id, attempt, status code, recipient_ids count) to retry manually

## Commit checkpoint

Before committing: show the user the test run output (`uv run pytest tests/test_send.py -v`) and a short walkthrough of `send.py`. Wait for explicit approval. Suggested commit message:

```
feat(pipeline): add execute_campaign_send with batching, dedup, and 429/5xx retry
```
