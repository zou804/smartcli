"""Unified model adapter with explicit timeout and retry behavior."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from ..config import ConfigManager, ConfigurationError, ModelProfile, get_model_config


class LLMRequestError(RuntimeError):
    """Raised when the provider rejects or cannot complete a request."""


class EmptyResponseError(LLMRequestError):
    """Raised when a successful response has no usable text."""


class ResponseText(str):
    """Model text with completion and retry metadata."""

    truncated: bool
    attempts: int

    def __new__(
        cls, value: str, *, truncated: bool = False, attempts: int = 1
    ) -> ResponseText:
        instance = super().__new__(cls, value)
        instance.truncated = truncated
        instance.attempts = attempts
        return instance


class OpenAICompatibleAdapter:
    def __init__(
        self,
        profile: ModelProfile,
        *,
        client: Any | None = None,
        environ: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        env_prefix: str | None = None,
    ) -> None:
        self.config = profile
        self.sleep = sleep
        environment = os.environ if environ is None else environ
        if environ is None:
            load_dotenv(override=False)
        env_prefix = env_prefix or (profile.api_key_env or "SMARTCLI").removesuffix("_API_KEY")
        self.model_id = environment.get(f"{env_prefix}_MODEL", profile.model_id)
        self.base_url = environment.get(f"{env_prefix}_BASE_URL", profile.base_url)
        api_key = environment.get(profile.api_key_env) if profile.api_key_env else None
        if profile.api_key_env and not api_key:
            raise ConfigurationError(
                f"Missing API key. Set the {profile.api_key_env} environment variable."
            )
        self._secrets = tuple(value for value in (api_key,) if value)
        timeout = httpx.Timeout(
            profile.timeout_seconds, connect=profile.connect_timeout_seconds
        )
        self.client = client or OpenAI(
            api_key=api_key or "local",
            base_url=self.base_url,
            timeout=timeout,
            max_retries=0,
        )

    def request(self, messages: Sequence[Mapping[str, str]]) -> ResponseText:
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=list(messages),
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                break
            except Exception as exc:
                retryable = self._is_retryable(exc)
                if not retryable or attempts > self.config.max_retries:
                    category = "transient" if retryable else "permanent"
                    message = str(exc)
                    for secret in self._secrets:
                        message = message.replace(secret, "<redacted>")
                    raise LLMRequestError(
                        f"Model request failed ({category}, attempts={attempts}): {message}"
                    ) from exc
                self.sleep(min(0.5 * (2 ** (attempts - 1)), 8.0))

        choices = getattr(response, "choices", None)
        if not choices:
            raise EmptyResponseError("Model returned no choices")
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if not isinstance(content, str) or not content.strip():
            raise EmptyResponseError("Model returned empty content")
        return ResponseText(
            content,
            truncated=getattr(choice, "finish_reason", None) == "length",
            attempts=attempts,
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(
            exc,
            (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
        ):
            return True
        status_code = getattr(exc, "status_code", None)
        return isinstance(exc, APIStatusError) and (
            status_code == 429 or (isinstance(status_code, int) and status_code >= 500)
        )


class OllamaAdapter(OpenAICompatibleAdapter):
    """Ollama uses the same OpenAI-compatible request contract."""


class LLMService:
    def __init__(
        self,
        model_name: str,
        *,
        client: Any | None = None,
        environ: Mapping[str, str] | None = None,
        manager: ConfigManager | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_name = model_name
        self.config = get_model_config(model_name, manager=manager)
        adapter_type = (
            OllamaAdapter if self.config.provider == "ollama" else OpenAICompatibleAdapter
        )
        self.adapter = adapter_type(
            self.config,
            client=client,
            environ=environ,
            sleep=sleep,
            env_prefix=model_name.upper().replace("-", "_")
        )

    @property
    def client(self) -> Any:
        return self.adapter.client

    def request(self, messages: Sequence[Mapping[str, str]]) -> ResponseText:
        return self.adapter.request(messages)
