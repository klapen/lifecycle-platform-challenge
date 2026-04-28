import json
import os
from unittest.mock import patch

import pytest

from lifecycle_platform_challenge.pipeline.dedup import load_sent_log, persist_sent


def test_load_returns_empty_set_when_file_missing(tmp_path):
    result = load_sent_log(str(tmp_path / "sent.json"), "cmp1")
    assert result == set()


def test_load_returns_ids_for_campaign(tmp_path):
    log = tmp_path / "sent.json"
    log.write_text(json.dumps({"cmp1": ["r1", "r2", "r3"]}))
    assert load_sent_log(str(log), "cmp1") == {"r1", "r2", "r3"}


def test_load_returns_empty_set_for_unknown_campaign(tmp_path):
    log = tmp_path / "sent.json"
    log.write_text(json.dumps({"other_campaign": ["r1"]}))
    assert load_sent_log(str(log), "cmp1") == set()


def test_persist_creates_file(tmp_path):
    log = str(tmp_path / "sent.json")
    persist_sent(log, "cmp1", ["r1", "r2"])
    data = json.loads(open(log).read())
    assert set(data["cmp1"]) == {"r1", "r2"}


def test_persist_merges_with_existing_ids(tmp_path):
    log = tmp_path / "sent.json"
    log.write_text(json.dumps({"cmp1": ["r1", "r2"]}))
    persist_sent(str(log), "cmp1", ["r3", "r4"])
    data = json.loads(log.read_text())
    assert set(data["cmp1"]) == {"r1", "r2", "r3", "r4"}


def test_persist_deduplicates_ids(tmp_path):
    log = tmp_path / "sent.json"
    log.write_text(json.dumps({"cmp1": ["r1"]}))
    persist_sent(str(log), "cmp1", ["r1", "r2"])  # r1 already present
    data = json.loads(log.read_text())
    assert data["cmp1"].count("r1") == 1


def test_persist_does_not_affect_other_campaigns(tmp_path):
    log = tmp_path / "sent.json"
    log.write_text(json.dumps({"cmp2": ["r99"]}))
    persist_sent(str(log), "cmp1", ["r1"])
    data = json.loads(log.read_text())
    assert data["cmp2"] == ["r99"]


def test_persist_is_atomic_original_intact_on_failure(tmp_path):
    log = tmp_path / "sent.json"
    log.write_text(json.dumps({"cmp1": ["r1"]}))

    with patch("lifecycle_platform_challenge.pipeline.dedup.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            persist_sent(str(log), "cmp1", ["r2"])

    # Original file untouched.
    data = json.loads(log.read_text())
    assert data["cmp1"] == ["r1"]
