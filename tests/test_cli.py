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
    assert "smartcli 0.2.1" in capsys.readouterr().out


@pytest.mark.parametrize("role", ROLE_PROMPTS)
def test_every_cli_role_maps_to_a_prompt(role):
    assert get_role_prompt(role)


def test_unknown_role_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["ask", "question", "--role", "unknown"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


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
