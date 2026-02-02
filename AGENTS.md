# Agent Notes

## Purpose

This repo will implement a LangGraph-based workflow that collects AWS Bedrock model usage and posts a daily report to Slack.

## Working Agreement

- Read docs/assignment.md before making structural changes.
- Do not implement production logic without a clear plan and user confirmation.
- Keep configuration in environment variables; do not commit secrets.
- Prefer small, well-scoped modules and clear state definitions for the graph.
- Add tests and eval fixtures alongside new functionality.
- **Always update the mermaid diagram in README.md whenever the graph structure changes**, even if not explicitly instructed. The diagram must accurately reflect the current node connections and flow.
- **Breaking changes are acceptable. Do not add backwards compatibility code.** Keep implementations minimal and clean.
- **Always update documentation when making changes.** If you change configuration formats, CLI options, environment variables, or behavior, update the relevant documentation files immediately. Documentation must stay in sync with the implementation.

## Project Conventions

- Python 3.13 via a virtual environment at `.venv/`.
- Use `src/` layout when code is introduced.
- Keep tool integrations behind adapters (AWS/Slack).
- Log structured data suitable for evals.
- Use `.env` for local configuration; keep it uncommitted and update `.env.example` when adding env vars. The `state/` folder stores snapshots and pricing cache.

## Known Limitations

- The pricing scraper (`scripts/scrape_bedrock_pricing.py`) is an early prototype and should not be relied upon yet. Update `config/pricing.yaml` manually until the scraper is more mature.
