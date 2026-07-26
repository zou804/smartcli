from __future__ import annotations

import pytest

from smartcli.verification import build_verification


def write(success=True):
    return {"tool": "write_file", "success": success, "metadata": {}}


def check(name, exit_code=0, backend="local"):
    return {
        "tool": "run_check",
        "success": exit_code == 0,
        "metadata": {"check": name, "exit_code": exit_code, "backend": backend},
    }


@pytest.mark.parametrize(
    ("actions", "required", "status", "unverified"),
    [
        ([], ("tests",), "unverified", ("tests",)),
        ([check("tests"), check("lint")], ("tests", "lint"), "verified", ()),
        ([check("tests")], ("tests", "lint"), "partially_verified", ("lint",)),
        ([check("tests", 1)], ("tests",), "failed", ()),
        ([check("compile")], (), "verified", ()),
        ([check("tests"), write()], ("tests",), "unverified", ("tests",)),
    ],
)
def test_verification_state_matrix(actions, required, status, unverified):
    summary = build_verification(actions, [], required)
    assert summary.status == status
    assert summary.unverified == unverified


def test_verification_keeps_latest_qualifying_evidence_and_changed_files():
    actions = [
        write(),
        check("tests", 1),
        check("tests", 0, "docker"),
        check("lint", 0, "docker"),
    ]
    changes = [
        {"path": "src/b.py", "state": "applied"},
        {"path": "src/a.py", "state": "failed"},
        {"path": "src/b.py", "state": "applied"},
    ]
    value = build_verification(actions, changes, ("tests", "lint"))
    assert value.status == "verified" and value.changed_files == ("src/b.py",)
    assert [item.name for item in value.checks] == ["tests", "lint"]
    assert value.checks[0].status == "passed"
    assert value.checks[0].backend == "docker" and value.checks[0].action_index == 2
    assert value.to_dict()["checks"][0]["exit_code"] == 0
