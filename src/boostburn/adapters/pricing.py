from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Dict, Optional

import yaml


@dataclass(frozen=True)
class PriceRate:
    input_per_1k: float
    output_per_1k: float
    currency: str = "USD"
    effective_date: Optional[str] = None
    missing_input: bool = False
    missing_output: bool = False


class PricingProvider:
    def get_rate(self, model_id: str, region: str) -> Optional[PriceRate]:
        raise NotImplementedError

    def refresh(self, model_ids: Optional[set[str]] = None) -> None:
        return None


class StaticPricingProvider(PricingProvider):
    def __init__(
        self,
        pricing_path: str | Path,
        now_fn: Optional[callable] = None,
    ) -> None:
        self._pricing_path = Path(pricing_path)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._rates: Optional[Dict[str, Dict[str, PriceRate]]] = None

    def refresh(self, model_ids: Optional[set[str]] = None) -> None:
        rates = _load_pricing_yaml(self._pricing_path)
        self._rates = _filter_rates(rates, model_ids)

    def get_rate(self, model_id: str, region: str) -> Optional[PriceRate]:
        """Get pricing rate for a model in a region.

        Uses the model ID (with inference profile prefix if present) to look up pricing.
        Requires exact match in pricing.yaml - no fallback logic.
        """
        if self._rates is None:
            self.refresh()

        # Direct lookup using pricing key (preserves inference profile)
        pricing_key = get_pricing_model_key(model_id)
        model_rates = (self._rates or {}).get(pricing_key)
        if model_rates:
            if region in model_rates:
                return model_rates[region]
            if "default" in model_rates:
                return model_rates["default"]

        return None


_KNOWN_PROVIDERS = {
    "anthropic",
    "amazon",
    "meta",
    "mistral",
    "cohere",
    "ai21",
    "stability",
    "deepseek",
    "qwen",
    "openai",
    "gpt",
}

_KNOWN_SCOPES = {"global", "us", "eu", "ap", "sa", "me", "af", "ca"}


def normalize_model_id(model_id: str) -> str:
    value = model_id
    if value.startswith("arn:"):
        value = value.split(":", 5)[-1]
    if "/" in value:
        value = value.split("/")[-1]
    return value


def get_pricing_model_key(original_model_id: str) -> str:
    """Extract the model key for pricing lookup, preserving inference profile prefix.

    For inference profile ARNs, extracts the profile.provider.model portion.
    For non-inference ARNs, uses existing normalization logic.
    Strips the trailing :0 version suffix to make keys YAML-compliant.

    Examples:
        arn:aws:bedrock:...:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0
        -> us.anthropic.claude-opus-4-5-20251101-v1

        arn:aws:bedrock:...:inference-profile/global.anthropic.claude-3-5-sonnet-20241022-v2:0
        -> global.anthropic.claude-3-5-sonnet-20241022-v2

        anthropic.claude-opus-4-5-20251101-v1:0
        -> anthropic.claude-opus-4-5-20251101-v1

    Returns:
        Model key with inference profile prefix preserved, without trailing :X suffix
    """
    if not isinstance(original_model_id, str):
        return normalize_model_id(original_model_id)

    result = original_model_id

    # Check if this is an inference profile ARN
    if "inference-profile/" in result:
        parts = result.split("inference-profile/", 1)
        if len(parts) == 2:
            # Extract everything after inference-profile/
            result = parts[1]
    else:
        # Fall back to standard normalization for non-inference-profile models
        result = normalize_model_id(result)

    # Strip trailing :0 or :X version suffix (YAML key compatibility)
    if ":" in result:
        result = result.rsplit(":", 1)[0]

    return result


def canonical_model_key(model_id: str) -> str:
    """Canonical model key used by pricing scraper.

    Note: This function is kept for the pricing scraper but is not used
    in the main pricing lookup logic, which uses get_pricing_model_key() instead.
    """
    value = normalize_model_id(model_id)
    if ":" in value:
        value = value.split(":", 1)[0]
    value = value.replace(":", " ")
    parts = value.split(".")
    if len(parts) >= 3 and parts[0].lower() in _KNOWN_SCOPES and parts[1].lower() in _KNOWN_PROVIDERS:
        value = ".".join(parts[1:])
    value = re.sub(r"[\./_]+", " ", value)
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    value = re.sub(r"(\d)([A-Za-z])", r"\1 \2", value)
    value = re.sub(r"([A-Za-z])(\d)", r"\1 \2", value)
    tokens = re.findall(r"[A-Za-z0-9]+", value)
    normalized: list[str] = []
    index = 0
    while index < len(tokens):
        lowered = tokens[index].lower()
        next_token = tokens[index + 1].lower() if index + 1 < len(tokens) else ""
        if lowered == "v" and next_token.isdigit():
            index += 2
            continue
        if re.fullmatch(r"v\d+", lowered):
            index += 1
            continue
        if lowered.isdigit() and len(lowered) >= 6:
            index += 1
            continue
        normalized.append(lowered)
        index += 1
    return "-".join(normalized)


def _filter_rates(
    rates: Dict[str, Dict[str, PriceRate]],
    model_ids: Optional[set[str]],
) -> Dict[str, Dict[str, PriceRate]]:
    if not model_ids:
        return rates
    pricing_keys: set[str] = set()
    for model_id in model_ids:
        # Include only the pricing key (with inference profile prefix)
        pricing_key = get_pricing_model_key(model_id)
        if pricing_key:
            pricing_keys.add(pricing_key)
    return {model_id: region_map for model_id, region_map in rates.items() if model_id in pricing_keys}


def _load_pricing_yaml(path: Path) -> Dict[str, Dict[str, PriceRate]]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text())
    if payload is None:
        return {}
    raw_rates = payload.get("rates") if isinstance(payload, dict) else None
    if raw_rates is None and isinstance(payload, dict):
        raw_rates = payload
    if not isinstance(raw_rates, dict):
        return {}

    rates: Dict[str, Dict[str, PriceRate]] = {}
    for model_id, region_map in raw_rates.items():
        if not isinstance(region_map, dict):
            continue
        # Use get_pricing_model_key to preserve inference profile prefixes
        pricing_key = get_pricing_model_key(str(model_id))
        if not pricing_key:
            continue

        for region, rate in region_map.items():
            if not isinstance(rate, dict):
                continue
            input_rate = rate.get("input_per_1k")
            output_rate = rate.get("output_per_1k")
            if input_rate is None and output_rate is None:
                continue
            missing_input = input_rate is None
            missing_output = output_rate is None
            try:
                input_val = float(input_rate) if input_rate is not None else 0.0
                output_val = float(output_rate) if output_rate is not None else 0.0
            except (TypeError, ValueError):
                continue
            price_rate = PriceRate(
                input_per_1k=input_val,
                output_per_1k=output_val,
                currency=rate.get("currency", "USD"),
                effective_date=rate.get("effective_date"),
                missing_input=missing_input,
                missing_output=missing_output,
            )
            # Store only under pricing key (no aliases)
            rates.setdefault(pricing_key, {})[region] = price_rate
    return rates
