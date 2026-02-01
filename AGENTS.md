# Agent Notes

## Purpose

This repo will implement a LangGraph-based workflow that collects AWS Bedrock model usage and posts a daily report to Slack.

## Working Agreement

- Read docs/assignment.md before making structural changes.
- Do not implement production logic without a clear plan and user confirmation.
- Keep configuration in environment variables; do not commit secrets.
- Prefer small, well-scoped modules and clear state definitions for the graph.
- Add tests and eval fixtures alongside new functionality.

## Project Conventions

- Python 3.13 via a virtual environment at `.venv/`.
- Use `src/` layout when code is introduced.
- Keep tool integrations behind adapters (AWS/Slack).
- Log structured data suitable for evals.
