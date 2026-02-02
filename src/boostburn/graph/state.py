from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from ..config import AppConfig
from ..models import Metrics, Warnings
from ..state.manifest import ManifestState
from ..adapters.aws_s3 import S3Object


class GraphState(TypedDict, total=False):
    config: AppConfig
    report_date: str
    report_start: datetime
    report_end: datetime
    regions: List[str]
    buckets: Dict[str, str]
    region_index: int
    current_region: Optional[str]
    current_bucket: Optional[str]
    current_manifest: ManifestState
    current_manifest_etag: Optional[str]
    scan_prefixes: List[str]
    scan_end_datehour: Optional[str]
    objects: List[S3Object]
    new_objects: List[S3Object]
    metrics: Metrics
    warnings: Warnings
    stats: Dict[str, Any]
    report_message: str
    report_snapshot: Dict[str, object]
    report_generated_at: datetime
    report_snapshot_path: Optional[str]
    csv_report_path: Optional[str]
    slack_message: Optional[str]
