from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from .models import Metrics, TokenStats, Warnings

CSV_FIELDS = [
    "report_date",
    "report_start",
    "report_end",
    "generated_at",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "total_cost_usd",
    "regions",
    "models",
    "identities",
    "objects_listed",
    "objects_processed",
    "records_parsed",
    "records_used",
    "missing_token_counts",
    "records_skipped",
    "unpriced_models",
    "verification_errors",
]


def format_report(report_date: str, metrics: Metrics, warnings: Warnings) -> str:
    totals = metrics.totals
    lines: List[str] = [f"Bedrock usage report for {report_date} (UTC)"]
    if totals.total_tokens == 0:
        lines.append("No Bedrock usage recorded for this date.")
        return "\n".join(lines)

    lines.append(
        f"Total tokens: {totals.total_tokens:,} (input {totals.input_tokens:,} / output {totals.output_tokens:,})"
    )
    lines.append(f"Total cost: ${totals.cost_usd:,.4f}")

    if metrics.by_region:
        lines.append("By region:")
        for region, stats in sorted(metrics.by_region.items()):
            lines.append(
                f"- {region}: {stats.total_tokens:,} tokens (${stats.cost_usd:,.4f})"
            )

    if metrics.by_model:
        lines.append("By model:")
        for model_id, stats in _by_model(metrics):
            lines.append(
                f"- {model_id}: {stats.total_tokens:,} tokens (${stats.cost_usd:,.4f})"
            )

    if metrics.by_identity:
        lines.append("Top identities:")
        for identity, stats in _top_identities(metrics):
            lines.append(
                f"- {identity}: {stats.total_tokens:,} tokens (${stats.cost_usd:,.4f})"
            )

    warning_lines = _format_warnings(warnings)
    if warning_lines:
        lines.append("Warnings:")
        lines.extend(warning_lines)

    return "\n".join(lines)


def build_report_snapshot(
    *,
    report_date: str,
    report_start: datetime,
    report_end: datetime,
    generated_at: datetime,
    metrics: Metrics,
    warnings: Warnings,
    stats: Dict[str, object],
    report_text: str,
) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "report_date": report_date,
        "report_start": report_start.astimezone(timezone.utc).isoformat(),
        "report_end": report_end.astimezone(timezone.utc).isoformat(),
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "report": {"text": report_text},
        "metrics": _metrics_to_dict(metrics),
        "warnings": warnings.to_dict(),
        "stats": stats,
    }


def build_csv_row(
    *,
    report_date: str,
    report_start: datetime,
    report_end: datetime,
    generated_at: datetime,
    metrics: Metrics,
    warnings: Warnings,
    stats: Dict[str, object],
) -> Dict[str, object]:
    totals = metrics.totals
    return {
        "report_date": report_date,
        "report_start": report_start.astimezone(timezone.utc).isoformat(),
        "report_end": report_end.astimezone(timezone.utc).isoformat(),
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "total_tokens": totals.total_tokens,
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "total_cost_usd": totals.cost_usd,
        "regions": len(metrics.by_region),
        "models": len(metrics.by_model),
        "identities": len(metrics.by_identity),
        "objects_listed": stats.get("objects_listed", 0),
        "objects_processed": stats.get("objects_processed", 0),
        "records_parsed": stats.get("records_parsed", 0),
        "records_used": stats.get("records_used", 0),
        "missing_token_counts": warnings.missing_token_counts,
        "records_skipped": warnings.records_skipped,
        "unpriced_models": "|".join(sorted(warnings.unpriced_models)),
        "verification_errors": "|".join(sorted(warnings.verification_errors)),
    }


def _top_identities(metrics: Metrics) -> List[tuple[str, object]]:
    ranked = sorted(metrics.by_identity.items(), key=lambda item: item[1].total_tokens, reverse=True)
    return ranked[:5]


def _by_model(metrics: Metrics) -> List[tuple[str, object]]:
    ranked = sorted(metrics.by_model.items(), key=lambda item: item[1].total_tokens, reverse=True)
    return ranked


def _format_warnings(warnings: Warnings) -> List[str]:
    lines: List[str] = []
    if warnings.unpriced_models:
        lines.append("")
        lines.append("UNPRICED MODELS DETECTED")
        lines.append("The following models had $0.00 cost due to missing pricing:")
        for model_id in sorted(warnings.unpriced_models):
            display_id = model_id.split("/")[-1] if "/" in model_id else model_id
            lines.append(f"  - {display_id}")
        lines.append("")
        lines.append("Action required: Update config/pricing.yaml with these model versions")
    if warnings.partial_pricing_models:
        models = ", ".join(sorted(warnings.partial_pricing_models))
        lines.append(f"- Partial pricing (missing input/output rates) for models: {models}")
    if warnings.missing_token_counts:
        lines.append(f"- {warnings.missing_token_counts} records missing token counts")
    if warnings.records_skipped:
        lines.append(f"- {warnings.records_skipped} records skipped due to missing fields")
    if warnings.verification_errors:
        issues = ", ".join(sorted(warnings.verification_errors))
        lines.append(f"- Verification issues: {issues}")
    return lines


def _metrics_to_dict(metrics: Metrics) -> Dict[str, object]:
    return {
        "totals": _token_stats_to_dict(metrics.totals),
        "by_region": _stats_map_to_dict(metrics.by_region),
        "by_model": _stats_map_to_dict(metrics.by_model),
        "by_identity": _stats_map_to_dict(metrics.by_identity),
        "by_usage_key": _usage_key_map_to_list(metrics.by_usage_key),
    }


def _token_stats_to_dict(stats: TokenStats) -> Dict[str, object]:
    return {
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "total_tokens": stats.total_tokens,
        "cost_usd": stats.cost_usd,
    }


def _stats_map_to_dict(stats_map: Dict[str, TokenStats]) -> Dict[str, object]:
    return {key: _token_stats_to_dict(stats_map[key]) for key in sorted(stats_map)}


def _usage_key_map_to_list(stats_map: Dict[tuple[str, str, str], TokenStats]) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for (region, identity, model_id), stats in sorted(stats_map.items()):
        entries.append(
            {
                "region": region,
                "identity": identity,
                "model_id": model_id,
                **_token_stats_to_dict(stats),
            }
        )
    return entries
