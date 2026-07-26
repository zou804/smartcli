from __future__ import annotations

import hashlib

import pytest

from smartcli.runs import RunStorageError, RunStore
from smartcli.tools import ToolContext, WriteFileTool


def test_run_journal_redacts_checkpoint_and_undoes_existing_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "value.txt"
    path.write_text("before", encoding="utf-8")
    before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    store = RunStore(tmp_path / "runs")
    journal = store.start(workspace, "update value")
    arguments = {
        "path": "value.txt",
        "content": "after",
        "overwrite": True,
        "expected_sha256": before_hash,
    }
    checkpoint = journal.prepare_action("write_file", arguments, ToolContext(workspace))
    result = WriteFileTool().execute(arguments, ToolContext(workspace))
    journal.record_action("write_file", arguments, result, checkpoint)
    journal.complete(final="done", steps=1, plan=("update",))

    report = store.public_report(journal.run_id)
    assert report["status"] == "completed"
    assert "before_content_base64" not in report["changes"][0]
    assert report["actions"][0]["arguments"]["sha256"]
    undo = store.undo(journal.run_id)
    assert undo["restored"] == ["value.txt"]
    assert path.read_text(encoding="utf-8") == "before"
    assert store.get(journal.run_id)["status"] == "undone"


def test_run_undo_removes_new_file_but_refuses_later_user_changes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = RunStore(tmp_path / "runs")
    journal = store.start(workspace, "create file")
    arguments = {"path": "new.txt", "content": "agent"}
    checkpoint = journal.prepare_action("write_file", arguments, ToolContext(workspace))
    result = WriteFileTool().execute(arguments, ToolContext(workspace))
    journal.record_action("write_file", arguments, result, checkpoint)
    journal.complete(final="done", steps=1, plan=())

    path = workspace / "new.txt"
    path.write_text("user changed it", encoding="utf-8")
    with pytest.raises(RunStorageError, match="changed after"):
        store.undo(journal.run_id)
    assert path.read_text(encoding="utf-8") == "user changed it"

    path.write_text("agent", encoding="utf-8")
    result = store.undo(journal.run_id)
    assert result["removed"] == ["new.txt"] and not path.exists()


def test_run_journal_persists_operational_telemetry(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = RunStore(tmp_path / "runs")
    journal = store.start(workspace, "measure")
    telemetry = {
        "duration_ms": 42,
        "model": {"calls": 1, "total_tokens": 7},
        "tools": {"calls": 0},
    }
    journal.set_telemetry(telemetry)
    journal.complete(final="done", steps=1, plan=())
    assert store.public_report(journal.run_id)["telemetry"] == telemetry
