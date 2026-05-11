from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import OpenAI as _OpenAI


class LlmClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        max_retries: int = 2,
        retry_delay_seconds: float = 0.25,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self._client: _OpenAI | None = None
        if api_key:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key)

    def enabled(self) -> bool:
        return self._client is not None

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        if self._client is None:
            raise RuntimeError("LLM client is disabled (no API key)")
        response = self._with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                **self._completion_options(temperature=temperature, max_tokens=max_tokens),
            )
        )
        return response.choices[0].message.content or ""

    def parse(
        self,
        messages: list[dict[str, str]],
        schema: type[Any],
        temperature: float = 0.2,
        max_tokens: int = 3000,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("LLM client is disabled (no API key)")
        response = self._with_retry(
            lambda: self._client.chat.completions.parse(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                response_format=schema,
                **self._completion_options(temperature=temperature, max_tokens=max_tokens),
            )
        )
        message = response.choices[0].message
        if message.parsed is None:
            refusal = getattr(message, "refusal", None)
            raise RuntimeError(refusal or "LLM response could not be parsed")
        return message.parsed

    def _with_retry(self, call: Callable[[], Any]) -> Any:
        attempts = max(1, self.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return call()
            except Exception as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
                time.sleep(self.retry_delay_seconds * (2**attempt))
        if last_error is None:
            raise RuntimeError("LLM 호출이 실행되지 않았습니다.")
        raise last_error

    def _completion_options(self, temperature: float, max_tokens: int) -> dict[str, Any]:
        model = self.model.strip().lower()
        if model.startswith(("gpt-5", "o1", "o3", "o4")):
            return {"max_completion_tokens": max_tokens}
        return {"temperature": temperature, "max_tokens": max_tokens}
