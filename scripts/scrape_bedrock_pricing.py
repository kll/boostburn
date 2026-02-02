from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from boostburn.pricing_scraper import (
    PRICING_URL,
    build_pricing_payload,
    fetch_pricing_html,
    parse_pricing_html,
    write_pricing_yaml,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape AWS Bedrock pricing into a YAML table")
    parser.add_argument("--url", default=PRICING_URL)
    parser.add_argument("--output", default="config/pricing.yaml")
    parser.add_argument("--region", default=None, help="Region code to apply when tables lack a region column")
    parser.add_argument("--html", default=None, help="Path to a local HTML file to parse instead of fetching")
    args = parser.parse_args()

    if args.html:
        html = Path(args.html).read_text(encoding="utf-8")
        source = f"file://{Path(args.html).resolve()}"
    else:
        html = fetch_pricing_html(args.url)
        source = args.url

    rates, stats = parse_pricing_html(html, region_override=args.region)
    payload = build_pricing_payload(rates, source=source)
    output_path = Path(args.output)
    write_pricing_yaml(output_path, payload)

    print(f"Wrote pricing table to {output_path}")
    print(f"Tables used: {stats.tables_used}")
    print(f"Rows parsed: {stats.rows_parsed}")
    print(f"Models parsed: {stats.models_parsed}")


if __name__ == "__main__":
    main()
