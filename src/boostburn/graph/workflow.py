from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional

from langgraph.graph import END, StateGraph

from ..adapters.aws_s3 import S3Adapter, S3Object
from ..adapters.pricing import PricingProvider
from ..adapters.report_store import ReportStore
from ..adapters.slack import SlackAdapter, SlackWebhookAdapter
from ..config import AppConfig, load_config
from ..ingest.bedrock_parser import (
    _maybe_decompress,
    extract_token_counts,
    normalize_model_id,
    parse_bedrock_records,
    parse_timestamp,
)
from ..logging_utils import log_event
from ..models import Metrics, TokenStats, Warnings
from ..reporting import CSV_FIELDS, build_csv_row, build_report_snapshot, format_report
from ..state.manifest import (
    ManifestState,
    load_manifest,
    prune_manifest,
    record_processed,
    save_manifest,
    update_last_datehour,
)
from .state import GraphState


@dataclass(frozen=True)
class Dependencies:
    s3: S3Adapter
    pricing: PricingProvider
    report_store: ReportStore
    slack: Optional[SlackAdapter]
    logger: object


@dataclass(frozen=True)
class RunConfig:
    config_path: str
    manifest_prefix: str = "manifests"
    lookback_hours: int = 6
    report_date: Optional[str] = None
    log_prefix_override: Optional[str] = None
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    debug: bool = False
    force_reprocess: bool = False


def build_graph(deps: Dependencies, run_config: RunConfig):
    def load_config_node(state: GraphState) -> GraphState:
        config = load_config(run_config.config_path)
        if run_config.log_prefix_override is not None:
            config = replace(config, log_prefix=run_config.log_prefix_override.strip("/"))
        now = run_config.now_fn()
        report_date = run_config.report_date or now.date().isoformat()
        report_start = datetime.fromisoformat(report_date).replace(tzinfo=timezone.utc)
        report_end = report_start + timedelta(days=1)
        regions = list(config.regions.keys())
        state.update(
            {
                "config": config,
                "report_date": report_date,
                "report_start": report_start,
                "report_end": report_end,
                "regions": regions,
                "buckets": config.regions,
                "region_index": 0,
                "metrics": Metrics(),
                "warnings": Warnings(),
                "stats": {
                    "objects_listed": 0,
                    "objects_filtered": 0,
                    "objects_processed": 0,
                    "records_parsed": 0,
                    "records_used": 0,
                },
            }
        )
        log_event(deps.logger, "load_config", regions=len(regions), report_date=report_date)
        return state

    def region_router(state: GraphState) -> GraphState:
        index = state["region_index"]
        regions = state["regions"]
        if index < len(regions):
            region = regions[index]
            state["current_region"] = region
            state["current_bucket"] = state["buckets"][region]
        return state

    def refresh_pricing_node(state: GraphState) -> GraphState:
        # Use original model IDs (with inference profile prefixes) for pricing filter
        metrics = state["metrics"]
        model_ids = {metrics.model_id_map.get(norm_id, norm_id) for norm_id in metrics.by_model.keys()}
        if model_ids:
            deps.pricing.refresh(model_ids=model_ids)
            log_event(deps.logger, "refresh_pricing", models=len(model_ids))
        else:
            log_event(deps.logger, "refresh_pricing_skipped")
        return state

    def apply_pricing_node(state: GraphState) -> GraphState:
        state["metrics"].apply_pricing(deps.pricing, state["warnings"])
        log_event(deps.logger, "apply_pricing")
        return state

    def load_manifest_node(state: GraphState) -> GraphState:
        bucket = state["current_bucket"]
        manifest_key = _manifest_key(run_config.manifest_prefix)
        manifest, etag = load_manifest(
            deps.s3,
            bucket,
            manifest_key,
            lookback_hours=run_config.lookback_hours,
        )
        manifest.lookback_hours = run_config.lookback_hours
        state["current_manifest"] = manifest
        state["current_manifest_etag"] = etag
        log_event(deps.logger, "load_manifest", bucket=bucket, manifest_key=manifest_key)
        return state

    def plan_scan_node(state: GraphState) -> GraphState:
        config = state["config"]
        region = state["current_region"]
        manifest: ManifestState = state["current_manifest"]
        report_start: datetime = state["report_start"]
        report_end: datetime = state["report_end"] - timedelta(seconds=1)

        start_dt = report_start

        # With force_reprocess, always scan the full report range
        # Otherwise, optimize scan range using manifest's last_datehour
        if not run_config.force_reprocess and manifest.last_datehour:
            last_dt = _parse_datehour(manifest.last_datehour)
            if last_dt:
                lookback_start = last_dt - timedelta(hours=manifest.lookback_hours)
                start_dt = max(start_dt, lookback_start)

        start_dt = start_dt.replace(minute=0, second=0, microsecond=0)
        end_hour = report_end.replace(minute=0, second=0, microsecond=0)

        prefixes: List[str] = []
        current = start_dt
        while current <= end_hour:
            prefixes.append(_build_log_prefix(config, region, current))
            current += timedelta(hours=1)

        # Cap scan_end_datehour at current time to avoid claiming we've scanned
        # future hours. This ensures subsequent runs correctly compute lookback_start.
        now = run_config.now_fn()
        now_hour = now.replace(minute=0, second=0, microsecond=0)
        effective_end = min(end_hour, now_hour)
        state["scan_prefixes"] = prefixes
        state["scan_end_datehour"] = effective_end.strftime("%Y-%m-%dT%H") if prefixes else None
        log_event(deps.logger, "plan_scan", region=region, prefixes=len(prefixes),
                  force_reprocess=run_config.force_reprocess)
        return state

    def list_objects_node(state: GraphState) -> GraphState:
        bucket = state["current_bucket"]
        prefixes = state.get("scan_prefixes", [])
        objects: List[S3Object] = []
        for prefix in prefixes:
            found = deps.s3.list_objects(bucket, prefix)
            state["stats"]["objects_listed"] += len(found)
            # Filter to only metadata files (skip input/output body files)
            metadata_files = [obj for obj in found if _is_metadata_file(obj.key)]
            state["stats"]["objects_filtered"] += len(found) - len(metadata_files)
            objects.extend(metadata_files)
        state["objects"] = objects
        log_event(deps.logger, "list_objects", bucket=bucket, total=state["stats"]["objects_listed"], metadata=len(objects))
        return state

    def filter_new_objects_node(state: GraphState) -> GraphState:
        manifest: ManifestState = state["current_manifest"]
        processed = manifest.processed
        new_objects: List[S3Object] = []
        for obj in state.get("objects", []):
            # Force reprocess: treat all objects as new
            if run_config.force_reprocess:
                new_objects.append(obj)
                continue
            meta = processed.get(obj.key)
            if not meta or meta.get("etag") != obj.etag:
                new_objects.append(obj)
        state["new_objects"] = new_objects
        log_event(deps.logger, "filter_new_objects", new=len(new_objects), force=run_config.force_reprocess)
        return state

    def ingest_objects_node(state: GraphState) -> GraphState:
        bucket = state["current_bucket"]
        region = state["current_region"]
        report_start: datetime = state["report_start"]
        report_end: datetime = state["report_end"]
        metrics: Metrics = state["metrics"]
        warnings: Warnings = state["warnings"]
        manifest: ManifestState = state["current_manifest"]
        now = run_config.now_fn()

        for obj in state.get("new_objects", []):
            raw = deps.s3.get_object_bytes(bucket, obj.key)

            # Debug mode: dump raw logs (decompressed) mirroring S3 structure
            if run_config.debug:
                debug_path = Path("debug") / bucket / obj.key
                # Remove .gz extension if present, always write as .json
                if debug_path.suffix == ".gz":
                    debug_path = debug_path.with_suffix("")
                if not debug_path.suffix:
                    debug_path = debug_path.with_suffix(".json")
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                decompressed = _maybe_decompress(raw, obj.key)
                debug_path.write_bytes(decompressed)

            records = parse_bedrock_records(raw, obj.key)
            state["stats"]["objects_processed"] += 1
            for record in records:
                state["stats"]["records_parsed"] += 1
                timestamp = parse_timestamp(record)
                if timestamp is None:
                    warnings.records_skipped += 1
                    # Debug mode: log skipped records with full content
                    if run_config.debug:
                        skipped_path = Path("debug/skipped_records.jsonl")
                        skipped_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(skipped_path, "a") as f:
                            f.write(json.dumps({
                                "reason": "no_timestamp",
                                "bucket": bucket,
                                "key": obj.key,
                                "record": record,
                            }) + "\n")
                    continue
                if not (report_start <= timestamp < report_end):
                    continue
                input_tokens, output_tokens, used_fallback = extract_token_counts(record)
                if used_fallback or (input_tokens == 0 and output_tokens == 0):
                    warnings.missing_token_counts += 1
                original_model_id = record.get("modelId") or "unknown"
                model_id = normalize_model_id(original_model_id)
                identity = record.get("identity", {}).get("arn") or "unknown"
                record_region = record.get("region") or region
                metrics.add_usage(
                    region=record_region,
                    identity=identity,
                    model_id=model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=0.0,
                    original_model_id=original_model_id,
                )
                state["stats"]["records_used"] += 1
            record_processed(manifest, obj.key, obj.etag, now)

        log_event(deps.logger, "ingest_objects", processed=len(state.get("new_objects", [])))
        return state

    def update_manifest_node(state: GraphState) -> GraphState:
        bucket = state["current_bucket"]
        manifest: ManifestState = state["current_manifest"]
        update_last_datehour(manifest, state.get("scan_end_datehour"))
        prune_manifest(manifest, run_config.now_fn())
        manifest_key = _manifest_key(run_config.manifest_prefix)
        save_manifest(deps.s3, bucket, manifest_key, manifest)
        log_event(deps.logger, "update_manifest", bucket=bucket, manifest_key=manifest_key)
        return state

    def advance_region_node(state: GraphState) -> GraphState:
        state["region_index"] += 1
        return state

    def verify_results_node(state: GraphState) -> GraphState:
        metrics: Metrics = state["metrics"]
        warnings: Warnings = state["warnings"]
        by_region = _sum_stats(metrics.by_region)
        by_identity = _sum_stats(metrics.by_identity)
        if not _stats_equal(metrics.totals, by_region):
            warnings.verification_errors.add("by_region_mismatch")
        if not _stats_equal(metrics.totals, by_identity):
            warnings.verification_errors.add("by_identity_mismatch")
        log_event(deps.logger, "verify_results", errors=len(warnings.verification_errors))
        return state

    def post_report_node(state: GraphState) -> GraphState:
        message = state["report_message"]
        if deps.slack is None:
            log_event(deps.logger, "post_report", posted=False)
            return state

        try:
            deps.slack.post_message(message)
            state["slack_message"] = message
            log_event(deps.logger, "post_report", posted=True)
        except Exception as e:
            # Log the error with masked webhook URL for debugging
            webhook_hint = "..."
            if isinstance(deps.slack, SlackWebhookAdapter):
                webhook_hint = deps.slack.webhook_url[-8:]
            log_event(
                deps.logger,
                "post_report",
                posted=False,
                error=str(e),
                webhook_suffix=webhook_hint,
            )
            raise  # Re-raise to fail the workflow

        return state

    def render_report_node(state: GraphState) -> GraphState:
        report_date = state["report_date"]
        report_start = state["report_start"]
        report_end = state["report_end"]
        metrics = state["metrics"]
        warnings = state["warnings"]
        generated_at = run_config.now_fn()
        message = format_report(report_date, metrics, warnings)
        snapshot = build_report_snapshot(
            report_date=report_date,
            report_start=report_start,
            report_end=report_end,
            generated_at=generated_at,
            metrics=metrics,
            warnings=warnings,
            stats=state["stats"],
            report_text=message,
        )
        state["report_message"] = message
        state["report_snapshot"] = snapshot
        state["report_generated_at"] = generated_at
        log_event(deps.logger, "render_report", report_date=report_date)
        return state

    def load_snapshot_node(state: GraphState) -> GraphState:
        """Load existing snapshot and merge metrics unless force_reprocess."""
        from ..adapters.report_store import load_metrics_from_snapshot

        if run_config.force_reprocess:
            log_event(deps.logger, "load_snapshot", skipped=True, reason="force_reprocess")
            return state

        report_date = state["report_date"]
        snapshot = deps.report_store.read_snapshot(report_date)

        if snapshot is None:
            log_event(deps.logger, "load_snapshot", found=False)
            return state

        # Check schema version
        schema_version = snapshot.get("schema_version", 0)
        if schema_version != 1:
            log_event(deps.logger, "load_snapshot", skipped=True, reason="schema_mismatch", version=schema_version)
            return state

        # Load and merge metrics
        existing_metrics = load_metrics_from_snapshot(snapshot)

        if existing_metrics is None:
            log_event(deps.logger, "load_snapshot", skipped=True, reason="corrupted")
            return state

        # Merge existing metrics into current metrics
        state["metrics"].merge(existing_metrics)
        log_event(deps.logger, "load_snapshot", found=True, merged=True)
        return state

    def write_snapshot_node(state: GraphState) -> GraphState:
        report_date = state["report_date"]
        snapshot = state["report_snapshot"]
        path = deps.report_store.write_snapshot(report_date, snapshot)
        state["report_snapshot_path"] = str(path)
        log_event(deps.logger, "write_snapshot", path=str(path))
        return state

    def append_csv_node(state: GraphState) -> GraphState:
        generated_at = state["report_generated_at"]
        row = build_csv_row(
            report_date=state["report_date"],
            report_start=state["report_start"],
            report_end=state["report_end"],
            generated_at=generated_at,
            metrics=state["metrics"],
            warnings=state["warnings"],
            stats=state["stats"],
        )
        path = deps.report_store.append_csv_row(row, CSV_FIELDS)
        if path is not None:
            state["csv_report_path"] = str(path)
        log_event(deps.logger, "append_csv", enabled=path is not None, path=str(path) if path else None)
        return state

    def has_new_objects(state: GraphState) -> str:
        if state.get("new_objects"):
            return "ingest_objects"
        return "update_manifest"

    graph = StateGraph(GraphState)
    graph.add_node("load_config", load_config_node)
    graph.add_node("refresh_pricing", refresh_pricing_node)
    graph.add_node("apply_pricing", apply_pricing_node)
    graph.add_node("load_manifest", load_manifest_node)
    graph.add_node("plan_scan", plan_scan_node)
    graph.add_node("list_objects", list_objects_node)
    graph.add_node("filter_new_objects", filter_new_objects_node)
    graph.add_node("ingest_objects", ingest_objects_node)
    graph.add_node("update_manifest", update_manifest_node)
    graph.add_node("advance_region", advance_region_node)
    graph.add_node("verify_results", verify_results_node)
    graph.add_node("render_report", render_report_node)
    graph.add_node("load_snapshot", load_snapshot_node)
    graph.add_node("write_snapshot", write_snapshot_node)
    graph.add_node("append_csv", append_csv_node)
    graph.add_node("post_report", post_report_node)

    graph.add_node("region_router", region_router)
    graph.set_entry_point("load_config")
    graph.add_edge("load_config", "region_router")

    graph.add_edge("load_manifest", "plan_scan")
    graph.add_edge("plan_scan", "list_objects")
    graph.add_edge("list_objects", "filter_new_objects")
    graph.add_conditional_edges("filter_new_objects", has_new_objects)
    graph.add_edge("ingest_objects", "update_manifest")
    graph.add_edge("update_manifest", "advance_region")
    graph.add_edge("advance_region", "region_router")

    graph.add_conditional_edges(
        "region_router",
        lambda state: "load_manifest" if state["region_index"] < len(state["regions"]) else "load_snapshot",
    )
    graph.add_edge("load_snapshot", "refresh_pricing")
    graph.add_edge("refresh_pricing", "apply_pricing")
    graph.add_edge("apply_pricing", "verify_results")
    graph.add_edge("verify_results", "render_report")
    graph.add_edge("render_report", "write_snapshot")
    graph.add_edge("write_snapshot", "append_csv")
    graph.add_edge("append_csv", "post_report")
    graph.add_edge("post_report", END)

    return graph.compile()


def _manifest_key(prefix: str) -> str:
    clean = prefix.strip("/")
    return f"{clean}/bedrock-usage/manifest.json" if clean else "bedrock-usage/manifest.json"


def _build_log_prefix(config: AppConfig, region: str, datehour: datetime) -> str:
    parts: List[str] = []
    if config.log_prefix:
        parts.append(config.log_prefix)
    parts.append("AWSLogs")
    if config.account_id:
        parts.append(config.account_id)
    parts.append("BedrockModelInvocationLogs")
    parts.append(region)
    parts.append(datehour.strftime("%Y/%m/%d/%H"))
    return "/".join(parts) + "/"


def _parse_datehour(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _sum_stats(stats_map) -> TokenStats:
    totals = TokenStats()
    for stats in stats_map.values():
        totals.add(stats.input_tokens, stats.output_tokens, stats.cost_usd)
    return totals


def _stats_equal(left: TokenStats, right: TokenStats) -> bool:
    if left.input_tokens != right.input_tokens:
        return False
    if left.output_tokens != right.output_tokens:
        return False
    if left.total_tokens != right.total_tokens:
        return False
    return abs(left.cost_usd - right.cost_usd) < 0.0001


def _is_metadata_file(key: str) -> bool:
    """Return True if this is a Bedrock metadata file (not input/output body).

    Bedrock logs include three types of files:
    - Metadata files: {timestamp}_{hash}.json(.gz) - contain modelId, tokens, identity
    - Input body files: {uuid}_input.json.gz - raw request payload only
    - Output body files: {uuid}_output.json.gz - raw response payload only
    - Permission check files: amazon-bedrock-logs-permission-check.json

    Only metadata files contain the fields needed for usage tracking.
    """
    basename = key.rsplit("/", 1)[-1]
    # Skip input/output body files
    if "_input.json" in basename or "_output.json" in basename:
        return False
    # Skip permission check files
    if basename.startswith("amazon-bedrock-logs-permission-check"):
        return False
    # Match timestamp-prefixed metadata files: 20260201T204541Z_hash.json(.gz)
    return bool(re.match(r"^\d{8}T\d{6,9}Z_[a-f0-9]+\.json(\.gz)?$", basename))
