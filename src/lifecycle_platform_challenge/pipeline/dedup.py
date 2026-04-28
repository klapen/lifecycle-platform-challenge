import json
import os
from pathlib import Path


def load_sent_log(path: str, campaign_id: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    with p.open() as f:
        data = json.load(f)
    return set(data.get(campaign_id, []))


def persist_sent(path: str, campaign_id: str, renter_ids: list[str]) -> None:
    p = Path(path)
    data: dict = json.loads(p.read_text()) if p.exists() else {}
    existing = set(data.get(campaign_id, []))
    data[campaign_id] = sorted(existing | set(renter_ids))
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    # Atomic replace: if this raises, the original file is untouched.
    os.replace(tmp, path)
