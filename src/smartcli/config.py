"""Model registry and persistent user configuration."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path

from .services.prompts import ROLE_PROMPTS


class ConfigurationError(RuntimeError):
    """Raised for invalid or inaccessible configuration."""


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model_id: str
    base_url: str
    api_key_env: str | None
    max_tokens: int = 2048
    temperature: float = 0.7


AVAILABLE_MODELS: dict[str, ModelConfig] = {
    "deepseek": ModelConfig(
        provider="openai_compatible",
        model_id="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    "glm": ModelConfig(
        provider="openai_compatible",
        model_id="glm-4-flash",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="GLM_API_KEY",
    ),
    "openai": ModelConfig(
        provider="openai_compatible",
        model_id="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    ),
    "ollama": ModelConfig(
        provider="ollama",
        model_id="qwen2.5:7b",
        base_url="http://localhost:11434/v1",
        api_key_env=None,
    ),
}
DEFAULT_CONFIG: dict[str, str] = {"default_model": "deepseek", "default_role": "default"}
ALLOWED_CONFIG_KEYS = frozenset(DEFAULT_CONFIG)


def get_model_config(model_name: str) -> ModelConfig:
    """Return a configured model or fail explicitly."""
    try:
        return AVAILABLE_MODELS[model_name]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown model: {model_name}") from exc


class ConfigManager:
    """Read and atomically update non-secret user preferences."""

    def __init__(self, filepath: str | Path | None = None) -> None:
        self.filepath = Path(filepath) if filepath else user_config_path("smartcli") / "config.json"

    def load(self) -> dict[str, str]:
        if not self.filepath.exists():
            return DEFAULT_CONFIG.copy()
        try:
            value = json.loads(self.filepath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Cannot read configuration: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("Configuration must be a JSON object")
        config = DEFAULT_CONFIG | {
            key: str(val) for key, val in value.items() if key in ALLOWED_CONFIG_KEYS
        }
        self._validate(config)
        return config

    def set(self, key: str, value: str) -> dict[str, str]:
        if key not in ALLOWED_CONFIG_KEYS:
            raise ConfigurationError(f"Unsupported configuration key: {key}")
        config = self.load()
        config[key] = value
        self._validate(config)
        self._atomic_write(config)
        return config

    @staticmethod
    def _validate(config: Mapping[str, str]) -> None:
        get_model_config(config["default_model"])
        if config["default_role"] not in ROLE_PROMPTS:
            raise ConfigurationError(f"Unknown role: {config['default_role']}")

    def _atomic_write(self, value: dict[str, str]) -> None:
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.filepath.name}.", dir=self.filepath.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(value, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                os.replace(temp_name, self.filepath)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise ConfigurationError(f"Cannot write configuration: {exc}") from exc
