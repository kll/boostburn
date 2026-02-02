import os
from pathlib import Path

from boostburn.env import load_dotenv


def test_load_dotenv(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# comment",
                "BOOSTBURN_REPORT_DATE=2026-02-01",
                "SLACK_WEBHOOK_URL=https://example.com/hook",
                "QUOTED=\"hello world\"",
                "EMPTY=",
                "COMMENTED=value # inline comment",
                "BADLINE",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("BOOSTBURN_REPORT_DATE", "preset")
    load_dotenv(Path(env_path))

    assert os.getenv("BOOSTBURN_REPORT_DATE") == "preset"
    assert os.getenv("SLACK_WEBHOOK_URL") == "https://example.com/hook"
    assert os.getenv("QUOTED") == "hello world"
    assert os.getenv("EMPTY") == ""
    assert os.getenv("COMMENTED") == "value"
