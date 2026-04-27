from __future__ import annotations

import os
import time

from exceptions import LLMError


class LLMClient:
    def __init__(self) -> None:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")

        if not anthropic_key and not openai_key:
            raise LLMError("MISSING_API_KEY")

        self._model = os.environ.get("MASP_MODEL", "claude-sonnet-4-6" if anthropic_key else "gpt-4o")
        self._max_tokens = int(os.environ.get("MASP_MAX_TOKENS", "1024"))
        self._timeout = float(os.environ.get("MASP_TIMEOUT_SECS", "30"))

        if anthropic_key:
            self._provider = "anthropic"
            import anthropic
            self._client = anthropic.Anthropic(api_key=anthropic_key, timeout=self._timeout)
        else:
            self._provider = "openai"
            import openai
            self._client = openai.OpenAI(api_key=openai_key, timeout=self._timeout)

    def call(self, system: str, user: str) -> str:
        for attempt in range(2):
            try:
                return self._call_once(system, user)
            except Exception as exc:
                if attempt == 0 and self._is_retryable(exc):
                    time.sleep(1)
                    continue
                raise LLMError(f"LLM call failed: {exc}") from exc
        raise LLMError("LLM call failed after retry")

    def _call_once(self, system: str, user: str) -> str:
        if self._provider == "anthropic":
            import anthropic
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return response.content[0].text
            except (anthropic.APITimeoutError, anthropic.RateLimitError):
                raise
            except anthropic.APIError as exc:
                raise LLMError(f"Anthropic API error: {exc}") from exc
        else:
            import openai
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return response.choices[0].message.content
            except (openai.APITimeoutError, openai.RateLimitError):
                raise
            except openai.APIError as exc:
                raise LLMError(f"OpenAI API error: {exc}") from exc

    def _is_retryable(self, exc: Exception) -> bool:
        if self._provider == "anthropic":
            import anthropic
            return isinstance(exc, (anthropic.APITimeoutError, anthropic.RateLimitError))
        else:
            import openai
            return isinstance(exc, (openai.APITimeoutError, openai.RateLimitError))

    def __repr__(self) -> str:
        return f"LLMClient(provider={self._provider!r}, model={self._model!r})"
