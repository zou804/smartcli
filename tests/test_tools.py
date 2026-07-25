from __future__ import annotations

import hashlib

import pytest

from smartcli.tools import (
    GitTool,
    ListFilesTool,
    ReadFileTool,
    RiskLevel,
    ToolContext,
    ToolRegistry,
    WriteFileTool,
)


def test_registry_exports_json_tool_specs():
    registry = ToolRegistry([ReadFileTool()])
    assert registry.names() == ("read_file",)
    assert registry.specs()[0]["input_schema"]["required"] == ["path"]


def test_file_tools_are_confined_to_workspace(tmp_path):
    context = ToolContext(tmp_path)
    write = WriteFileTool().execute({"path": "nested/file.txt", "content": "hello"}, context)
    assert write.success
    assert ReadFileTool().execute({"path": "nested/file.txt"}, context).output == "hello"
    assert ReadFileTool().execute({"path": "nested/file.txt"}, context).metadata[
        "sha256"
    ] == hashlib.sha256(b"hello").hexdigest()
    escaped = ReadFileTool().execute({"path": "../outside.txt"}, context)
    assert not escaped.success and "escapes" in escaped.output


def test_every_file_write_requires_review_and_overwrite_uses_optimistic_lock(tmp_path):
    tool = WriteFileTool()
    context = ToolContext(tmp_path)
    assert tool.assess_risk({"path": "new.txt"})[0] is RiskLevel.REVIEW
    assert tool.execute({"path": "value.txt", "content": "old"}, context).success
    missing = tool.execute(
        {"path": "value.txt", "content": "new", "overwrite": True}, context
    )
    assert not missing.success and "expected_sha256" in missing.output
    stale = tool.execute(
        {
            "path": "value.txt",
            "content": "new",
            "overwrite": True,
            "expected_sha256": "0" * 64,
        },
        context,
    )
    assert not stale.success and "changed since" in stale.output
    current_hash = hashlib.sha256(b"old").hexdigest()
    updated = tool.execute(
        {
            "path": "value.txt",
            "content": "new",
            "overwrite": True,
            "expected_sha256": current_hash,
        },
        context,
    )
    assert updated.success and (tmp_path / "value.txt").read_text(encoding="utf-8") == "new"


def test_file_tools_block_credentials_but_allow_env_templates(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=secret", encoding="utf-8")
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=", encoding="utf-8")
    context = ToolContext(tmp_path)
    assert not ReadFileTool().execute({"path": ".env"}, context).success
    assert ReadFileTool().execute({"path": ".env.example"}, context).success
    assert not WriteFileTool().execute(
        {"path": "private.key", "content": "secret"}, context
    ).success
    assert not WriteFileTool().execute(
        {"path": ".git/config", "content": "malicious"}, context
    ).success
    assert not WriteFileTool().execute(
        {"path": "huge.txt", "content": "x" * 1_000_001}, context
    ).success


def test_list_files_discovers_project_structure_without_sensitive_or_generated_paths(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("remote", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    result = ListFilesTool().execute(
        {"recursive": True, "max_entries": 20}, ToolContext(tmp_path)
    )
    assert result.success and "src/app.py" in result.output
    assert ".git" not in result.output and ".env" not in result.output


def test_git_tool_only_builds_fixed_read_only_commands(tmp_path, monkeypatch):
    tool = GitTool()
    command = tool._command("diff", {"path": ".", "staged": True}, tmp_path)
    assert command[0] == "git" and "core.fsmonitor=false" in command
    assert any(token.startswith("safe.directory=") for token in command)
    assert "--cached" in command and "--no-ext-diff" in command
    assert not any(token in command for token in ("-Command", "sh", "powershell"))
    with pytest.raises(ValueError, match="Unknown tool argument"):
        tool.execute(
            {"operation": "status", "command": "rm -rf /"}, ToolContext(tmp_path)
        )
    escaped = tool.execute(
        {"operation": "diff", "path": "../outside"}, ToolContext(tmp_path)
    )
    assert not escaped.success and "escapes" in escaped.output
    fake_git = tmp_path / "git.exe"
    fake_git.write_bytes(b"not executable")
    monkeypatch.setattr("smartcli.tools.git.shutil.which", lambda name: str(fake_git))
    refused = tool.execute({"operation": "status"}, ToolContext(tmp_path))
    assert not refused.success and "inside the workspace" in refused.output
