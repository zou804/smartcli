from __future__ import annotations

import io
import json

import pytest

from smartcli import cli
from smartcli.commands.ask import MAX_STDIN_CHARS, read_piped_input
from smartcli.services.llm import ResponseText
from smartcli.services.prompts import ROLE_PROMPTS, get_role_prompt


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTCLI_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setenv("SMARTCLI_NOTES_PATH", str(tmp_path / "notes.json"))
    monkeypatch.setenv("SMARTCLI_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("SMARTCLI_RUNS_PATH", str(tmp_path / "runs"))
    monkeypatch.setenv("SMARTCLI_EVALS_PATH", str(tmp_path / "evals"))
    return tmp_path


def run_cli(argv, stdin=""):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli.run(argv, stdin=io.StringIO(stdin), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_help_and_version(capsys):
    with pytest.raises(SystemExit) as help_exit:
        cli.run(["--help"])
    assert help_exit.value.code == 0
    assert "ask" in capsys.readouterr().out

    with pytest.raises(SystemExit) as version_exit:
        cli.run(["--version"])
    assert version_exit.value.code == 0
    assert "smartcli 0.9.0" in capsys.readouterr().out


@pytest.mark.parametrize("role", ROLE_PROMPTS)
def test_every_cli_role_maps_to_a_prompt(role):
    assert "lightweight Markdown" in get_role_prompt(role)


def test_unknown_role_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["ask", "question", "--role", "unknown"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_unknown_role_from_service_returns_error(monkeypatch):
    monkeypatch.setattr(cli, "_resolved_ai_options", lambda args: ("missing", "deepseek"))
    code, stdout, stderr = run_cli(["ask", "question"])
    assert code == 1 and not stdout and "Unknown role: missing" in stderr


def test_ask_direct_question(isolated_paths, monkeypatch):
    captured = {}

    def fake_ask(message, role, model):
        captured.update(message=message, role=role, model=model)
        return "answer"

    monkeypatch.setattr(cli, "ask_once", fake_ask)
    code, stdout, stderr = run_cli(["ask", "What is a descriptor?"])
    assert (code, stdout, stderr) == (0, "answer\n", "")
    assert captured == {
        "message": "What is a descriptor?",
        "role": "default",
        "model": "deepseek",
    }


def test_agent_command_runs_react_final_response(isolated_paths, monkeypatch):
    class FakeAgentLLM:
        def request(self, messages):
            return '{"thought":"done","final":"agent answer"}'

    monkeypatch.setattr(cli, "LLMService", lambda model: FakeAgentLLM())
    code, stdout, stderr = run_cli(["agent", "finish this task", "--max-steps", "2"])
    assert code == 0 and stdout == "agent answer\n" and "Run ID: run_" in stderr
    assert "Verification: unverified" in stderr


def test_agent_verbose_does_not_print_model_thought(isolated_paths, monkeypatch):
    class FakeAgentLLM:
        def request(self, messages):
            return '{"thought":"private rationale","final":"done"}'

    monkeypatch.setattr(cli, "LLMService", lambda model: FakeAgentLLM())
    code, stdout, stderr = run_cli(["agent", "finish", "--verbose"])
    assert (code, stdout) == (0, "done\n")
    assert "private rationale" not in stderr


def test_agent_rejects_invalid_step_limit(isolated_paths):
    code, stdout, stderr = run_cli(["agent", "task", "--max-steps", "0"])
    assert code == 1 and not stdout and "between 1 and 100" in stderr


def test_agent_reports_invalid_project_policy_before_model_call(isolated_paths):
    (isolated_paths / "smartcli.toml").write_text(
        '[execution]\nnetwork = "host"\n', encoding="utf-8"
    )
    code, stdout, stderr = run_cli(
        ["agent", "inspect", "--workspace", str(isolated_paths), "--json"]
    )
    payload = json.loads(stdout)
    assert code == 1 and not stderr
    assert payload["error"]["type"] == "PolicyError"
    assert "network" in payload["error"]["message"]


def test_agent_is_read_only_by_default_and_validates_capabilities(isolated_paths, capsys):
    assert cli._agent_tools().names() == ("list_files", "read_file", "note_search")
    assert cli._agent_tools({"write"}).names() == (
        "list_files",
        "read_file",
        "note_search",
        "write_file",
        "apply_patch",
    )
    assert cli._agent_tools({"git"}).names()[-1] == "git"
    assert cli._agent_tools({"check"}).names()[-1] == "run_check"
    with pytest.raises(SystemExit) as exc:
        cli.run(["agent", "task", "--allow", "shell"])
    assert exc.value.code == 2 and "invalid choice" in capsys.readouterr().err


def test_agent_dry_run_skips_write_and_redacts_audit(isolated_paths, monkeypatch):
    class FakeAgentLLM:
        calls = 0

        def request(self, messages):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "thought": "write",
                        "action": {
                            "tool": "write_file",
                            "arguments": {"path": "result.txt", "content": "private body"},
                        },
                    }
                )
            return '{"thought":"done","final":"planned"}'

    monkeypatch.setattr(cli, "LLMService", lambda model: FakeAgentLLM())
    code, stdout, stderr = run_cli(
        [
            "agent",
            "prepare a file",
            "--allow",
            "write",
            "--dry-run",
            "--workspace",
            str(isolated_paths),
        ]
    )
    assert code == 0 and stdout == "planned\n" and "Dry run" in stderr
    assert not (isolated_paths / "result.txt").exists()
    audit = json.loads((isolated_paths / "audit.jsonl").read_text(encoding="utf-8"))
    assert audit["dry_run"] is True and audit["executed"] is False
    assert audit["arguments"]["path"] == "result.txt"
    assert "private body" not in json.dumps(audit)


def test_approve_risky_never_bypasses_file_write_confirmation(isolated_paths, monkeypatch):
    class FakeAgentLLM:
        calls = 0

        def request(self, messages):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "thought": "write",
                        "action": {
                            "tool": "write_file",
                            "arguments": {"path": "unsafe.txt", "content": "untrusted"},
                        },
                    }
                )
            return '{"thought":"done","final":"write denied"}'

    monkeypatch.setattr(cli, "LLMService", lambda model: FakeAgentLLM())
    code, stdout, stderr = run_cli(
        [
            "agent",
            "write a file",
            "--allow",
            "write",
            "--approve-risky",
            "--workspace",
            str(isolated_paths),
        ]
    )
    assert code == 0 and stdout == "write denied\n"
    assert "requires confirmation" in stderr
    assert not (isolated_paths / "unsafe.txt").exists()


def test_ask_warns_when_provider_truncates_response(isolated_paths, monkeypatch):
    monkeypatch.setattr(
        cli, "ask_once", lambda message, role, model: ResponseText("partial", truncated=True)
    )
    code, stdout, stderr = run_cli(["ask", "long review"])
    assert code == 0 and stdout == "partial\n"
    assert "output limit" in stderr


def test_ask_stdin_and_combined_input(isolated_paths, monkeypatch):
    messages = []
    monkeypatch.setattr(
        cli, "ask_once", lambda message, role, model: messages.append(message) or "ok"
    )
    assert run_cli(["ask"], "traceback")[0] == 0
    assert messages[-1] == "Input from stdin:\ntraceback"
    assert run_cli(["ask", "debug this"], "traceback")[0] == 0
    assert messages[-1] == "User instruction:\ndebug this\n\nInput from stdin:\ntraceback"


def test_ask_empty_and_oversized_stdin_are_errors(isolated_paths):
    code, stdout, stderr = run_cli(["ask"])
    assert code == 1 and not stdout and "Provide a question" in stderr
    code, stdout, stderr = run_cli(["ask"], "x" * (MAX_STDIN_CHARS + 1))
    assert code == 1 and not stdout and "character limit" in stderr


def test_piped_input_replaces_invalid_unicode_surrogates():
    result = read_piped_input(io.StringIO("diff contents \udc80"))
    assert result == "diff contents ?"
    result.encode("utf-8", errors="strict")


def test_ask_save_creates_ai_note(isolated_paths, monkeypatch):
    monkeypatch.setattr(cli, "ask_once", lambda message, role, model: "Use __get__.")
    code, stdout, stderr = run_cli(["ask", "Descriptors", "--save", "--tag", "Python"])
    assert code == 0 and stdout == "Use __get__.\n" and "Saved note" in stderr
    data = json.loads((isolated_paths / "notes.json").read_text(encoding="utf-8"))
    assert data[0]["source"] == "ai"
    assert data[0]["model"] == "deepseek"
    assert data[0]["role"] == "default"
    assert data[0]["tags"] == ["Python"]
    assert "Descriptors" in data[0]["content"]


def test_cli_note_workflow_and_error_status(isolated_paths):
    code, stdout, _ = run_cli(["note", "add", "Useful Python fact", "--tag", "Python"])
    note_id = stdout.split("[")[1].split("]")[0]
    assert code == 0
    assert note_id in run_cli(["note", "list"])[1]
    assert note_id in run_cli(["note", "search", "python"])[1]
    assert "Useful Python fact" in run_cli(["note", "show", note_id])[1]
    assert run_cli(["note", "delete", note_id])[0] == 0
    code, _, stderr = run_cli(["note", "delete", note_id])
    assert code == 1 and "Note not found" in stderr


def test_config_show_never_prints_api_key(isolated_paths, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "top-secret")
    code, stdout, stderr = run_cli(["config", "show"])
    assert code == 0 and not stderr
    assert "default_model" in stdout and "top-secret" not in stdout
    assert run_cli(["config", "set", "default_role", "review"])[0] == 0
    code, _, stderr = run_cli(["config", "set", "api_key", "bad"])
    assert code == 1 and "Unsupported" in stderr


def test_json_success_and_error_envelopes(isolated_paths, monkeypatch):
    monkeypatch.setattr(
        cli,
        "ask_once",
        lambda message, role, model: ResponseText("answer", attempts=2),
    )
    code, stdout, stderr = run_cli(["ask", "question", "--json"])
    payload = json.loads(stdout)
    assert code == 0 and not stderr and payload["ok"] is True
    assert payload["command"] == "ask"
    assert payload["data"]["answer"] == "answer"
    assert payload["data"]["attempts"] == 2

    code, stdout, stderr = run_cli(["config", "set", "api_key", "bad", "--json"])
    payload = json.loads(stdout)
    assert code == 1 and not stderr and payload["ok"] is False
    assert payload["command"] == "config.set"
    assert payload["error"]["type"] == "ConfigurationError"

    code, stdout, stderr = run_cli(["--json", "config", "show"])
    payload = json.loads(stdout)
    assert code == 0 and not stderr and payload["command"] == "config.show"


def test_model_profile_cli_workflow_and_json_output(isolated_paths):
    add_args = [
        "model",
        "add",
        "localdev",
        "--provider",
        "ollama",
        "--model-id",
        "qwen-test",
        "--base-url",
        "http://localhost:11434/v1",
        "--timeout",
        "25",
        "--connect-timeout",
        "3",
        "--retries",
        "1",
        "--json",
    ]
    code, stdout, stderr = run_cli(add_args)
    added = json.loads(stdout)
    assert code == 0 and not stderr and added["data"]["name"] == "localdev"
    assert added["data"]["timeout_seconds"] == 25.0

    code, stdout, _ = run_cli(["model", "show", "localdev", "--json"])
    shown = json.loads(stdout)
    assert code == 0 and shown["data"]["model_id"] == "qwen-test"
    assert run_cli(["config", "set", "default_model", "localdev"])[0] == 0

    code, stdout, _ = run_cli(["doctor", "--json"])
    diagnosis = json.loads(stdout)
    assert code == 0 and diagnosis["data"]["healthy"] is True
    assert any(
        check["name"] == "connection" and check["status"] == "skipped"
        for check in diagnosis["data"]["checks"]
    )


def test_agent_json_output(isolated_paths, monkeypatch):
    class FakeAgentLLM:
        def request(self, messages):
            return '{"thought":"done","plan":["inspect"],"final":"safe"}'

    monkeypatch.setattr(cli, "LLMService", lambda model: FakeAgentLLM())
    code, stdout, stderr = run_cli(["agent", "inspect", "--json"])
    payload = json.loads(stdout)
    assert code == 0 and not stderr and payload["data"]["final"] == "safe"
    assert payload["data"]["steps"] == 1
    assert payload["data"]["verification"]["status"] == "unverified"
    assert payload["data"]["telemetry"]["model"]["calls"] == 1
    assert payload["data"]["run_id"].startswith("run_")
    run_id = payload["data"]["run_id"]
    code, stdout, stderr = run_cli(["run", "list", "--json"])
    listed = json.loads(stdout)
    assert code == 0 and not stderr and listed["data"][0]["run_id"] == run_id
    code, stdout, stderr = run_cli(["run", "show", run_id, "--json"])
    shown = json.loads(stdout)
    assert code == 0 and not stderr and shown["data"]["status"] == "completed"


def test_eval_cli_runs_scripted_case_and_reads_report(isolated_paths):
    case = isolated_paths / "case"
    fixture = case / "fixture"
    fixture.mkdir(parents=True)
    document = {
        "schema_version": 1,
        "id": "cli_eval",
        "task": "Create result.txt",
        "capabilities": ["write"],
        "required_checks": [],
        "expected_changed_paths": ["result.txt"],
        "forbidden_paths": [],
        "max_steps": 2,
        "predicates": [{"path": "result.txt", "contains": ["ok"]}],
        "decisions": [
            {
                "thought": "write",
                "action": {
                    "tool": "write_file",
                    "arguments": {"path": "result.txt", "content": "ok\n"},
                },
            },
            {"thought": "done", "final": "done"},
        ],
    }
    (case / "case.json").write_text(json.dumps(document), encoding="utf-8")
    code, stdout, stderr = run_cli(["eval", "run", str(case), "--json"])
    payload = json.loads(stdout)["data"]
    assert code == 0 and not stderr and payload["passed"] is True
    report_id = payload["report_id"]
    code, stdout, stderr = run_cli(["eval", "report", report_id, "--json"])
    assert code == 0 and not stderr
    assert json.loads(stdout)["data"]["cases"][0]["case_id"] == "cli_eval"
