"""Unified adapters for OpenAI-compatible and Ollama endpoints."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from ..config import ConfigurationError, ModelConfig, get_model_config


class LLMRequestError(RuntimeError):
    """Raised when the provider rejects or cannot complete a request."""


class EmptyResponseError(LLMRequestError):
    """Raised when a successful response has no usable text."""


class ResponseText(str):
    """Model text with provider completion metadata."""

    truncated: bool

    def __new__(cls, value: str, *, truncated: bool = False) -> ResponseText:
        instance = super().__new__(cls, value)
        instance.truncated = truncated
        return instance


class OpenAICompatibleAdapter:
    """Adapter for OpenAI and providers exposing its chat-completions protocol."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        client: Any | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        environment = os.environ if environ is None else environ
        if environ is None:
            load_dotenv(override=False)
        env_prefix = (
            "OLLAMA"
            if self.config.provider == "ollama"
            else (self.config.api_key_env or "SMARTCLI").removesuffix("_API_KEY")
        )
        self.model_id = environment.get(f"{env_prefix}_MODEL", self.config.model_id)
        self.base_url = environment.get(f"{env_prefix}_BASE_URL", self.config.base_url)
        api_key = environment.get(self.config.api_key_env) if self.config.api_key_env else None
        if self.config.api_key_env and not api_key:
            raise ConfigurationError(
                f"Missing API key. Set the {self.config.api_key_env} environment variable."
            )
        self.client = client or OpenAI(api_key=api_key or "local", base_url=self.base_url)

    def request(self, messages: Sequence[Mapping[str, str]]) -> ResponseText:
        """Return response text for a structured message history."""
        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=list(messages),
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
        except Exception as exc:
            raise LLMRequestError(f"Model request failed: {exc}") from exc

        choices = getattr(response, "choices", None)
        if not choices:
            raise EmptyResponseError("Model returned no choices")
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if not isinstance(content, str) or not content.strip():
            raise EmptyResponseError("Model returned empty content")
        return ResponseText(content, truncated=getattr(choice, "finish_reason", None) == "length")


class OllamaAdapter(OpenAICompatibleAdapter):
    """Adapter for Ollama's local OpenAI-compatible endpoint."""


class LLMService:
    """Backwards-compatible facade selecting an adapter from the model registry."""

    def __init__(
        self,
        model_name: str,
        *,
        client: Any | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.model_name = model_name
        self.config = get_model_config(model_name)
        adapter_type = (
            OllamaAdapter if self.config.provider == "ollama" else OpenAICompatibleAdapter
        )
        self.adapter = adapter_type(self.config, client=client, environ=environ)

    @property
    def client(self) -> Any:
        return self.adapter.client

    def request(self, messages: Sequence[Mapping[str, str]]) -> ResponseText:
        return self.adapter.request(messages)
