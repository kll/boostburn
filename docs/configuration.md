# Configuration

Boostburn uses YAML files for configuration and environment variables for runtime settings.

## Regions Configuration

Create your own `config/regions.yaml` file (ignored by git) to specify your AWS account and log bucket locations. See the tracked example: [`config/regions.example.yaml`](../config/regions.example.yaml)

```yaml
account_id: "123456789012"
log_prefix: ""
regions:
  us-east-1: bedrock-logs-123456789012-us-east-1
  us-west-2: bedrock-logs-123456789012-us-west-2
```

### Fields

- **account_id**: Your AWS account ID
- **log_prefix**: Optional prefix for log paths (usually empty)
- **regions**: Map of AWS region names to their corresponding S3 bucket names

## Pricing Configuration

Pricing is loaded from `config/pricing.yaml` (tracked in git). The file uses a flat structure where each model + inference profile combination is a separate entry.

### Structure

```yaml
generated_at: '2026-02-01T23:18:20.978517+00:00'
source: https://aws.amazon.com/bedrock/pricing/
rates:
  # Inference profile entries (scope.provider.model-version)
  global.anthropic.claude-opus-4-5-20251101-v1:
    default:
      currency: USD
      input_per_1k: 0.006
      output_per_1k: 0.018

  us.anthropic.claude-opus-4-5-20251101-v1:
    default:
      currency: USD
      input_per_1k: 0.005
      output_per_1k: 0.015

  eu.anthropic.claude-opus-4-5-20251101-v1:
    default:
      currency: USD
      input_per_1k: 0.0052
      output_per_1k: 0.016

  # Non-profile entry (direct model invocation)
  anthropic.claude-opus-4-5-20251101-v1:
    default:
      currency: USD
      input_per_1k: 0.005
      output_per_1k: 0.015
```

### Key Format

Pricing keys must exactly match the model identifiers in your Bedrock logs:

- **Inference profiles**: Include the scope prefix (`global.`, `us.`, `eu.`, `apac.`, etc.)
- **Direct invocation**: Use the full Bedrock model ID without the scope prefix
- **Version suffix**: Omit the trailing `:0` or `:X` from model IDs (e.g., use `v1` not `v1:0`)

### Inference Profile Pricing

AWS Bedrock has different pricing tiers based on inference profile type:

- **Global cross-region** (`global.*`) - Highest cost, automatic cross-region routing
- **Geo-specific** (`us.*`, `eu.*`, `apac.*`) - Lower cost, regional deployment
- **Direct invocation** (no prefix) - Varies by model

Each inference profile must have its own entry in `pricing.yaml`. The system does NOT fall back or use aliases - pricing must be explicitly defined for each profile used in your logs.

### Region-Specific Overrides

You can specify different rates for specific regions:

```yaml
rates:
  us.anthropic.claude-opus-4-5-20251101-v1:
    default:
      currency: USD
      input_per_1k: 0.005
      output_per_1k: 0.015
    us-west-2:  # Override for this region
      currency: USD
      input_per_1k: 0.0055
      output_per_1k: 0.016
```

When a region-specific rate exists, it takes precedence over the `default` rate.

### Updating Pricing

> **Note:** The pricing scraper (`scripts/scrape_bedrock_pricing.py`) is an early prototype and should not be relied upon yet. Manual updates to `config/pricing.yaml` are recommended until the scraper is more mature.

To manually scrape pricing (use with caution):

```bash
python scripts/scrape_bedrock_pricing.py --output config/pricing.yaml --region us-east-2
```

To parse from a saved HTML file:

```bash
python scripts/scrape_bedrock_pricing.py --html /path/to/bedrock-pricing.html --output config/pricing.yaml
```

## Pricing Maintenance

Boostburn requires explicit pricing entries for each Claude model version. When AWS releases new model versions, you must update `config/pricing.yaml`.

### Detecting Missing Pricing

Slack reports will show **"UNPRICED MODELS DETECTED"** warnings when models are missing from pricing configuration.

### Adding New Model Versions

1. Identify the model ID from the warning (e.g., `global.anthropic.claude-haiku-4-5-20251001-v1`)
2. Check AWS Bedrock pricing page for the model's rates
3. Add entries for all inference profile variants (global, us, eu) to `config/pricing.yaml`
4. Run tests to verify: `pytest tests/test_pricing.py`
5. Re-run the workflow to generate updated report

### No Automatic Fallback

The system will NOT use similar model versions as fallback. Each version requires an explicit pricing entry to ensure accurate cost tracking.

Example:
- `claude-haiku-4-5-20241022-v1` cannot be used for
- `claude-haiku-4-5-20251001-v1` (requires separate entry)

## Environment Variables

Boostburn loads a `.env` file from the repo root if present. Existing environment variables take precedence over `.env` values. A starter template is available in [`.env.example`](../.env.example).

### AWS Configuration

- **AWS_PROFILE** (optional): AWS profile name for credentials
- **AWS_ACCESS_KEY_ID** / **AWS_SECRET_ACCESS_KEY** (optional): AWS credentials

### Boostburn Settings

- **BOOSTBURN_CONFIG_PATH**: Path to your regions config file (required)
  - Example: `config/regions.yaml`

- **BOOSTBURN_PRICING_PATH** (optional): Path to pricing config
  - Default: `config/pricing.yaml`

- **BOOSTBURN_STATE_DIR** (optional): Directory for state files (snapshots, manifests)
  - Default: `state`

- **BOOSTBURN_MANIFEST_PREFIX** (optional): S3 prefix for manifest files
  - Default: `manifests`

- **BOOSTBURN_LOOKBACK_HOURS** (optional): How many hours back to scan for logs
  - Default: `6`

- **BOOSTBURN_REPORT_DATE** (optional): Report date in `YYYY-MM-DD` format
  - Default: Current date (UTC)

- **BOOSTBURN_LOG_PREFIX** (optional): Override log prefix from regions config

- **BOOSTBURN_CSV_PATH** (optional): Path to append CSV report rows
  - If not set, CSV output is disabled
  - File is created if it doesn't exist

### Slack Integration

See [`docs/slack-setup.md`](slack-setup.md) for detailed setup instructions.

- **SLACK_WEBHOOK_URL** (optional): Slack incoming webhook URL
  - If not set, Slack output is disabled

- **SLACK_CHANNEL** (optional): Override webhook's default channel
  - Example: `#bedrock-usage`

- **SLACK_USERNAME** (optional): Custom bot display name
  - Default: `Boostburn`

### Example `.env` File

```env
# AWS Configuration
AWS_PROFILE=my-profile

# Boostburn Configuration
BOOSTBURN_CONFIG_PATH=config/regions.yaml
BOOSTBURN_PRICING_PATH=config/pricing.yaml
BOOSTBURN_STATE_DIR=state
BOOSTBURN_LOOKBACK_HOURS=6

# Slack (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_CHANNEL=#bedrock-usage
SLACK_USERNAME=Bedrock Usage Bot

# CSV Output (optional)
BOOSTBURN_CSV_PATH=reports/daily-usage.csv
```

## CLI Options

All environment variables can be overridden via CLI flags:

```bash
boostburn --report-date 2026-02-01 --lookback-hours 12 --config config/regions.yaml
```

Available options:

- `--report-date YYYY-MM-DD`: Report date
- `--lookback-hours N`: Hours to look back for logs
- `--config PATH`: Path to regions config
- `--pricing PATH`: Path to pricing config
- `--state-dir PATH`: State directory
- `--csv PATH`: CSV output path
- `--force-reprocess`: Skip merging with existing snapshot (start fresh)

Run `boostburn --help` for the full list.

## Daily Aggregation

When Boostburn runs multiple times for the same report date, it automatically merges metrics from previous runs. This ensures cumulative daily totals across multiple executions.

**Normal behavior:**
1. First run: Creates snapshot with metrics A
2. Second run: Loads snapshot, merges A + B, saves merged snapshot
3. Reports always show cumulative totals

**Force reprocess mode:**

Use `--force-reprocess` to completely regenerate a report from scratch:

```bash
boostburn --report-date 2026-02-01 --force-reprocess
```

When enabled, `--force-reprocess`:
- **Rescans the entire report date range** (all 24 hours for the specified date)
- **Ignores the manifest's last_datehour optimization** (normally used to scan only recent logs)
- **Reprocesses all objects found**, even if already seen
- **Skips loading the previous snapshot** for that date
- Overwrites any existing snapshot with fresh data

This is useful for:
- Regenerating reports after updating pricing data
- Recovering from corrupt snapshots
- Debugging discrepancies in daily totals

**Note:** While `--force-reprocess` rescans and reprocesses all objects, it still records processed objects in the manifest to maintain state consistency.
