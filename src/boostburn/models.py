from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from .metrics.aggregator import compute_cost
from .adapters.pricing import PricingProvider


@dataclass
class TokenStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.cost_usd += cost_usd


@dataclass
class Metrics:
    totals: TokenStats = field(default_factory=TokenStats)
    by_region: Dict[str, TokenStats] = field(default_factory=dict)
    by_identity: Dict[str, TokenStats] = field(default_factory=dict)
    by_model: Dict[str, TokenStats] = field(default_factory=dict)
    by_usage_key: Dict[Tuple[str, str, str], TokenStats] = field(default_factory=dict)
    model_id_map: Dict[str, str] = field(default_factory=dict)  # normalized -> original

    def add_usage(
        self,
        *,
        region: str,
        identity: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        original_model_id: Optional[str] = None,
    ) -> None:
        self.totals.add(input_tokens, output_tokens, cost_usd)
        self.by_region.setdefault(region, TokenStats()).add(input_tokens, output_tokens, cost_usd)
        self.by_identity.setdefault(identity, TokenStats()).add(input_tokens, output_tokens, cost_usd)
        self.by_model.setdefault(model_id, TokenStats()).add(input_tokens, output_tokens, cost_usd)
        key = (region, identity, model_id)
        self.by_usage_key.setdefault(key, TokenStats()).add(input_tokens, output_tokens, 0.0)

        # Track mapping from normalized to original model ID
        if original_model_id and model_id not in self.model_id_map:
            self.model_id_map[model_id] = original_model_id

    def merge(self, other: Metrics) -> Metrics:
        """Merge another Metrics object into this one (additive).

        Used when loading existing snapshots to aggregate multiple runs per day.
        Note: pricing is NOT merged - it will be recalculated by apply_pricing.
        """
        # Merge totals (costs will be recalculated later)
        self.totals.add(
            other.totals.input_tokens,
            other.totals.output_tokens,
            0.0  # Don't merge old costs, will be recalculated
        )

        # Merge by_region
        for region, stats in other.by_region.items():
            if region not in self.by_region:
                self.by_region[region] = TokenStats()
            self.by_region[region].add(stats.input_tokens, stats.output_tokens, 0.0)

        # Merge by_identity
        for identity, stats in other.by_identity.items():
            if identity not in self.by_identity:
                self.by_identity[identity] = TokenStats()
            self.by_identity[identity].add(stats.input_tokens, stats.output_tokens, 0.0)

        # Merge by_model
        for model, stats in other.by_model.items():
            if model not in self.by_model:
                self.by_model[model] = TokenStats()
            self.by_model[model].add(stats.input_tokens, stats.output_tokens, 0.0)

        # Merge by_usage_key (needed for pricing recalculation)
        for key, stats in other.by_usage_key.items():
            if key not in self.by_usage_key:
                self.by_usage_key[key] = TokenStats()
            self.by_usage_key[key].add(stats.input_tokens, stats.output_tokens, 0.0)

        # Merge model_id_map (preserve first occurrence)
        for normalized, original in other.model_id_map.items():
            if normalized not in self.model_id_map:
                self.model_id_map[normalized] = original

        return self

    def apply_pricing(self, pricing: PricingProvider, warnings: "Warnings") -> None:
        """Apply pricing to all usage records using original model IDs for lookup."""
        self.totals.cost_usd = 0.0
        for stats in self.by_region.values():
            stats.cost_usd = 0.0
        for stats in self.by_identity.values():
            stats.cost_usd = 0.0
        for stats in self.by_model.values():
            stats.cost_usd = 0.0

        for (region, identity, model_id), stats in self.by_usage_key.items():
            # Use original model ID (with profile) for pricing lookup
            original_model_id = self.model_id_map.get(model_id, model_id)

            # Get rate using the original model ID (preserves inference profile)
            rate = pricing.get_rate(original_model_id, region)

            if rate is None:
                warnings.unpriced_models.add(model_id)
            else:
                if getattr(rate, "missing_input", False) or getattr(rate, "missing_output", False):
                    warnings.partial_pricing_models.add(model_id)
            cost = compute_cost(rate, stats.input_tokens, stats.output_tokens)
            stats.cost_usd = cost
            self.totals.cost_usd += cost
            self.by_region[region].cost_usd += cost
            self.by_identity[identity].cost_usd += cost
            self.by_model[model_id].cost_usd += cost


@dataclass
class Warnings:
    unpriced_models: Set[str] = field(default_factory=set)
    partial_pricing_models: Set[str] = field(default_factory=set)
    missing_token_counts: int = 0
    records_skipped: int = 0
    verification_errors: Set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "unpriced_models": sorted(self.unpriced_models),
            "partial_pricing_models": sorted(self.partial_pricing_models),
            "missing_token_counts": self.missing_token_counts,
            "records_skipped": self.records_skipped,
            "verification_errors": sorted(self.verification_errors),
        }

    def has_critical_warnings(self) -> bool:
        """Check if any critical warnings exist requiring operator attention."""
        return bool(
            self.unpriced_models
            or self.verification_errors
        )
