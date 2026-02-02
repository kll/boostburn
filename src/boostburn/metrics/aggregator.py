from __future__ import annotations

from typing import Optional

from ..adapters.pricing import PriceRate


def compute_cost(rate: Optional[PriceRate], input_tokens: int, output_tokens: int) -> float:
    if rate is None:
        return 0.0
    return (input_tokens / 1000.0) * rate.input_per_1k + (output_tokens / 1000.0) * rate.output_per_1k
