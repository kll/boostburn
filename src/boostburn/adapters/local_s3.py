from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .aws_s3 import S3Adapter, S3Object


@dataclass
class LocalBucket:
    name: str
    root: Path


class LocalS3Adapter(S3Adapter):
    def __init__(self, buckets: Dict[str, Path]) -> None:
        self._buckets = {name: Path(path) for name, path in buckets.items()}

    def list_objects(self, bucket: str, prefix: str) -> List[S3Object]:
        root = self._bucket_root(bucket)
        objects: List[S3Object] = []
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            key = path.relative_to(root).as_posix()
            if not key.startswith(prefix):
                continue
            stat = path.stat()
            etag = f"{stat.st_size}-{int(stat.st_mtime)}"
            objects.append(
                S3Object(key=key, etag=etag, last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))
            )
        return objects

    def get_object_bytes(self, bucket: str, key: str) -> bytes:
        root = self._bucket_root(bucket)
        path = root / key
        return path.read_bytes()

    def put_object(self, bucket: str, key: str, body: bytes, content_type: str = "application/json") -> str:
        root = self._bucket_root(bucket)
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        stat = path.stat()
        return f"{stat.st_size}-{int(stat.st_mtime)}"

    def get_object_etag(self, bucket: str, key: str) -> Optional[str]:
        root = self._bucket_root(bucket)
        path = root / key
        if not path.exists():
            return None
        stat = path.stat()
        return f"{stat.st_size}-{int(stat.st_mtime)}"

    def _bucket_root(self, bucket: str) -> Path:
        if bucket not in self._buckets:
            raise KeyError(f"Unknown bucket: {bucket}")
        return self._buckets[bucket]
