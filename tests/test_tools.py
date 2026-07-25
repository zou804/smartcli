from __future__ import annotations

from smartcli.tools import (
    ReadFileTool,
    RiskLevel,
    ShellTool,
    ToolContext,
    ToolRegistry,
    WriteFileTool,
)
from smartcli.tools.safety import ShellSafetyPolicy


def test_registry_exports_json_tool_specs():
    registry = ToolRegistry([ReadFileTool()])
    assert registry.names() == ("read_file",)
    assert registry.specs()[0]["input_schema"]["required"] == ["path"]


def test_file_tools_are_confined_to_workspace(tmp_path):
    context = ToolContext(tmp_path)
    write = WriteFileTool().execute({"path": "nested/file.txt", "content": "hello"}, context)
    assert write.success
    assert ReadFileTool().execute({"path": "nested/file.txt"}, context).output == "hello"
    escaped = ReadFileTool().execute({"path": "../outside.txt"}, context)
    assert not escaped.success and "escapes" in escaped.output


def test_shell_safety_policy_classifies_dangerous_commands():
    policy = ShellSafetyPolicy()
    assert policy.assess("git status")[0] is RiskLevel.SAFE
    assert policy.assess("Remove-Item old.txt")[0] is RiskLevel.HIGH
    assert policy.assess("Remove-Item C:\\ -Recurse -Force")[0] is RiskLevel.BLOCKED
    assert policy.assess("git reset --hard HEAD")[0] is RiskLevel.HIGH
    assert policy.assess("powershell -EncodedCommand ZQBjAGgAbwA=")[0] is RiskLevel.HIGH
    assert policy.assess("rm -rf /")[0] is RiskLevel.BLOCKED


def test_shell_tool_never_executes_blocked_command(tmp_path):
    result = ShellTool().execute({"command": "rm -rf /"}, ToolContext(tmp_path))
    assert not result.success and "blocked" in result.output
