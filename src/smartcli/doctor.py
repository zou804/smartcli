"""Offline-first installation and model profile diagnostics."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from platformdirs import user_data_path

from .config import ConfigManager, ConfigurationError
from .services.llm import LLMRequestError, LLMService


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def run_doctor(
    manager: ConfigManager,
    *,
    model_name: str | None = None,
    connect: bool = False,
    environ: Mapping[str, str] | None = None,
    service_factory: Callable[[str], Any] | None = None,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    version = sys.version_info
    status = "ok" if version >= (3, 11) else "error"
    checks.append(
        DoctorCheck("python", status, f"Python {version.major}.{version.minor}.{version.micro}")
    )
    try:
        config = manager.load()
        profiles = manager.profiles()
        checks.append(DoctorCheck("config", "ok", str(manager.filepath)))
    except ConfigurationError as exc:
        checks.append(DoctorCheck("config", "error", str(exc)))
        return checks

    data_root = user_data_path("smartcli")
    for name, path in (
        ("config_directory", manager.filepath.parent),
        ("data_directory", data_root),
    ):
        ancestor = _existing_ancestor(path)
        writable = os.access(ancestor, os.W_OK)
        checks.append(
            DoctorCheck(name, "ok" if writable else "error", f"{path} (parent: {ancestor})")
        )

    selected = model_name or config["default_model"]
    profile = profiles.get(selected)
    if profile is None:
        checks.append(DoctorCheck("model_profile", "error", f"Unknown profile: {selected}"))
        return checks
    checks.append(
        DoctorCheck(
            "model_profile",
            "ok",
            f"{selected}: {profile.provider}/{profile.model_id} at {profile.base_url}",
        )
    )

    environment = os.environ if environ is None else environ
    if environ is None:
        load_dotenv(override=False)
    key_ready = profile.api_key_env is None or bool(environment.get(profile.api_key_env))
    if profile.api_key_env:
        checks.append(
            DoctorCheck(
                "api_key",
                "ok" if key_ready else "error",
                (
                    f"{profile.api_key_env} is set"
                    if key_ready
                    else f"{profile.api_key_env} is not set"
                ),
            )
        )
    else:
        checks.append(DoctorCheck("api_key", "ok", "Profile does not require an API key"))

    if connect:
        if not key_ready:
            checks.append(DoctorCheck("connection", "error", "Skipped because API key is missing"))
        else:
            try:
                service = (
                    service_factory(selected)
                    if service_factory is not None
                    else LLMService(selected, manager=manager, environ=environment)
                )
                service.request([{"role": "user", "content": "Reply with OK."}])
                checks.append(DoctorCheck("connection", "ok", "Model request succeeded"))
            except (ConfigurationError, LLMRequestError) as exc:
                checks.append(DoctorCheck("connection", "error", str(exc)))
    else:
        checks.append(DoctorCheck("connection", "skipped", "Use --connect to test the endpoint"))
    return checks


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate
