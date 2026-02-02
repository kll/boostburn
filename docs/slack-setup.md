# Slack Integration Setup

This guide walks you through setting up Slack to receive daily Bedrock usage reports from Boostburn.

## Overview

Boostburn uses Slack Incoming Webhooks to post daily usage reports. This is an optional feature - if you don't configure Slack, reports will still be written to local files.

## Required Configuration

To enable Slack integration, you need to set the `SLACK_WEBHOOK_URL` environment variable. Optionally, you can customize the channel and username.

### Environment Variables

- `SLACK_WEBHOOK_URL` - Webhook URL for posting messages (required to enable Slack)
- `SLACK_CHANNEL` - Override the default channel (optional, e.g., `#aws-usage`)
- `SLACK_USERNAME` - Custom bot username (optional, e.g., `Boostburn Bot`)

## Step-by-Step Setup

### 1. Create a Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App**
3. Choose **From scratch**
4. Enter an app name (e.g., "Boostburn Reports")
5. Select your workspace
6. Click **Create App**

### 2. Enable Incoming Webhooks

1. In your app settings, click **Incoming Webhooks** in the sidebar
2. Toggle **Activate Incoming Webhooks** to **On**
3. Scroll down and click **Add New Webhook to Workspace**
4. Select the channel where you want reports posted
5. Click **Allow**

### 3. Copy the Webhook URL

After authorizing, you'll see your webhook URL in the format:

```
https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
```

Copy this URL - you'll need it for your `.env` file.

### 4. Configure Environment Variables

Add the webhook URL to your `.env` file:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
```

#### Optional: Override Channel

If you want to post to a different channel than the one configured in the webhook:

```bash
SLACK_CHANNEL=#different-channel
```

#### Optional: Custom Username

To display a custom bot name instead of your app name:

```bash
SLACK_USERNAME=Bedrock Usage Bot
```

### 5. Test the Integration

First, test the webhook configuration without running a full report:

```bash
boostburn --test-slack
```

If the webhook is valid, you'll see:
```
Testing Slack webhook...
✓ Test message posted successfully!
```

If there's an error, you'll see a detailed error message explaining what went wrong.

After confirming the webhook works, run a daily report to verify full integration:

```bash
boostburn --report-date 2026-02-01
```

If configured correctly, you should see a message posted to your Slack channel with the usage summary.

## Message Format

Boostburn posts a text summary of daily usage including:

- Total tokens processed (input/output)
- Total estimated cost
- Breakdown by region
- Breakdown by identity (user/role ARN)
- Breakdown by model

## Troubleshooting

### Testing Your Webhook

Always start by testing your webhook configuration:

```bash
boostburn --test-slack
```

This will immediately tell you if your webhook is working or show you the exact error.

### No message appears in Slack

**Important:** A 200 OK HTTP response doesn't guarantee Slack posted your message. Boostburn now validates that Slack returned `"ok"` in the response body, which confirms successful delivery.

If you see an error like `Slack webhook returned unexpected response: channel_not_found`, this means:

1. **First, test the webhook:**
   ```bash
   boostburn --test-slack
   ```

2. **Common error responses and solutions:**
   - `channel_not_found` - The channel doesn't exist or the webhook was deleted
   - `channel_is_archived` - The target channel has been archived
   - `invalid_token` - The webhook URL has been revoked or is invalid
   - `missing_text_or_fallback_or_attachments` - The message format was invalid (shouldn't happen with Boostburn)

3. **If the webhook is invalid:**
   - Go to your [Slack app settings](https://api.slack.com/apps)
   - Navigate to **Incoming Webhooks**
   - Check if your webhook still exists
   - If not, create a new webhook (steps 2-3 above) and update your `.env`

4. **Verify manually with curl:**
   ```bash
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"text":"Manual test"}' \
     YOUR_WEBHOOK_URL
   ```
   - Should return `ok` if valid
   - Will return an error message if invalid

### Webhook appears valid but still fails

1. Check that `SLACK_WEBHOOK_URL` is set in your `.env` file
2. Ensure there are no extra spaces or quotes around the URL
3. Check the terminal output for any error messages
4. Ensure the app has permission to post to the target channel

### Message appears in wrong channel

The webhook has a default channel set during creation. To override it:

```bash
SLACK_CHANNEL=#correct-channel
```

Make sure to include the `#` prefix for public channels or `@` for direct messages.

### Webhook stopped working

Webhooks can be revoked if:
- The app is uninstalled from the workspace
- The webhook is manually deleted from the app settings
- The workspace is migrated or deleted

To fix: Generate a new webhook URL following steps 2-3 above and update your `.env` file.

## Security Notes

- **Never commit your webhook URL to version control** - it's already in `.gitignore` via `.env`
- Webhook URLs are sensitive - anyone with the URL can post to your channel
- If a webhook URL is exposed, revoke it in your app settings and generate a new one
- Consider using workspace-level secrets management for production deployments

## Further Customization

The Slack adapter currently supports basic text messages. For richer formatting (buttons, images, interactive elements), you would need to modify `src/boostburn/adapters/slack.py` to use Slack's Block Kit format.

See the [Slack Block Kit documentation](https://api.slack.com/block-kit) for more advanced formatting options.
