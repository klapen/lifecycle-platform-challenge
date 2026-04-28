import logging


class BatchLogger:
    def __init__(self, campaign_id: str) -> None:
        self._log = logging.getLogger(__name__)
        self._campaign_id = campaign_id

    def batch_attempt(self, *, batch_size: int, attempt: int, status: int, latency_ms: float) -> None:
        self._log.info(
            "batch_attempt campaign_id=%s batch_size=%d attempt=%d status=%d latency_ms=%.1f",
            self._campaign_id, batch_size, attempt, status, latency_ms,
        )

    def rate_limited(self, *, attempt: int, delay: float) -> None:
        self._log.warning(
            "rate_limited campaign_id=%s attempt=%d sleeping=%.2fs",
            self._campaign_id, attempt, delay,
        )

    def transient_error(self, *, attempt: int, status: int, delay: float) -> None:
        self._log.warning(
            "transient_error campaign_id=%s attempt=%d status=%d sleeping=%.2fs",
            self._campaign_id, attempt, status, delay,
        )

    def permanent_failure(self, *, attempt: int, status: int, batch_size: int) -> None:
        self._log.error(
            "batch_permanent_failure campaign_id=%s attempt=%d status=%d batch_size=%d",
            self._campaign_id, attempt, status, batch_size,
        )

    def batch_exception(self, *, attempt: int, exc: Exception, delay: float, latency_ms: float) -> None:
        self._log.warning(
            "batch_exception campaign_id=%s attempt=%d error=%s sleeping=%.2fs latency_ms=%.1f",
            self._campaign_id, attempt, exc, delay, latency_ms,
        )

    def retries_exhausted(self, *, batch_size: int) -> None:
        self._log.error(
            "batch_retries_exhausted campaign_id=%s batch_size=%d",
            self._campaign_id, batch_size,
        )

    def batch_dropped(self, *, batch_size: int) -> None:
        self._log.error(
            "batch_dropped campaign_id=%s batch_size=%d",
            self._campaign_id, batch_size,
        )
