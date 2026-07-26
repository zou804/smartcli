"""Strict repository policy that may constrain but never grant Agent authority."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class PolicyError(RuntimeError):
    """Raised when smartcli.toml contains an invalid or unsafe policy."""


KNOWN_CHECKS = ("tests", "lint", "compile")


@dataclass(frozen=True)
class ExecutionPolicy:
    backend: str = "local"
    image: str | None = None
    network: str = "none"
    timeout_seconds: int = 120
    memory_mb: int = 512
    cpus: float = 1.0
    pids_limit: int = 128


@dataclass(frozen=True)
class WorkspacePolicy:
    writable: tuple[str, ...] = ()
    protected: tuple[str, ...] = ()

    def can_write(self, relative_path: str) -> bool:
        normalized = PurePosixPath(relative_path.replace("\\", "/"))
        if any(normalized.match(pattern) for pattern in self.protected):
            return False
        return not self.writable or any(normalized.match(pattern) for pattern in self.writable)


@dataclass(frozen=True)
class ChecksPolicy:
    allowed: tuple[str, ...] = KNOWN_CHECKS
    required: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectPolicy:
    execution: ExecutionPolicy = ExecutionPolicy()
    workspace: WorkspacePolicy = WorkspacePolicy()
    checks: ChecksPolicy = ChecksPolicy()


def load_project_policy(workspace: Path) -> ProjectPolicy:
    path = workspace.resolve() / "smartcli.toml"
    if not path.exists():
        return ProjectPolicy()
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"Cannot read project policy: {exc}") from exc
    _reject_unknown("root", document, {"execution", "workspace", "checks"})
    execution = _execution_policy(_table(document, "execution"))
    workspace_policy = _workspace_policy(_table(document, "workspace"))
    checks = _checks_policy(_table(document, "checks"))
    return ProjectPolicy(execution, workspace_policy, checks)


def _table(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise PolicyError(f"Policy {name} must be a table")
    return value


def _execution_policy(value: dict[str, Any]) -> ExecutionPolicy:
    _reject_unknown(
        "execution",
        value,
        {"backend", "image", "network", "timeout_seconds", "memory_mb", "cpus", "pids_limit"},
    )
    backend = _string(value, "backend", "local")
    if backend not in {"local", "docker"}:
        raise PolicyError("execution.backend must be local or docker")
    image_value = value.get("image")
    if image_value is not None and (not isinstance(image_value, str) or not image_value.strip()):
        raise PolicyError("execution.image must be a non-empty string")
    image = image_value.strip() if isinstance(image_value, str) else None
    if backend == "docker" and image is None:
        raise PolicyError("execution.image is required for the docker backend")
    network = _string(value, "network", "none")
    if network != "none":
        raise PolicyError("execution.network currently only supports none")
    timeout = _integer(value, "timeout_seconds", 120, 1, 600)
    memory = _integer(value, "memory_mb", 512, 64, 32768)
    cpus = _number(value, "cpus", 1.0, 0.1, 64.0)
    pids = _integer(value, "pids_limit", 128, 16, 4096)
    return ExecutionPolicy(backend, image, network, timeout, memory, cpus, pids)


def _workspace_policy(value: dict[str, Any]) -> WorkspacePolicy:
    _reject_unknown("workspace", value, {"writable", "protected"})
    return WorkspacePolicy(
        _patterns(value, "writable"),
        _patterns(value, "protected"),
    )


def _checks_policy(value: dict[str, Any]) -> ChecksPolicy:
    _reject_unknown("checks", value, {"allowed", "required"})
    allowed = _check_names(value, "allowed", KNOWN_CHECKS)
    required = _check_names(value, "required", ())
    if not set(required).issubset(allowed):
        raise PolicyError("checks.required must be a subset of checks.allowed")
    return ChecksPolicy(allowed, required)


def _reject_unknown(section: str, value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PolicyError(f"Policy {section} contains unknown key(s): {', '.join(unknown)}")


def _string(value: dict[str, Any], name: str, default: str) -> str:
    result = value.get(name, default)
    if not isinstance(result, str) or not result.strip():
        raise PolicyError(f"execution.{name} must be a non-empty string")
    return result.strip()


def _integer(value: dict[str, Any], name: str, default: int, low: int, high: int) -> int:
    result = value.get(name, default)
    if not isinstance(result, int) or isinstance(result, bool) or not low <= result <= high:
        raise PolicyError(f"execution.{name} must be between {low} and {high}")
    return result


def _number(value: dict[str, Any], name: str, default: float, low: float, high: float) -> float:
    result = value.get(name, default)
    if (
        not isinstance(result, (int, float))
        or isinstance(result, bool)
        or not low <= float(result) <= high
    ):
        raise PolicyError(f"execution.{name} must be between {low} and {high}")
    return float(result)


def _patterns(value: dict[str, Any], name: str) -> tuple[str, ...]:
    result = value.get(name, [])
    if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
        raise PolicyError(f"workspace.{name} must be an array of strings")
    for pattern in result:
        path = PurePosixPath(pattern.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not pattern:
            raise PolicyError(f"workspace.{name} contains an unsafe pattern: {pattern!r}")
    return tuple(dict.fromkeys(result))


def _check_names(
    value: dict[str, Any], name: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    result = value.get(name, list(default))
    if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
        raise PolicyError(f"checks.{name} must be an array of strings")
    unknown = sorted(set(result) - set(KNOWN_CHECKS))
    if unknown:
        raise PolicyError(f"checks.{name} contains unknown check(s): {', '.join(unknown)}")
    return tuple(dict.fromkeys(result))
