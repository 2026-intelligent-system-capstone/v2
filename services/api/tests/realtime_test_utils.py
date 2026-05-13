from __future__ import annotations

import json
import time

from websockets.exceptions import ConnectionClosedOK


class FakeLlm:
    def __init__(
        self, response: str = "no", enabled: bool = True, delay: float = 0.0
    ) -> None:
        self.response = response
        self._enabled = enabled
        self.delay = delay
        self.calls: list[dict[str, object]] = []

    def enabled(self) -> bool:
        return self._enabled

    def chat(self, messages, temperature, max_tokens) -> str:
        if self.delay:
            time.sleep(self.delay)
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


class FakeBrowserWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = list(messages)
        self.sent_json: list[dict] = []

    async def receive(self) -> dict:
        if self._messages:
            return self._messages.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, data: dict) -> None:
        self.sent_json.append(data)


class FakeOaiWebSocket:
    def __init__(
        self, receive_events: list[dict | str] | None = None, fail_send: bool = False
    ) -> None:
        self.sent: list[dict] = []
        self._receive_events = list(receive_events or [])
        self.fail_send = fail_send

    async def send(self, raw: str) -> None:
        if self.fail_send:
            raise RuntimeError("OAI send failed")
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self._receive_events:
            raise ConnectionClosedOK(None, None)
        event = self._receive_events.pop(0)
        if isinstance(event, str):
            return event
        return json.dumps(event)
