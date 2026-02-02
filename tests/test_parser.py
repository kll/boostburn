from pathlib import Path

import pytest

from boostburn.ingest.bedrock_parser import (
    extract_token_counts,
    normalize_model_id,
    parse_bedrock_records,
)


def test_parse_records_counts():
    path = Path(
        "evals/fixtures/buckets/bedrock-logs-123456789012-us-east-2/"
        "AWSLogs/123456789012/BedrockModelInvocationLogs/us-east-2/2026/02/01/17/"
        "20260201T173052540Z_0b98d2144de6272e.json"
    )
    records = parse_bedrock_records(path.read_bytes(), key=path.name)
    assert len(records) == 1
    input_tokens, output_tokens, _ = extract_token_counts(records[0])
    assert input_tokens == 5000
    assert output_tokens == 5233


def test_parse_records_multiple_lines():
    payload = (
        b'{"timestamp":"2026-02-01T00:00:00Z","input":{"inputTokenCount":1},"output":{"outputTokenCount":2}}\n'
        b'{"timestamp":"2026-02-01T00:00:01Z","input":{"inputTokenCount":3},"output":{"outputTokenCount":4}}\n'
    )
    records = parse_bedrock_records(payload, key="inline.json")
    assert len(records) == 2


@pytest.mark.parametrize(
    "model_id,expected",
    [
        # US inference profile -> keep prefix, strip :0
        (
            "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0",
            "us.anthropic.claude-opus-4-5-20251101-v1",
        ),
        # Global inference profile -> keep prefix (different from us!)
        (
            "arn:aws:bedrock:us-east-2:123456789012:inference-profile/global.anthropic.claude-opus-4-5-20251101-v1:0",
            "global.anthropic.claude-opus-4-5-20251101-v1",
        ),
        # EU inference profile -> keep prefix
        (
            "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "eu.anthropic.claude-3-5-sonnet-20241022-v2",
        ),
        # APAC inference profile -> keep prefix
        (
            "arn:aws:bedrock:ap-northeast-1:123456789012:inference-profile/apac.meta.llama3-2-11b-instruct-v1:0",
            "apac.meta.llama3-2-11b-instruct-v1",
        ),
        # Direct model ID (no ARN) - suffix stripped
        (
            "anthropic.claude-3-haiku-20240307-v1:0",
            "anthropic.claude-3-haiku-20240307-v1",
        ),
        # Unknown / fallback - unchanged
        ("unknown", "unknown"),
        # Empty string - unchanged
        ("", ""),
    ],
)
def test_normalize_model_id(model_id: str, expected: str):
    assert normalize_model_id(model_id) == expected


def test_normalize_model_id_keeps_regional_and_global_separate():
    """Verify that us. and global. prefixes are kept separate (BREAKING CHANGE)."""
    us_arn = "arn:aws:bedrock:us-east-2:992382809180:inference-profile/us.anthropic.claude-opus-4-5-20251101-v1:0"
    global_arn = "arn:aws:bedrock:us-east-2:992382809180:inference-profile/global.anthropic.claude-opus-4-5-20251101-v1:0"
    # Breaking change: us. and global. are now tracked separately
    assert normalize_model_id(us_arn) == "us.anthropic.claude-opus-4-5-20251101-v1"
    assert normalize_model_id(global_arn) == "global.anthropic.claude-opus-4-5-20251101-v1"
    assert normalize_model_id(us_arn) != normalize_model_id(global_arn)
