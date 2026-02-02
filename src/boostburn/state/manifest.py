from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import json
from typing import Dict, Optional, Tuple

from ..adapters.aws_s3 import S3Adapter


MANIFEST_VERSION = 1


@dataclass
class ManifestState:
    version: int = MANIFEST_VERSION
    last_datehour: Optional[str] = None
    processed: Dict[str, Dict[str, str]] = field(default_factory=dict)
    updated_at: Optional[str] = None
    lookback_hours: int = 6

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "last_datehour": self.last_datehour,
            "processed": self.processed,
            "updated_at": self.updated_at,
            "lookback_hours": self.lookback_hours,
        }


def load_manifest(
    s3: S3Adapter,
    bucket: str,
    key: str,
    lookback_hours: int,
) -> Tuple[ManifestState, Optional[str]]:
    etag = s3.get_object_etag(bucket, key)
    if etag is None:
        return ManifestState(lookback_hours=lookback_hours), None
    payload = s3.get_object_bytes(bucket, key)
    data = json.loads(payload.decode("utf-8"))
    manifest = ManifestState(
        version=data.get("version", MANIFEST_VERSION),
        last_datehour=data.get("last_datehour"),
        processed=data.get("processed", {}),
        updated_at=data.get("updated_at"),
        lookback_hours=int(data.get("lookback_hours", lookback_hours)),
    )
    return manifest, etag


def prune_manifest(manifest: ManifestState, now: datetime) -> ManifestState:
    cutoff = now - timedelta(hours=manifest.lookback_hours)
    pruned = {}
    for key, meta in manifest.processed.items():
        seen_at = meta.get("seen_at")
        if not seen_at:
            continue
        try:
            seen_dt = datetime.fromisoformat(seen_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if seen_dt >= cutoff:
            pruned[key] = meta
    manifest.processed = pruned
    return manifest


def record_processed(manifest: ManifestState, key: str, etag: str, seen_at: datetime) -> None:
    manifest.processed[key] = {"etag": etag, "seen_at": seen_at.astimezone(timezone.utc).isoformat()}


def update_last_datehour(manifest: ManifestState, datehour: Optional[str]) -> None:
    if datehour:
        manifest.last_datehour = datehour


def save_manifest(s3: S3Adapter, bucket: str, key: str, manifest: ManifestState) -> str:
    manifest.updated_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(manifest.to_dict(), sort_keys=True).encode("utf-8")
    return s3.put_object(bucket, key, payload, content_type="application/json")
