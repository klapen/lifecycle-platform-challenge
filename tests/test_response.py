import pytest

from lifecycle_platform_challenge.pipeline.response import ResponseStatus, classify_response_status


@pytest.mark.parametrize("status_code", [200, 201, 204, 299])
def test_2xx_is_success(status_code):
    assert classify_response_status(status_code) is ResponseStatus.SUCCESS


def test_429_is_rate_limited():
    assert classify_response_status(429) is ResponseStatus.RATE_LIMITED


@pytest.mark.parametrize("status_code", [500, 502, 503, 504, 599])
def test_5xx_is_transient_error(status_code):
    assert classify_response_status(status_code) is ResponseStatus.TRANSIENT_ERROR


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_4xx_non_429_is_permanent_failure(status_code):
    assert classify_response_status(status_code) is ResponseStatus.PERMANENT_FAILURE
