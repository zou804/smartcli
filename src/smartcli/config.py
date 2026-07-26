"""Model profiles and persistent non-secret user configuration."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from platformdirs import user_config_path

from .services.prompts import ROLE_PROMPTS
from .storage import InterProcessFileLock, StorageLockError


class ConfigurationError(RuntimeError):
    """Raised for invalid or inaccessible configuration."""


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model_id: str
    base_url: str
    api_key_env: str | None
    max_tokens: int = 2048
    temperature: float = 0.7
    timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 2

    def validate(self) -> None:
        if self.provider not in {"openai_compatible", "ollama"}:
            raise ConfigurationError(f"Unsupported provider: {self.provider}")
        if not self.model_id.strip():
            raise ConfigurationError("Model ID cannot be empty")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigurationError("Model base URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ConfigurationError("Model base URL must not contain credentials")
        if self.api_key_env is not None and not re.fullmatch(
            r"[A-Z_][A-Z0-9_]*", self.api_key_env
        ):
            raise ConfigurationError("API key environment variable must use uppercase shell syntax")
        if not 1 <= self.max_tokens <= 1_000_000:
            raise ConfigurationError("max_tokens must be between 1 and 1,000,000")
        if not 0 <= self.temperature <= 2:
            raise ConfigurationError("temperature must be between 0 and 2")
        if not 1 <= self.timeout_seconds <= 600:
            raise ConfigurationError("timeout_seconds must be between 1 and 600")
        if not 0.1 <= self.connect_timeout_seconds <= self.timeout_seconds:
            raise ConfigurationError(
                "connect_timeout_seconds must be between 0.1 and timeout_seconds"
            )
        if not 0 <= self.max_retries <= 10:
            raise ConfigurationError("max_retries must be between 0 and 10")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ModelProfile:
        try:
            profile = cls(
                provider=str(value["provider"]),
                model_id=str(value["model_id"]),
                base_url=str(value["base_url"]),
                api_key_env=(
                    str(value["api_key_env"]) if value.get("api_key_env") is not None else None
                ),
                max_tokens=int(value.get("max_tokens", 2048)),
                temperature=float(value.get("temperature", 0.7)),
                timeout_seconds=float(value.get("timeout_seconds", 60.0)),
                connect_timeout_seconds=float(value.get("connect_timeout_seconds", 10.0)),
                max_retries=int(value.get("max_retries", 2)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(f"Invalid model profile: {exc}") from exc
        profile.validate()
        return profile


ModelConfig = ModelProfile

BUILTIN_PROFILES: dict[str, ModelProfile] = {
    "deepseek": ModelProfile(
        provider="openai_compatible",
        model_id="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    "glm": ModelProfile(
        provider="openai_compatible",
        model_id="glm-4-flash",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="GLM_API_KEY",
    ),
    "openai": ModelProfile(
        provider="openai_compatible",
        model_id="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    ),
    "ollama": ModelProfile(
        provider="ollama",
        model_id="qwen2.5:7b",
        base_url="http://localhost:11434/v1",
        api_key_env=None,
    ),
}
AVAILABLE_MODELS = BUILTIN_PROFILES
DEFAULT_CONFIG: dict[str, str] = {"default_model": "deepseek", "default_role": "default"}
ALLOWED_CONFIG_KEYS = frozenset(DEFAULT_CONFIG)


class ConfigManager:
    """Read and atomically update preferences and non-secret model profiles."""

    def __init__(self, filepath: str | Path | None = None) -> None:
        self.filepath = Path(filepath) if filepath else user_config_path("smartcli") / "config.json"

    def _load_document(self) -> dict[str, Any]:
        if not self.filepath.exists():
            return {**DEFAULT_CONFIG, "profiles": {}}
        try:
            value = json.loads(self.filepath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Cannot read configuration: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("Configuration must be a JSON object")
        profiles = value.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ConfigurationError("Configuration profiles must be a JSON object")
        document: dict[str, Any] = {
            **DEFAULT_CONFIG,
            **{key: str(value[key]) for key in ALLOWED_CONFIG_KEYS if key in value},
            "profiles": profiles,
        }
        self._validate_document(document)
        return document

    def load(self) -> dict[str, str]:
        document = self._load_document()
        return {key: str(document[key]) for key in ALLOWED_CONFIG_KEYS}

    def profiles(self) -> dict[str, ModelProfile]:
        custom = {
            name: ModelProfile.from_dict(value)
            for name, value in self._load_document()["profiles"].items()
        }
        return {**BUILTIN_PROFILES, **custom}

    def get_profile(self, name: str) -> ModelProfile:
        try:
            return self.profiles()[name]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown model profile: {name}") from exc

    def add_profile(self, name: str, profile: ModelProfile, *, replace: bool = False) -> None:
        self._validate_profile_name(name)
        profile.validate()
        if name in BUILTIN_PROFILES:
            raise ConfigurationError(f"Built-in model profile cannot be replaced: {name}")
        try:
            with InterProcessFileLock(self.filepath):
                document = self._load_document()
                if name in document["profiles"] and not replace:
                    raise ConfigurationError(f"Model profile already exists: {name}")
                document["profiles"][name] = profile.to_dict()
                self._atomic_write(document)
        except StorageLockError as exc:
            raise ConfigurationError(str(exc)) from exc

    def remove_profile(self, name: str) -> None:
        if name in BUILTIN_PROFILES:
            raise ConfigurationError(f"Built-in model profile cannot be removed: {name}")
        try:
            with InterProcessFileLock(self.filepath):
                document = self._load_document()
                if name not in document["profiles"]:
                    raise ConfigurationError(f"Unknown custom model profile: {name}")
                if document["default_model"] == name:
                    raise ConfigurationError("Cannot remove the default model profile")
                del document["profiles"][name]
                self._atomic_write(document)
        except StorageLockError as exc:
            raise ConfigurationError(str(exc)) from exc

    def set(self, key: str, value: str) -> dict[str, str]:
        if key not in ALLOWED_CONFIG_KEYS:
            raise ConfigurationError(f"Unsupported configuration key: {key}")
        try:
            with InterProcessFileLock(self.filepath):
                document = self._load_document()
                document[key] = value
                self._validate_document(document)
                self._atomic_write(document)
        except StorageLockError as exc:
            raise ConfigurationError(str(exc)) from exc
        return {name: str(document[name]) for name in ALLOWED_CONFIG_KEYS}

    def _validate_document(self, document: Mapping[str, Any]) -> None:
        custom_profiles = document.get("profiles", {})
        for name in custom_profiles:
            self._validate_profile_name(name)
            if name in BUILTIN_PROFILES:
                raise ConfigurationError(f"Custom profile cannot override built-in profile: {name}")
        profiles = {
            **BUILTIN_PROFILES,
            **{
                name: ModelProfile.from_dict(value)
                for name, value in custom_profiles.items()
            },
        }
        if document["default_model"] not in profiles:
            raise ConfigurationError(f"Unknown model profile: {document['default_model']}")
        if document["default_role"] not in ROLE_PROMPTS:
            raise ConfigurationError(f"Unknown role: {document['default_role']}")

    @staticmethod
    def _validate_profile_name(name: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", name):
            raise ConfigurationError(
                "Profile name must be 2-32 lowercase letters, digits, underscores, or hyphens"
            )

    def _atomic_write(self, value: Mapping[str, Any]) -> None:
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


def get_model_config(
    model_name: str, *, manager: ConfigManager | None = None
) -> ModelProfile:
    """Resolve a built-in or user-defined model profile."""
    if manager is None:
        override = os.getenv("SMARTCLI_CONFIG_PATH")
        manager = ConfigManager(Path(override) if override else None)
    return manager.get_profile(model_name)
