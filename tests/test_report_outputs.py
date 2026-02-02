from datetime import datetime, timezone

from boostburn.adapters.report_store import ReportStore
from boostburn.models import Metrics, Warnings
from boostburn.reporting import CSV_FIELDS, build_csv_row, build_report_snapshot


def test_build_report_snapshot_and_csv_row():
    metrics = Metrics()
    metrics.add_usage(
        region="us-east-1",
        identity="arn:example",
        model_id="model",
        input_tokens=5,
        output_tokens=7,
        cost_usd=0.0,
    )
    metrics.totals.cost_usd = 1.23
    metrics.by_region["us-east-1"].cost_usd = 1.23
    metrics.by_model["model"].cost_usd = 1.23
    metrics.by_identity["arn:example"].cost_usd = 1.23

    warnings = Warnings()
    warnings.unpriced_models.add("model-x")
    warnings.missing_token_counts = 2
    warnings.records_skipped = 1
    warnings.verification_errors.add("by_region_mismatch")

    stats = {"objects_listed": 3, "objects_processed": 2, "records_parsed": 4, "records_used": 3}

    report_start = datetime(2026, 1, 31, tzinfo=timezone.utc)
    report_end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    generated_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

    snapshot = build_report_snapshot(
        report_date="2026-01-31",
        report_start=report_start,
        report_end=report_end,
        generated_at=generated_at,
        metrics=metrics,
        warnings=warnings,
        stats=stats,
        report_text="Daily summary",
    )

    assert snapshot["report_date"] == "2026-01-31"
    assert snapshot["metrics"]["totals"]["total_tokens"] == 12
    assert snapshot["warnings"]["unpriced_models"] == ["model-x"]
    assert snapshot["stats"]["objects_listed"] == 3

    row = build_csv_row(
        report_date="2026-01-31",
        report_start=report_start,
        report_end=report_end,
        generated_at=generated_at,
        metrics=metrics,
        warnings=warnings,
        stats=stats,
    )

    assert list(row.keys()) == CSV_FIELDS
    assert row["total_tokens"] == 12
    assert row["unpriced_models"] == "model-x"


def test_report_store_writes_snapshot_and_csv(tmp_path):
    store = ReportStore(
        state_dir=tmp_path / "state",
        csv_path=tmp_path / "reports" / "bedrock-usage.csv",
    )

    snapshot = {"report_date": "2026-01-31", "metrics": {"totals": {"total_tokens": 12}}}
    snapshot_path = store.write_snapshot("2026-01-31", snapshot)
    assert snapshot_path.exists()
    assert "report_date:" in snapshot_path.read_text(encoding="utf-8")

    row = {field: "x" for field in CSV_FIELDS}
    csv_path = store.append_csv_row(row, CSV_FIELDS)
    assert csv_path is not None
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == CSV_FIELDS
    assert len(lines) == 2

    store.append_csv_row(row, CSV_FIELDS)
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_read_snapshot_missing(tmp_path):
    """Reading a non-existent snapshot should return None."""
    from boostburn.adapters.report_store import ReportStore

    store = ReportStore(state_dir=tmp_path)
    snapshot = store.read_snapshot("2099-12-31")
    assert snapshot is None


def test_read_snapshot_corrupted(tmp_path):
    """Reading a corrupted snapshot should return None gracefully."""
    from boostburn.adapters.report_store import ReportStore

    store = ReportStore(state_dir=tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Write invalid YAML
    path = tmp_path / "bedrock-usage-2026-02-01.yaml"
    path.write_text("{ invalid yaml [", encoding="utf-8")

    snapshot = store.read_snapshot("2026-02-01")
    assert snapshot is None


def test_load_metrics_from_snapshot():
    """Loading metrics from snapshot dict should reconstruct Metrics object."""
    from boostburn.adapters.report_store import load_metrics_from_snapshot

    snapshot = {
        "schema_version": 1,
        "metrics": {
            "totals": {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "cost_usd": 0.5
            },
            "by_region": {
                "us-east-1": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "cost_usd": 0.5
                }
            },
            "by_identity": {},
            "by_model": {}
        }
    }

    metrics = load_metrics_from_snapshot(snapshot)
    assert metrics is not None
    assert metrics.totals.total_tokens == 150
    assert metrics.totals.cost_usd == 0.5
    assert metrics.by_region["us-east-1"].total_tokens == 150


def test_load_metrics_from_empty_snapshot():
    """Loading from empty snapshot should return empty Metrics."""
    from boostburn.adapters.report_store import load_metrics_from_snapshot

    snapshot = {"schema_version": 1, "metrics": {}}
    metrics = load_metrics_from_snapshot(snapshot)
    assert metrics is not None
    assert metrics.totals.total_tokens == 0
