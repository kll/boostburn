from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


class SlackAdapter:
    def post_message(self, text: str, blocks: Optional[List[Dict[str, Any]]] = None) -> None:
        raise NotImplementedError


@dataclass
class SlackWebhookAdapter(SlackAdapter):
    webhook_url: str
    channel: Optional[str] = None
    username: Optional[str] = None

    def post_message(self, text: str, blocks: Optional[List[Dict[str, Any]]] = None) -> None:
        payload: Dict[str, Any] = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        if self.channel:
            payload["channel"] = self.channel
        if self.username:
            payload["username"] = self.username
        response = requests.post(self.webhook_url, json=payload, timeout=10)
        response.raise_for_status()

        # Slack webhooks return "ok" on success, error message on failure
        response_text = response.text.strip()
        if response_text != "ok":
            raise RuntimeError(
                f"Slack webhook returned unexpected response: {response_text}"
            )


class RecordingSlackAdapter(SlackAdapter):
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    def post_message(self, text: str, blocks: Optional[List[Dict[str, Any]]] = None) -> None:
        self.messages.append({"text": text, "blocks": blocks})
