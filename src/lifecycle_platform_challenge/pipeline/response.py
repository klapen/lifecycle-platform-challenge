from enum import Enum


class ResponseStatus(Enum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_FAILURE = "permanent_failure"


def classify_response_status(status_code: int) -> ResponseStatus:
    if 200 <= status_code < 300:
        return ResponseStatus.SUCCESS
    if status_code == 429:
        return ResponseStatus.RATE_LIMITED
    if 500 <= status_code < 600:
        return ResponseStatus.TRANSIENT_ERROR
    return ResponseStatus.PERMANENT_FAILURE
