"""Strict models for deterministic Agent evaluation cases and reports."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..policy import KNOWN_CHECKS

_CASE_ID = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
_CAPABILITIES = {"write", "git", "check"}


class EvalCaseError(RuntimeError):
    """Raised when an evaluation case is invalid or unsafe."""


@dataclass(frozen=True)
class FilePredicate:
    path: str
    contains: tuple[str, ...] = ()
    does_not_contain: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    task: str
    root: Path
    fixture: Path
    capabilities: tuple[str, ...]
    required_checks: tuple[str, ...]
    expected_changed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    max_steps: int
    predicates: tuple[FilePredicate, ...]
    decisions: tuple[dict[str, Any], ...]

    @classmethod
    def from_path(cls, value: str | Path) -> EvalCase:
        root = Path(value).resolve()
        path = root / "case.json" if root.is_dir() else root
        root = path.parent.resolve()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvalCaseError(f"Cannot read eval case: {exc}") from exc
        if not isinstance(document, dict):
            raise EvalCaseError("Eval case must be a JSON object")
        allowed = {
            "schema_version",
            "id",
            "task",
            "capabilities",
            "required_checks",
            "expected_changed_paths",
            "forbidden_paths",
            "max_steps",
            "predicates",
            "decisions",
        }
        unknown = sorted(set(document) - allowed)
        if unknown:
            raise EvalCaseError(f"Eval case contains unknown field(s): {', '.join(unknown)}")
        if document.get("schema_version") != 1:
            raise EvalCaseError("Eval case schema_version must be 1")
        case_id = document.get("id")
        if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
            raise EvalCaseError("Eval case id must match [a-z][a-z0-9_-]{1,63}")
        task = document.get("task")
        if not isinstance(task, str) or not task.strip():
            raise EvalCaseError("Eval case task must be a non-empty string")
        capabilities = _strings(document, "capabilities")
        invalid_capabilities = sorted(set(capabilities) - _CAPABILITIES)
        if invalid_capabilities:
            raise EvalCaseError(f"Unknown eval capabilities: {', '.join(invalid_capabilities)}")
        required_checks = _strings(document, "required_checks")
        invalid_checks = sorted(set(required_checks) - set(KNOWN_CHECKS))
        if invalid_checks:
            raise EvalCaseError(f"Unknown required checks: {', '.join(invalid_checks)}")
        expected = _safe_paths(document, "expected_changed_paths")
        forbidden = _safe_paths(document, "forbidden_paths")
        max_steps = document.get("max_steps")
        valid_steps = (
            isinstance(max_steps, int)
            and not isinstance(max_steps, bool)
            and 1 <= max_steps <= 100
        )
        if not valid_steps:
            raise EvalCaseError("Eval case max_steps must be between 1 and 100")
        predicates_value = document.get("predicates", [])
        if not isinstance(predicates_value, list):
            raise EvalCaseError("Eval case predicates must be an array")
        predicates = tuple(_predicate(item) for item in predicates_value)
        decisions_value = document.get("decisions", [])
        if not isinstance(decisions_value, list) or not all(
            isinstance(item, dict) for item in decisions_value
        ):
            raise EvalCaseError("Eval case decisions must be an array of objects")
        fixture = (root / "fixture").resolve()
        if fixture.parent != root or not fixture.is_dir():
            raise EvalCaseError("Eval case fixture directory is missing")
        return cls(
            case_id,
            task.strip(),
            root,
            fixture,
            capabilities,
            required_checks,
            expected,
            forbidden,
            max_steps,
            predicates,
            tuple(decisions_value),
        )


@dataclass(frozen=True)
class Grade:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    grades: tuple[Grade, ...]


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    passed: bool
    grades: tuple[Grade, ...]
    verification: dict[str, Any]
    steps: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "grades": [asdict(grade) for grade in self.grades],
            "verification": self.verification,
            "steps": self.steps,
        }


@dataclass(frozen=True)
class EvalReport:
    report_id: str
    created_at: str
    passed: bool
    cases: tuple[EvalCaseResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_at": self.created_at,
            "passed": self.passed,
            "cases": [case.to_dict() for case in self.cases],
        }


def _strings(document: dict[str, Any], name: str) -> tuple[str, ...]:
    value = document.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EvalCaseError(f"Eval case {name} must be an array of strings")
    return tuple(dict.fromkeys(value))


def _safe_paths(document: dict[str, Any], name: str) -> tuple[str, ...]:
    paths = _strings(document, name)
    for value in paths:
        path = PurePosixPath(value.replace("\\", "/"))
        if not value or path.is_absolute() or ".." in path.parts:
            raise EvalCaseError(f"Eval case {name} contains unsafe path: {value!r}")
    return paths


def _predicate(value: Any) -> FilePredicate:
    if not isinstance(value, dict):
        raise EvalCaseError("Each eval predicate must be an object")
    unknown = sorted(set(value) - {"path", "contains", "does_not_contain"})
    if unknown:
        raise EvalCaseError(f"Eval predicate contains unknown field(s): {', '.join(unknown)}")
    paths = _safe_paths({"paths": [value.get("path")]}, "paths")
    contains = _strings(value, "contains")
    excludes = _strings(value, "does_not_contain")
    return FilePredicate(paths[0], contains, excludes)
