from boostburn.metrics.aggregator import compute_cost
from boostburn.adapters.pricing import PriceRate
from boostburn.models import Metrics


def test_compute_cost():
    rate = PriceRate(input_per_1k=0.01, output_per_1k=0.02)
    cost = compute_cost(rate, input_tokens=1000, output_tokens=500)
    assert abs(cost - 0.02) < 1e-9


def test_metrics_add_usage():
    metrics = Metrics()
    metrics.add_usage(
        region="us-east-2",
        identity="arn:example",
        model_id="model",
        input_tokens=5,
        output_tokens=7,
        cost_usd=0.001,
    )
    assert metrics.totals.total_tokens == 12
    assert metrics.by_region["us-east-2"].total_tokens == 12
    assert metrics.by_identity["arn:example"].total_tokens == 12


def test_metrics_merge_empty():
    """Merging empty metrics should be a no-op."""
    m1 = Metrics()
    m2 = Metrics()
    m1.merge(m2)
    assert m1.totals.total_tokens == 0
    assert m1.totals.cost_usd == 0.0


def test_metrics_merge_additive():
    """Merging should add token counts across all dimensions."""
    m1 = Metrics()
    m1.add_usage(
        region="us-east-1",
        identity="arn:aws:iam::123456789012:role/Role1",
        model_id="anthropic.claude-3-sonnet-20240229-v1",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0,  # No pricing yet
    )

    m2 = Metrics()
    m2.add_usage(
        region="us-east-1",
        identity="arn:aws:iam::123456789012:role/Role2",
        model_id="anthropic.claude-3-sonnet-20240229-v1",
        input_tokens=200,
        output_tokens=100,
        cost_usd=0.0,
    )

    m1.merge(m2)

    # Check totals
    assert m1.totals.input_tokens == 300
    assert m1.totals.output_tokens == 150
    assert m1.totals.total_tokens == 450

    # Check by_region (should be combined)
    assert m1.by_region["us-east-1"].total_tokens == 450

    # Check by_model (should be combined)
    assert m1.by_model["anthropic.claude-3-sonnet-20240229-v1"].total_tokens == 450

    # Check by_identity (should have 2 entries)
    assert len(m1.by_identity) == 2
    assert m1.by_identity["arn:aws:iam::123456789012:role/Role1"].total_tokens == 150
    assert m1.by_identity["arn:aws:iam::123456789012:role/Role2"].total_tokens == 300


def test_metrics_merge_different_regions():
    """Merging metrics from different regions should keep them separate."""
    m1 = Metrics()
    m1.add_usage(
        region="us-east-1",
        identity="arn:aws:iam::123456789012:role/Role1",
        model_id="anthropic.claude-3-sonnet-20240229-v1",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0,
    )

    m2 = Metrics()
    m2.add_usage(
        region="us-west-2",
        identity="arn:aws:iam::123456789012:role/Role1",
        model_id="anthropic.claude-3-sonnet-20240229-v1",
        input_tokens=200,
        output_tokens=100,
        cost_usd=0.0,
    )

    m1.merge(m2)

    # Check we have 2 regions
    assert len(m1.by_region) == 2
    assert m1.by_region["us-east-1"].total_tokens == 150
    assert m1.by_region["us-west-2"].total_tokens == 300

    # Check totals are combined
    assert m1.totals.total_tokens == 450


def test_metrics_merge_by_usage_key():
    """Merging should also merge by_usage_key for pricing calculation."""
    m1 = Metrics()
    m1.add_usage(
        region="us-east-1",
        identity="arn1",
        model_id="model1",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0,
    )

    m2 = Metrics()
    m2.add_usage(
        region="us-east-1",
        identity="arn1",
        model_id="model1",
        input_tokens=200,
        output_tokens=100,
        cost_usd=0.0,
    )

    m1.merge(m2)

    # Check by_usage_key is merged
    key = ("us-east-1", "arn1", "model1")
    assert key in m1.by_usage_key
    assert m1.by_usage_key[key].total_tokens == 450


def test_apply_pricing_with_missing_model():
    """Test that apply_pricing handles missing models correctly."""
    from boostburn.models import Warnings

    # Create metrics with usage for multiple models
    metrics = Metrics()
    metrics.add_usage(
        region="us-east-2",
        identity="arn:test",
        model_id="global.anthropic.claude-haiku-4-5-20241022-v1",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.0,
    )
    metrics.add_usage(
        region="us-east-2",
        identity="arn:test",
        model_id="global.anthropic.claude-haiku-4-5-20251001-v1",
        input_tokens=2000,
        output_tokens=1000,
        cost_usd=0.0,
    )

    # Create pricing provider with only one model
    class PartialPricingProvider:
        def get_rate(self, model_id, region):
            # Only provide pricing for the old version
            if "20241022" in model_id:
                return PriceRate(input_per_1k=0.001, output_per_1k=0.005)
            return None

    provider = PartialPricingProvider()
    warnings = Warnings()

    # Apply pricing
    metrics.apply_pricing(provider, warnings)

    # Priced model should have cost > 0
    assert metrics.by_model["global.anthropic.claude-haiku-4-5-20241022-v1"].cost_usd > 0

    # Unpriced model should have cost = 0
    assert metrics.by_model["global.anthropic.claude-haiku-4-5-20251001-v1"].cost_usd == 0.0

    # Warnings should contain missing model
    assert "global.anthropic.claude-haiku-4-5-20251001-v1" in warnings.unpriced_models


def test_apply_pricing_populates_by_usage_key_costs():
    """Test that apply_pricing stores costs in by_usage_key entries."""
    from boostburn.models import Warnings

    metrics = Metrics()
    metrics.add_usage(
        region="us-east-2",
        identity="arn:test",
        model_id="anthropic.claude-sonnet-4-5-20250929-v1",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.0,
    )

    class SimplePricingProvider:
        def get_rate(self, model_id, region):
            return PriceRate(input_per_1k=0.003, output_per_1k=0.015)

    provider = SimplePricingProvider()
    warnings = Warnings()

    # Apply pricing
    metrics.apply_pricing(provider, warnings)

    # Check that by_usage_key entry has the cost populated
    key = ("us-east-2", "arn:test", "anthropic.claude-sonnet-4-5-20250929-v1")
    expected_cost = (1000 / 1000.0) * 0.003 + (500 / 1000.0) * 0.015  # 0.0105
    assert key in metrics.by_usage_key
    assert abs(metrics.by_usage_key[key].cost_usd - expected_cost) < 1e-9

    # Also verify totals match (sanity check)
    assert abs(metrics.totals.cost_usd - expected_cost) < 1e-9
