from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Dict, Optional

import yaml


@dataclass(frozen=True)
class AppConfig:
    regions: Dict[str, str]
    account_id: Optional[str] = None
    log_prefix: str = ""


def _normalize_bucket_name(value: str) -> str:
    bucket = value.strip()
    if bucket.startswith("s3://"):
        bucket = bucket[5:]
    if ".s3." in bucket:
        bucket = bucket.split(".s3.", 1)[0]
    return bucket.strip("/")


def _derive_account_id(buckets: Dict[str, str]) -> Optional[str]:
    ids = set()
    for name in buckets.values():
        match = re.search(r"\b(\d{12})\b", name)
        if match:
            ids.add(match.group(1))
    if len(ids) == 1:
        return next(iter(ids))
    return None


def load_config(path: str | Path) -> AppConfig:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict) or "regions" not in data:
        raise ValueError("Config must contain a 'regions' mapping")
    regions_raw = data["regions"]
    if not isinstance(regions_raw, dict) or not regions_raw:
        raise ValueError("'regions' must be a non-empty mapping")
    regions = {region: _normalize_bucket_name(bucket) for region, bucket in regions_raw.items()}
    account_id = data.get("account_id") or _derive_account_id(regions)
    log_prefix = data.get("log_prefix", "") or ""
    return AppConfig(regions=regions, account_id=account_id, log_prefix=log_prefix.strip("/"))
