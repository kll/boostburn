from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
from typing import Mapping, Optional, Sequence

import yaml


@dataclass(frozen=True)
class ReportStore:
    state_dir: Path
    csv_path: Optional[Path] = None

    def write_snapshot(self, report_date: str, snapshot: Mapping[str, object]) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / f"bedrock-usage-{report_date}.yaml"
        payload = yaml.safe_dump(snapshot, sort_keys=False)
        path.write_text(payload, encoding="utf-8")
        return path

    def read_snapshot(self, report_date: str) -> Optional[dict]:
        """Read existing snapshot for a report date, returns None if not found."""
        path = self.state_dir / f"bedrock-usage-{report_date}.yaml"
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            return yaml.safe_load(content)
        except Exception:
            return None  # Corrupted file, treat as missing

    def append_csv_row(self, row: Mapping[str, object], fieldnames: Sequence[str]) -> Optional[Path]:
        if self.csv_path is None:
            return None
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        with self.csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
        return self.csv_path


def load_metrics_from_snapshot(snapshot: dict) -> Optional[Metrics]:
    """Extract and deserialize Metrics from a snapshot dict."""
    from ..models import Metrics, TokenStats

    try:
        metrics_dict = snapshot.get("metrics", {})
        metrics = Metrics()

        # Load totals
        if "totals" in metrics_dict:
            t = metrics_dict["totals"]
            metrics.totals = TokenStats(
                input_tokens=t.get("input_tokens", 0),
                output_tokens=t.get("output_tokens", 0),
                total_tokens=t.get("total_tokens", 0),
                cost_usd=t.get("cost_usd", 0.0),
            )

        # Load by_region
        for region, stats_dict in metrics_dict.get("by_region", {}).items():
            metrics.by_region[region] = TokenStats(
                input_tokens=stats_dict.get("input_tokens", 0),
                output_tokens=stats_dict.get("output_tokens", 0),
                total_tokens=stats_dict.get("total_tokens", 0),
                cost_usd=stats_dict.get("cost_usd", 0.0),
            )

        # Load by_identity
        for identity, stats_dict in metrics_dict.get("by_identity", {}).items():
            metrics.by_identity[identity] = TokenStats(
                input_tokens=stats_dict.get("input_tokens", 0),
                output_tokens=stats_dict.get("output_tokens", 0),
                total_tokens=stats_dict.get("total_tokens", 0),
                cost_usd=stats_dict.get("cost_usd", 0.0),
            )

        # Load by_model
        for model, stats_dict in metrics_dict.get("by_model", {}).items():
            metrics.by_model[model] = TokenStats(
                input_tokens=stats_dict.get("input_tokens", 0),
                output_tokens=stats_dict.get("output_tokens", 0),
                total_tokens=stats_dict.get("total_tokens", 0),
                cost_usd=stats_dict.get("cost_usd", 0.0),
            )

        # Load by_usage_key for pricing recalculation
        usage_entries = metrics_dict.get("by_usage_key", [])
        if isinstance(usage_entries, list):
            for entry in usage_entries:
                if not isinstance(entry, dict):
                    continue
                region = entry.get("region")
                identity = entry.get("identity")
                model_id = entry.get("model_id")
                if not region or not identity or not model_id:
                    continue
                metrics.by_usage_key[(region, identity, model_id)] = TokenStats(
                    input_tokens=entry.get("input_tokens", 0),
                    output_tokens=entry.get("output_tokens", 0),
                    total_tokens=entry.get("total_tokens", 0),
                    cost_usd=entry.get("cost_usd", 0.0),
                )
        elif isinstance(usage_entries, dict):
            for key, stats_dict in usage_entries.items():
                if not isinstance(stats_dict, dict):
                    continue
                if not isinstance(key, str):
                    continue
                parts = key.split("|")
                if len(parts) != 3:
                    continue
                region, identity, model_id = parts
                metrics.by_usage_key[(region, identity, model_id)] = TokenStats(
                    input_tokens=stats_dict.get("input_tokens", 0),
                    output_tokens=stats_dict.get("output_tokens", 0),
                    total_tokens=stats_dict.get("total_tokens", 0),
                    cost_usd=stats_dict.get("cost_usd", 0.0),
                )

        return metrics
    except Exception:
        return None  # Corrupted data, skip merge
