from __future__ import annotations

import json

import pytest

from smartcli.evals import EvalCase, EvalCaseError, EvalRunner, grade_case


def write_case(root, **overrides):
    root.mkdir()
    (root / "fixture").mkdir()
    document = {
        "schema_version": 1,
        "id": "create_result",
        "task": "Create result.txt",
        "capabilities": ["write"],
        "required_checks": [],
        "expected_changed_paths": ["result.txt"],
        "forbidden_paths": ["secret.txt"],
        "max_steps": 2,
        "predicates": [
            {"path": "result.txt", "contains": ["complete"], "does_not_contain": ["secret"]}
        ],
        "decisions": [
            {
                "thought": "write",
                "action": {
                    "tool": "write_file",
                    "arguments": {"path": "result.txt", "content": "complete\n"},
                },
            },
            {"thought": "done", "final": "created"},
        ],
    }
    document.update(overrides)
    (root / "case.json").write_text(json.dumps(document), encoding="utf-8")
    return root


def test_eval_case_rejects_unknown_fields_and_escaping_paths(tmp_path):
    unknown = write_case(tmp_path / "unknown", surprise=True)
    with pytest.raises(EvalCaseError, match="unknown"):
        EvalCase.from_path(unknown)
    escaping = write_case(tmp_path / "escaping", expected_changed_paths=["../outside"])
    with pytest.raises(EvalCaseError, match="unsafe path"):
        EvalCase.from_path(escaping)


def test_deterministic_grader_reports_named_failures(tmp_path):
    case = EvalCase.from_path(write_case(tmp_path / "case"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_text("wrong secret", encoding="utf-8")
    report = {
        "status": "completed",
        "result": {"steps": 3},
        "changes": [{"path": "result.txt", "state": "applied"}],
        "verification": {"status": "unverified", "checks": []},
        "permission_violations": 1,
    }
    grades = grade_case(case, workspace, report)
    assert not grades.passed
    failed = {grade.name for grade in grades.grades if not grade.passed}
    assert {"step_budget", "permission_boundaries", "file:result.txt"} <= failed


def test_offline_eval_runner_uses_scripted_agent_and_writes_reports(tmp_path):
    case_path = write_case(tmp_path / "case")
    report_root = tmp_path / "reports"
    report = EvalRunner(report_root=report_root).run(case_path)
    assert report.passed and report.cases[0].case_id == "create_result"
    assert report.cases[0].verification["status"] == "unverified"
    assert (report_root / f"{report.report_id}.json").is_file()
    assert (report_root / f"{report.report_id}.md").is_file()
    loaded = EvalRunner(report_root=report_root).get_report(report.report_id)
    assert loaded["passed"] is True and loaded["cases"][0]["case_id"] == "create_result"
