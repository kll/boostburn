from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3

from .adapters.aws_s3 import AwsS3Adapter
from .adapters.pricing import StaticPricingProvider
from .adapters.report_store import ReportStore
from .adapters.slack import SlackWebhookAdapter
from .env import load_dotenv
from .graph.workflow import Dependencies, RunConfig, build_graph


def _create_slack_adapter() -> Optional[SlackWebhookAdapter]:
    """Create Slack adapter from environment variables."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return None
    slack_channel = os.getenv("SLACK_CHANNEL")
    slack_username = os.getenv("SLACK_USERNAME")
    return SlackWebhookAdapter(webhook_url, channel=slack_channel, username=slack_username)


def main() -> None:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(description="Run the Boostburn daily Bedrock usage report")
    parser.add_argument("--config", default=os.getenv("BOOSTBURN_CONFIG_PATH", "config/regions.yaml"))
    parser.add_argument(
        "--pricing-path",
        default=os.getenv("BOOSTBURN_PRICING_PATH", "config/pricing.yaml"),
    )
    parser.add_argument("--manifest-prefix", default=os.getenv("BOOSTBURN_MANIFEST_PREFIX", "manifests"))
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=int(os.getenv("BOOSTBURN_LOOKBACK_HOURS", "6")),
    )
    parser.add_argument("--report-date", default=os.getenv("BOOSTBURN_REPORT_DATE"))
    parser.add_argument("--log-prefix", default=os.getenv("BOOSTBURN_LOG_PREFIX"))
    parser.add_argument("--state-dir", default=os.getenv("BOOSTBURN_STATE_DIR", "state"))
    parser.add_argument("--csv-path", default=os.getenv("BOOSTBURN_CSV_PATH"))
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode with raw log dumps to debug/ folder")
    parser.add_argument("--force-reprocess", action="store_true",
                        help="Rescan entire report date range and reprocess all objects, ignoring manifest optimization and previous snapshot")
    parser.add_argument("--test-slack", action="store_true",
                        help="Send a test message to Slack to validate webhook configuration")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("boostburn")

    # Handle --test-slack before checking AWS credentials
    if args.test_slack:
        slack_adapter = _create_slack_adapter()
        if slack_adapter is None:
            print("Error: SLACK_WEBHOOK_URL not set in environment")
            raise SystemExit(1)

        print("Testing Slack webhook...")
        try:
            slack_adapter.post_message("🧪 Boostburn webhook test successful!")
            print("✓ Test message posted successfully!")
        except Exception as e:
            print(f"✗ Slack webhook test failed: {e}")
            raise SystemExit(1)

        return

    _ensure_aws_credentials()

    slack_adapter = _create_slack_adapter()

    state_dir = Path(args.state_dir)
    csv_path = Path(args.csv_path) if args.csv_path else None
    report_store = ReportStore(state_dir=state_dir, csv_path=csv_path)
    pricing_path = Path(args.pricing_path)
    if not pricing_path.exists():
        raise SystemExit(
            f"Pricing file not found at {pricing_path}. "
            "Run scripts/scrape_bedrock_pricing.py to generate it or set BOOSTBURN_PRICING_PATH."
        )

    deps = Dependencies(
        s3=AwsS3Adapter(),
        pricing=StaticPricingProvider(pricing_path=pricing_path),
        report_store=report_store,
        slack=slack_adapter,
        logger=logger,
    )

    run_config = RunConfig(
        config_path=args.config,
        manifest_prefix=args.manifest_prefix,
        lookback_hours=args.lookback_hours,
        report_date=args.report_date,
        log_prefix_override=args.log_prefix,
        now_fn=lambda: datetime.now(timezone.utc),
        debug=args.debug,
        force_reprocess=args.force_reprocess,
    )
    graph = build_graph(deps, run_config)
    graph.invoke({})


def _ensure_aws_credentials() -> None:
    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise SystemExit(
            "AWS credentials not found. Set AWS_PROFILE or AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY, "
            "or run 'aws configure' before running boostburn."
        )
    frozen = credentials.get_frozen_credentials()
    if not frozen.access_key or not frozen.secret_key:
        raise SystemExit(
            "AWS credentials are incomplete. Set AWS_PROFILE or AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY, "
            "or run 'aws configure' before running boostburn."
        )


if __name__ == "__main__":
    main()
