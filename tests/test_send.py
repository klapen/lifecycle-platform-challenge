import json
import os
from unittest.mock import MagicMock, patch

import pytest

from lifecycle_platform_challenge.pipeline.send import execute_campaign_send


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audience(n: int, prefix: str = "r") -> list[dict]:
    return [{"renter_id": f"{prefix}{i}", "phone": f"+1555{i:07d}"} for i in range(n)]


def _resp(status: int, headers: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    return r


def _client(*responses):
    client = MagicMock()
    client.send_batch.side_effect = list(responses)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path(tmp_path):
    log = str(tmp_path / "sent.json")
    esp = _client(*[_resp(200)] * 3)  # 3 batches: 100, 100, 50

    result = execute_campaign_send("cmp1", _audience(250), esp, log)

    assert result == {"total_sent": 250, "total_failed": 0, "total_skipped": 0,
                      "elapsed_seconds": pytest.approx(result["elapsed_seconds"])}
    assert esp.send_batch.call_count == 3


def test_dedup_filter(tmp_path):
    log_path = tmp_path / "sent.json"
    audience = _audience(100)
    log_path.write_text(json.dumps({"cmp1": sorted(r["renter_id"] for r in audience[:50])}))
    esp = _client(_resp(200))

    result = execute_campaign_send("cmp1", audience, esp, str(log_path))

    assert result["total_skipped"] == 50
    assert result["total_sent"] == 50
    assert esp.send_batch.call_count == 1


def test_dedup_persistence(tmp_path):
    log = str(tmp_path / "sent.json")
    audience = _audience(10)
    execute_campaign_send("cmp1", audience, _client(_resp(200)), log)

    data = json.loads(open(log).read())
    assert set(data["cmp1"]) == {r["renter_id"] for r in audience}


@pytest.mark.parametrize("retryable_status", [429, 503])
def test_retries_on_retryable_status(tmp_path, retryable_status):
    log = str(tmp_path / "sent.json")
    esp = _client(_resp(retryable_status), _resp(200))

    with patch("lifecycle_platform_challenge.pipeline.send.time.sleep"), \
         patch("lifecycle_platform_challenge.pipeline.send.random.uniform", return_value=0):
        result = execute_campaign_send("cmp1", _audience(5), esp, log)

    assert result["total_sent"] == 5
    assert result["total_failed"] == 0
    assert esp.send_batch.call_count == 2


def test_retry_after_header_honored(tmp_path):
    log = str(tmp_path / "sent.json")
    esp = _client(_resp(429, {"Retry-After": "2"}), _resp(200))

    with patch("lifecycle_platform_challenge.pipeline.send.random.uniform", return_value=0), \
         patch("lifecycle_platform_challenge.pipeline.send.time.sleep") as mock_sleep:
        execute_campaign_send("cmp1", _audience(5), esp, log)

    mock_sleep.assert_any_call(2.0)


@pytest.mark.parametrize("retryable_status", [429, 503])
def test_retry_exhaustion(tmp_path, retryable_status):
    log = str(tmp_path / "sent.json")
    esp = _client(*[_resp(retryable_status)] * 5)

    with patch("lifecycle_platform_challenge.pipeline.send.time.sleep"), \
         patch("lifecycle_platform_challenge.pipeline.send.random.uniform", return_value=0):
        result = execute_campaign_send("cmp1", _audience(5), esp, log)

    assert result["total_failed"] == 5
    assert result["total_sent"] == 0
    assert not os.path.exists(log)


@pytest.mark.parametrize("status_code", [400, 401, 403, 422])
def test_no_retry_on_non_retryable_4xx(tmp_path, status_code):
    log = str(tmp_path / "sent.json")
    esp = _client(_resp(status_code))

    result = execute_campaign_send("cmp1", _audience(5), esp, log)

    assert result["total_failed"] == 5
    assert result["total_sent"] == 0
    assert esp.send_batch.call_count == 1


def test_partial_failure_across_batches(tmp_path):
    log = str(tmp_path / "sent.json")
    audience = _audience(200)
    esp = _client(_resp(200), _resp(400))

    result = execute_campaign_send("cmp1", audience, esp, log)

    assert result["total_sent"] == 100
    assert result["total_failed"] == 100
    data = json.loads(open(log).read())
    assert set(data["cmp1"]) == {r["renter_id"] for r in audience[:100]}


def test_empty_audience_all_deduped(tmp_path):
    log_path = tmp_path / "sent.json"
    audience = _audience(20)
    log_path.write_text(json.dumps({"cmp1": sorted(r["renter_id"] for r in audience)}))
    esp = MagicMock()

    result = execute_campaign_send("cmp1", audience, esp, str(log_path))

    assert result["total_skipped"] == 20
    assert result["total_sent"] == 0
    esp.send_batch.assert_not_called()


def test_elapsed_seconds(tmp_path):
    log = str(tmp_path / "sent.json")
    esp = _client(_resp(200))

    # Calls: start, t0 inside batch, latency read inside batch, final elapsed.
    with patch("lifecycle_platform_challenge.pipeline.send.time.monotonic", side_effect=[0.0, 0.0, 0.0, 1.5]):
        result = execute_campaign_send("cmp1", _audience(5), esp, log)

    assert result["elapsed_seconds"] == pytest.approx(1.5)


def test_atomic_persistence_on_replace_failure(tmp_path):
    log = str(tmp_path / "sent.json")
    audience = _audience(200)
    esp = _client(_resp(200), _resp(200))

    original_replace = os.replace
    call_count = {"n": 0}

    def fail_on_second(src, dst):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("simulated crash")
        return original_replace(src, dst)

    with patch("lifecycle_platform_challenge.pipeline.dedup.os.replace", side_effect=fail_on_second):
        with pytest.raises(OSError, match="simulated crash"):
            execute_campaign_send("cmp1", audience, esp, log)

    data = json.loads(open(log).read())
    assert len(data["cmp1"]) == 100
    assert set(data["cmp1"]) == {r["renter_id"] for r in audience[:100]}
