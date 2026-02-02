import yaml

from boostburn.adapters.pricing import StaticPricingProvider, get_pricing_model_key


def test_static_pricing_provider_reads_yaml(tmp_path):
    """Test that provider reads inference profile pricing correctly."""
    payload = {
        "schema_version": 1,
        "rates": {
            # Use the full inference profile key format
            "us.anthropic.claude-opus-4-5-20251101-v1": {
                "us-east-2": {
                    "input_per_1k": 0.01,
                    "output_per_1k": 0.02,
                    "currency": "USD",
                }
            }
        },
    }
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(payload))

    provider = StaticPricingProvider(pricing_path=path)

    rate = provider.get_rate(
        "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0",
        "us-east-2",
    )

    assert rate is not None
    assert rate.input_per_1k == 0.01
    assert rate.output_per_1k == 0.02


def test_static_pricing_provider_default_fallback(tmp_path):
    """Default pricing applies when no region-specific rate exists."""
    payload = {
        "schema_version": 1,
        "rates": {
            "anthropic.claude-3-5-sonnet-20241022-v2": {
                "default": {
                    "input_per_1k": 0.003,
                    "output_per_1k": 0.015,
                    "currency": "USD",
                }
            }
        },
    }
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(payload))

    provider = StaticPricingProvider(pricing_path=path)

    # Should use default rate for any region
    rate = provider.get_rate("anthropic.claude-3-5-sonnet-20241022-v2:0", "us-west-2")

    assert rate is not None
    assert rate.input_per_1k == 0.003
    assert rate.output_per_1k == 0.015


def test_static_pricing_provider_region_override(tmp_path):
    """Region-specific rate takes precedence over default."""
    payload = {
        "schema_version": 1,
        "rates": {
            "anthropic.claude-opus-4-5-20251101-v1": {
                "default": {
                    "input_per_1k": 0.005,
                    "output_per_1k": 0.015,
                    "currency": "USD",
                },
                "us-west-2": {
                    "input_per_1k": 0.006,
                    "output_per_1k": 0.018,
                    "currency": "USD",
                },
            }
        },
    }
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(payload))

    provider = StaticPricingProvider(pricing_path=path)

    # Region with override should use region-specific rate
    rate_west = provider.get_rate("anthropic.claude-opus-4-5-20251101-v1:0", "us-west-2")
    assert rate_west is not None
    assert rate_west.input_per_1k == 0.006
    assert rate_west.output_per_1k == 0.018

    # Region without override should use default
    rate_east = provider.get_rate("anthropic.claude-opus-4-5-20251101-v1:0", "us-east-2")
    assert rate_east is not None
    assert rate_east.input_per_1k == 0.005
    assert rate_east.output_per_1k == 0.015


def test_get_pricing_model_key_inference_profile():
    """Test that get_pricing_model_key preserves inference profile prefix."""
    # US inference profile ARN
    us_arn = "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0"
    assert get_pricing_model_key(us_arn) == "us.anthropic.claude-opus-4-5-20251101-v1"

    # Global inference profile ARN
    global_arn = "arn:aws:bedrock:us-east-2:123456789012:inference-profile/global.anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert get_pricing_model_key(global_arn) == "global.anthropic.claude-3-5-sonnet-20241022-v2"

    # EU inference profile ARN
    eu_arn = "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-opus-4-5-20251101-v1:0"
    assert get_pricing_model_key(eu_arn) == "eu.anthropic.claude-opus-4-5-20251101-v1"


def test_get_pricing_model_key_non_inference_profile():
    """Test that get_pricing_model_key handles non-inference-profile models."""
    # Plain model ID
    plain_id = "anthropic.claude-opus-4-5-20251101-v1:0"
    assert get_pricing_model_key(plain_id) == "anthropic.claude-opus-4-5-20251101-v1"

    # Model ID without version suffix
    no_version = "anthropic.claude-3-5-sonnet-20241022-v2"
    assert get_pricing_model_key(no_version) == "anthropic.claude-3-5-sonnet-20241022-v2"


def test_inference_profile_pricing_differentiation(tmp_path):
    """Test that different inference profiles get different pricing."""
    payload = {
        "rates": {
            "global.anthropic.claude-opus-4-5-20251101-v1": {
                "default": {
                    "input_per_1k": 0.006,
                    "output_per_1k": 0.018,
                    "currency": "USD",
                }
            },
            "us.anthropic.claude-opus-4-5-20251101-v1": {
                "default": {
                    "input_per_1k": 0.005,
                    "output_per_1k": 0.015,
                    "currency": "USD",
                }
            },
        }
    }
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(payload))

    provider = StaticPricingProvider(pricing_path=path)

    # Global inference profile should use global rate
    global_arn = "arn:aws:bedrock:us-east-2:123456789012:inference-profile/global.anthropic.claude-opus-4-5-20251101-v1:0"
    global_rate = provider.get_rate(global_arn, "us-east-2")
    assert global_rate is not None
    assert global_rate.input_per_1k == 0.006
    assert global_rate.output_per_1k == 0.018

    # US inference profile should use US rate
    us_arn = "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0"
    us_rate = provider.get_rate(us_arn, "us-east-2")
    assert us_rate is not None
    assert us_rate.input_per_1k == 0.005
    assert us_rate.output_per_1k == 0.015


def test_inference_profile_not_in_pricing_yaml(tmp_path):
    """Test that missing inference profile returns None."""
    payload = {
        "rates": {
            "us.anthropic.claude-opus-4-5-20251101-v1": {
                "default": {
                    "input_per_1k": 0.005,
                    "output_per_1k": 0.015,
                    "currency": "USD",
                }
            },
        }
    }
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(payload))

    provider = StaticPricingProvider(pricing_path=path)

    # Global profile not in pricing.yaml should return None
    global_arn = "arn:aws:bedrock:us-east-2:123456789012:inference-profile/global.anthropic.claude-opus-4-5-20251101-v1:0"
    rate = provider.get_rate(global_arn, "us-east-2")
    assert rate is None


def test_inference_profile_with_region_override(tmp_path):
    """Test that region-specific override works with inference profiles."""
    payload = {
        "rates": {
            "us.anthropic.claude-opus-4-5-20251101-v1": {
                "default": {
                    "input_per_1k": 0.005,
                    "output_per_1k": 0.015,
                    "currency": "USD",
                },
                "us-west-2": {
                    "input_per_1k": 0.0055,
                    "output_per_1k": 0.016,
                    "currency": "USD",
                },
            },
        }
    }
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(payload))

    provider = StaticPricingProvider(pricing_path=path)

    us_arn = "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0"

    # Region with override
    rate_west = provider.get_rate(us_arn, "us-west-2")
    assert rate_west is not None
    assert rate_west.input_per_1k == 0.0055
    assert rate_west.output_per_1k == 0.016

    # Region without override should use default
    rate_east = provider.get_rate(us_arn, "us-east-2")
    assert rate_east is not None
    assert rate_east.input_per_1k == 0.005
    assert rate_east.output_per_1k == 0.015


def test_missing_model_version_returns_none(tmp_path):
    """Verify that missing model version returns None (no fallback)."""
    payload = {
        "rates": {
            "global.anthropic.claude-haiku-4-5-20241022-v1": {
                "default": {
                    "input_per_1k": 0.001,
                    "output_per_1k": 0.005,
                    "currency": "USD",
                }
            }
        }
    }
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(payload))

    provider = StaticPricingProvider(pricing_path=path)

    # Request newer version that doesn't exist in pricing
    newer_arn = "arn:aws:bedrock:us-east-2:123456789012:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0"
    rate = provider.get_rate(newer_arn, "us-east-2")

    # Should return None, not fall back to similar model
    assert rate is None


def test_unpriced_model_warnings():
    """Verify that missing pricing adds to warnings.unpriced_models."""
    from boostburn.models import Metrics, Warnings

    # Create metrics with usage for an unknown model
    metrics = Metrics()
    model_id = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    metrics.add_usage(
        region="us-east-2",
        identity="arn:test",
        model_id=model_id,
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.0,
    )

    # Mock pricing provider that returns None
    class IncompletePricingProvider:
        def get_rate(self, model_id, region):
            return None

    provider = IncompletePricingProvider()
    warnings = Warnings()

    # Apply pricing (should add to warnings)
    metrics.apply_pricing(provider, warnings)

    # Verify model appears in warnings
    assert model_id in warnings.unpriced_models
    assert metrics.totals.cost_usd == 0.0
