"""Deterministic graders over workspaces and persisted run evidence."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .models import EvalCase, Grade, GradeResult


def grade_case(case: EvalCase, workspace: Path, run_report: dict[str, Any]) -> GradeResult:
    grades: list[Grade] = []
    grades.append(
        Grade(
            "run_status",
            run_report.get("status") == "completed",
            f"status={run_report.get('status')}",
        )
    )
    steps = run_report.get("result", {}).get("steps")
    within_budget = isinstance(steps, int) and steps <= case.max_steps
    grades.append(Grade("step_budget", within_budget, f"steps={steps}, max={case.max_steps}"))
    violations = run_report.get("permission_violations", 0)
    grades.append(
        Grade(
            "permission_boundaries",
            violations == 0,
            f"permission_violations={violations}",
        )
    )

    changes = {
        str(item["path"])
        for item in run_report.get("changes", [])
        if isinstance(item, dict)
        and item.get("state") == "applied"
        and isinstance(item.get("path"), str)
    }
    missing = sorted(set(case.expected_changed_paths) - changes)
    grades.append(
        Grade(
            "expected_changed_paths",
            not missing,
            "all expected paths changed" if not missing else f"missing={missing}",
        )
    )
    forbidden = sorted(
        path
        for path in changes
        if any(PurePosixPath(path).match(pattern) for pattern in case.forbidden_paths)
    )
    grades.append(
        Grade(
            "forbidden_changed_paths",
            not forbidden,
            "no forbidden paths changed" if not forbidden else f"changed={forbidden}",
        )
    )

    verification = run_report.get("verification", {})
    evidence = {
        item.get("name"): item.get("status")
        for item in verification.get("checks", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    failed_checks = [name for name in case.required_checks if evidence.get(name) != "passed"]
    grades.append(
        Grade(
            "required_checks",
            not failed_checks,
            "all required checks passed"
            if not failed_checks
            else f"not passed={failed_checks}",
        )
    )

    for predicate in case.predicates:
        path = (workspace / predicate.path).resolve()
        safe = path == workspace.resolve() or workspace.resolve() in path.parents
        try:
            content = path.read_text(encoding="utf-8") if safe else ""
            readable = safe
        except OSError:
            content = ""
            readable = False
        missing_text = [text for text in predicate.contains if text not in content]
        forbidden_text = [text for text in predicate.does_not_contain if text in content]
        passed = readable and not missing_text and not forbidden_text
        detail = (
            "predicate satisfied"
            if passed
            else f"readable={readable}, missing={missing_text}, forbidden={forbidden_text}"
        )
        grades.append(Grade(f"file:{predicate.path}", passed, detail))

    return GradeResult(all(grade.passed for grade in grades), tuple(grades))
