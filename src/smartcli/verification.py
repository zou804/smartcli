"""Verification summaries derived from persisted tool evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

VerificationStatus = Literal["verified", "partially_verified", "failed", "unverified"]


@dataclass(frozen=True)
class CheckEvidence:
    name: str
    status: Literal["passed", "failed"]
    exit_code: int | None
    backend: str | None
    action_index: int


@dataclass(frozen=True)
class VerificationSummary:
    status: VerificationStatus
    required_checks: tuple[str, ...]
    checks: tuple[CheckEvidence, ...]
    changed_files: tuple[str, ...]
    unverified: tuple[str, ...]
    risks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "required_checks": list(self.required_checks),
            "checks": [asdict(item) for item in self.checks],
            "changed_files": list(self.changed_files),
            "unverified": list(self.unverified),
            "risks": list(self.risks),
        }


def build_verification(
    actions: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    required_checks: tuple[str, ...],
) -> VerificationSummary:
    """Reduce chronological action evidence into a conservative verification state."""
    last_write = max(
        (
            index
            for index, action in enumerate(actions)
            if action.get("tool") in {"write_file", "apply_patch"}
            and action.get("success") is True
        ),
        default=-1,
    )
    latest: dict[str, CheckEvidence] = {}
    for index, action in enumerate(actions):
        if index <= last_write or action.get("tool") != "run_check":
            continue
        metadata = action.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("check"), str):
            continue
        name = metadata["check"]
        exit_code = metadata.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            exit_code = None
        backend = metadata.get("backend")
        latest[name] = CheckEvidence(
            name=name,
            status="passed" if action.get("success") is True and exit_code == 0 else "failed",
            exit_code=exit_code,
            backend=backend if isinstance(backend, str) else None,
            action_index=index,
        )

    checks = tuple(sorted(latest.values(), key=lambda item: item.action_index))
    missing = tuple(name for name in required_checks if name not in latest)
    failed = tuple(
        name
        for name in required_checks
        if name in latest and latest[name].status == "failed"
    )
    passed = any(item.status == "passed" for item in checks)
    if failed:
        status: VerificationStatus = "failed"
    elif not checks:
        status = "unverified"
    elif not missing:
        status = "verified"
    elif passed:
        status = "partially_verified"
    else:
        status = "unverified"

    changed_files = tuple(
        sorted(
            {
                str(change["path"])
                for change in changes
                if change.get("state") == "applied" and isinstance(change.get("path"), str)
            }
        )
    )
    risks = tuple(f"Required check failed: {name}" for name in failed)
    return VerificationSummary(
        status,
        tuple(required_checks),
        checks,
        changed_files,
        missing,
        risks,
    )
