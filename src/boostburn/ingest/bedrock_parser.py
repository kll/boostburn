from __future__ import annotations

import gzip
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Pattern to match inference profile ARNs and extract full profile name (including scope prefix)
# Examples:
#   arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0
#   arn:aws:bedrock:us-east-2:123456789012:inference-profile/global.anthropic.claude-3-5-sonnet-20241022-v2:0
_INFERENCE_PROFILE_PATTERN = re.compile(
    r"^arn:aws:bedrock:[^:]+:[^:]+:inference-profile/((us|eu|global|apac)\..+)$"
)


def normalize_model_id(model_id: str) -> str:
    """Normalize model ID to canonical form for aggregation.

    Extracts inference profile names (including scope prefix) from ARNs and
    strips trailing version suffixes (:0, :1, etc.).

    IMPORTANT: Preserves scope prefixes (us., global., eu., apac.) because
    different inference profiles have different pricing in config/pricing.yaml.

    Examples:
        arn:aws:bedrock:us-east-2:123:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0
        -> us.anthropic.claude-opus-4-5-20251101-v1 (prefix preserved!)

        arn:aws:bedrock:us-east-2:123:inference-profile/global.anthropic.claude-opus-4-5-20251101-v1:0
        -> global.anthropic.claude-opus-4-5-20251101-v1 (different from us!)

        anthropic.claude-3-haiku-20240307-v1:0
        -> anthropic.claude-3-haiku-20240307-v1
    """
    match = _INFERENCE_PROFILE_PATTERN.match(model_id)
    if match:
        result = match.group(1)  # Now captures "us.anthropic.model..." with prefix
    else:
        result = model_id

    # Strip trailing :X version suffix
    if ":" in result:
        result = result.rsplit(":", 1)[0]

    return result


def parse_bedrock_records(data: bytes, key: Optional[str] = None) -> List[Dict[str, Any]]:
    payload = _maybe_decompress(data, key)
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    first = text.lstrip()[:1]
    if first == "[":
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    if first == "{":
        try:
            return [json.loads(text)]
        except json.JSONDecodeError:
            return _parse_json_lines(text)
    return _parse_json_lines(text)


def extract_token_counts(record: Dict[str, Any]) -> Tuple[int, int, bool]:
    input_tokens = _safe_int(record.get("input", {}).get("inputTokenCount"))
    output_tokens = _safe_int(record.get("output", {}).get("outputTokenCount"))
    used_fallback = False
    if input_tokens is None or output_tokens is None:
        usage = _extract_usage(record.get("output", {}).get("outputBodyJson"))
        if usage:
            if input_tokens is None:
                input_tokens = _safe_int(usage.get("input_tokens") or usage.get("inputTokens") or usage.get("input_token_count"))
            if output_tokens is None:
                output_tokens = _safe_int(usage.get("output_tokens") or usage.get("outputTokens") or usage.get("output_token_count"))
            used_fallback = True
    return int(input_tokens or 0), int(output_tokens or 0), used_fallback


def parse_timestamp(record: Dict[str, Any]) -> Optional[datetime]:
    value = record.get("timestamp")
    if not value:
        return None
    if isinstance(value, str):
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(value).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_json_lines(text: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def _maybe_decompress(data: bytes, key: Optional[str]) -> bytes:
    if _is_gzip(data, key):
        return gzip.decompress(data)
    return data


def _is_gzip(data: bytes, key: Optional[str]) -> bool:
    if key and key.endswith(".gz"):
        return True
    return len(data) >= 2 and data[:2] == b"\x1f\x8b"


def _extract_usage(output_body: Any) -> Optional[Dict[str, Any]]:
    if output_body is None:
        return None
    if isinstance(output_body, dict):
        return output_body.get("usage")
    if isinstance(output_body, list):
        for item in output_body:
            if isinstance(item, dict):
                message = item.get("message")
                if isinstance(message, dict) and "usage" in message:
                    return message.get("usage")
                if "usage" in item:
                    return item.get("usage")
    return None
