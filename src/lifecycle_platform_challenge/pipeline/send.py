import random
import time
from typing import Iterator

from lifecycle_platform_challenge.pipeline.dedup import load_sent_log, persist_sent
from lifecycle_platform_challenge.pipeline.esp import ESPClient
from lifecycle_platform_challenge.pipeline.logger import BatchLogger
from lifecycle_platform_challenge.pipeline.response import ResponseStatus, classify_response_status

BATCH_SIZE = 100
MAX_RETRIES = 5
BASE_DELAY = 1.0


def _chunked(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _compute_backoff(attempt: int, retry_after: float | None) -> float:
    # Jitter proportional to the delay window to spread retries across the full interval.
    exponential = BASE_DELAY * (2**attempt)
    jitter = random.uniform(0, exponential)
    if retry_after is not None:
        # Respect the server's directive; small jitter avoids thundering herd on resume.
        return retry_after + random.uniform(0, 1)
    return exponential + jitter


def _extract_retry_after(response) -> float | None:
    try:
        return float(response.headers.get("Retry-After"))
    except (AttributeError, TypeError, ValueError):
        return None


def _send_batch_with_retries(
    client: ESPClient,
    campaign_id: str,
    batch: list[dict],
    logger: BatchLogger,
) -> bool:
    for attempt in range(MAX_RETRIES):
        t0 = time.monotonic()
        try:
            response = client.send_batch(campaign_id, batch)
            latency_ms = (time.monotonic() - t0) * 1000
            status = response.status_code
            result = classify_response_status(status)

            logger.batch_attempt(batch_size=len(batch), attempt=attempt, status=status, latency_ms=latency_ms)

            if result is ResponseStatus.SUCCESS:
                return True

            if result is ResponseStatus.RATE_LIMITED:
                delay = _compute_backoff(attempt, _extract_retry_after(response))
                logger.rate_limited(attempt=attempt, delay=delay)
                time.sleep(delay)
                continue

            if result is ResponseStatus.TRANSIENT_ERROR:
                delay = _compute_backoff(attempt, None)
                logger.transient_error(attempt=attempt, status=status, delay=delay)
                time.sleep(delay)
                continue

            # PERMANENT_FAILURE: 4xx non-429, do not retry.
            logger.permanent_failure(attempt=attempt, status=status, batch_size=len(batch))
            return False

        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            delay = _compute_backoff(attempt, None)
            logger.batch_exception(attempt=attempt, exc=exc, delay=delay, latency_ms=latency_ms)
            time.sleep(delay)

    logger.retries_exhausted(batch_size=len(batch))
    return False


def execute_campaign_send(
    campaign_id: str,
    audience: list[dict],
    esp_client: ESPClient,
    sent_log_path: str = "sent_renters.json",
) -> dict:
    """Returns {'total_sent': int, 'total_failed': int, 'total_skipped': int, 'elapsed_seconds': float}"""
    start = time.monotonic()
    logger = BatchLogger(campaign_id)

    already_sent = load_sent_log(sent_log_path, campaign_id)
    to_send = [r for r in audience if r["renter_id"] not in already_sent]
    total_skipped = len(audience) - len(to_send)

    total_sent = 0
    total_failed = 0

    for batch in _chunked(to_send, BATCH_SIZE):
        success = _send_batch_with_retries(esp_client, campaign_id, batch, logger)
        if success:
            batch_ids = [r["renter_id"] for r in batch]
            try:
                # Persist per-batch: a mid-run crash loses at most the current
                # in-flight batch, not all progress since the run started.
                persist_sent(sent_log_path, campaign_id, batch_ids)
                total_sent += len(batch)
            except Exception as exc:
                # Sent to ESP but log write failed — recipients may be re-sent on retry.
                logger.persist_failed(exc=exc, batch_size=len(batch))
                total_failed += len(batch)
        else:
            logger.batch_dropped(batch_size=len(batch))
            total_failed += len(batch)

    return {
        "total_sent": total_sent,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
        "elapsed_seconds": time.monotonic() - start,
    }
