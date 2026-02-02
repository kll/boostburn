from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

import yaml

from boostburn.adapters.local_s3 import LocalS3Adapter

from boostburn.adapters.pricing import StaticPricingProvider
from boostburn.adapters.report_store import ReportStore
from boostburn.adapters.slack import RecordingSlackAdapter
from boostburn.graph.workflow import Dependencies, RunConfig, build_graph


def main() -> int:
    cases = yaml.safe_load(Path("evals/golden_data.yaml").read_text()) or []
    failures: List[str] = []
    for case in cases:
        errors = run_case(case)
        if errors:
            failures.append(case["id"])
            for error in errors:
                print(f"✗ {case['id']}: {error}")
        else:
            print(f"✓ {case['id']}: {case.get('description', '')}")

    print("\nResults:")
    print(f"{len(cases) - len(failures)}/{len(cases)} passed")
    return 1 if failures else 0


def run_case(case: Dict[str, Any]) -> List[str]:
    config_path = Path(case.get("config_path", "evals/fixtures/config.yaml"))
    pricing_cache_path = Path(case.get("pricing_cache_path", "evals/fixtures/pricing_cache_full.json"))
    pricing_path = Path(case.get("pricing_path", "config/pricing.yaml"))
    state_dir = Path(case.get("state_dir", "evals/fixtures/state"))
    report_date = case.get("report_date", "2026-02-01")

    buckets_root = Path(case.get("buckets_root", "evals/fixtures/buckets"))
    bucket_map = {path.name: path for path in buckets_root.iterdir() if path.is_dir()}

    manifest_prefix = f"manifests/{case['id']}"
    _clear_manifest(bucket_map, manifest_prefix)
    _clear_snapshot(state_dir, report_date)

    deps = Dependencies(
        s3=LocalS3Adapter(bucket_map),
        pricing=StaticPricingProvider(pricing_path=_select_pricing_path(pricing_path, pricing_cache_path)),
        report_store=ReportStore(state_dir=state_dir),
        slack=RecordingSlackAdapter(),
        logger=_null_logger(),
    )

    run_config = RunConfig(
        config_path=str(config_path),
        manifest_prefix=manifest_prefix,
        lookback_hours=int(case.get("lookback_hours", 6)),
        report_date=report_date,
    )

    graph = build_graph(deps, run_config)
    result = graph.invoke({})

    return validate_case(case, result, deps)


def _select_pricing_path(default_path: Path, cache_path: Path) -> Path:
    if cache_path.suffix == ".json":
        candidate = cache_path.with_suffix(".yaml")
        if candidate.exists():
            return candidate
    return default_path


def _clear_snapshot(state_dir: Path, report_date: str) -> None:
    path = state_dir / f"bedrock-usage-{report_date}.yaml"
    if path.exists():
        path.unlink()


def validate_case(case: Dict[str, Any], result: Dict[str, Any], deps: Dependencies) -> List[str]:
    errors: List[str] = []
    expect = case.get("expect", {})
    metrics = result["metrics"]
    warnings = result["warnings"]

    if "total_tokens" in expect and metrics.totals.total_tokens != expect["total_tokens"]:
        errors.append(
            f"total_tokens expected {expect['total_tokens']} got {metrics.totals.total_tokens}"
        )

    if "min_cost_usd" in expect and metrics.totals.cost_usd < expect["min_cost_usd"]:
        errors.append(
            f"min_cost_usd expected >= {expect['min_cost_usd']} got {metrics.totals.cost_usd}"
        )

    for region, expected_region in expect.get("by_region", {}).items():
        actual = metrics.by_region.get(region)
        if not actual:
            errors.append(f"missing region stats for {region}")
            continue
        if "total_tokens" in expected_region and actual.total_tokens != expected_region["total_tokens"]:
            errors.append(
                f"region {region} total_tokens expected {expected_region['total_tokens']} got {actual.total_tokens}"
            )

    for needle in expect.get("slack_contains", []):
        if not deps.slack or not deps.slack.messages or needle not in deps.slack.messages[-1]["text"]:
            errors.append(f"slack message missing '{needle}'")

    for needle in expect.get("slack_not_contains", []):
        if deps.slack and deps.slack.messages and needle in deps.slack.messages[-1]["text"]:
            errors.append(f"slack message should not contain '{needle}'")

    # Validate unpriced_models with exact matching
    if "unpriced_models" in expect:
        expected_unpriced = set(expect["unpriced_models"])
        actual_unpriced = set(warnings.unpriced_models or [])
        if expected_unpriced != actual_unpriced:
            errors.append(
                f"unpriced_models mismatch: expected {expected_unpriced}, got {actual_unpriced}"
            )

    if expect.get("no_usage") and metrics.totals.total_tokens != 0:
        errors.append("expected no usage but totals were non-zero")

    if expect.get("usage_present") and metrics.totals.total_tokens == 0:
        errors.append("expected usage but totals were zero")

    return errors


def _null_logger():
    class _Logger:
        def info(self, *_: Any, **__: Any) -> None:
            return None

    return _Logger()


def _clear_manifest(bucket_map, manifest_prefix: str) -> None:
    manifest_key = f"{manifest_prefix.strip('/')}/bedrock-usage/manifest.json"
    for bucket_root in bucket_map.values():
        path = bucket_root / manifest_key
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    sys.exit(main())
