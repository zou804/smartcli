"""SmartCLI command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .agent import AgentError, ReActAgent
from .commands.ask import (
    TRUNCATION_WARNING,
    InputError,
    ask_once,
    chat,
    combine_input,
    read_piped_input,
)
from .commands.note import NoteManager, NoteNotFoundError, NoteStorageError
from .config import AVAILABLE_MODELS, ConfigManager, ConfigurationError
from .services.llm import LLMRequestError, LLMService
from .services.prompts import ROLE_PROMPTS, UnknownRoleError
from .tools import NoteSearchTool, ReadFileTool, ShellTool, ToolRegistry, WriteFileTool


def _note_manager() -> NoteManager:
    override = os.getenv("SMARTCLI_NOTES_PATH")
    return NoteManager(Path(override) if override else None)


def _config_manager() -> ConfigManager:
    override = os.getenv("SMARTCLI_CONFIG_PATH")
    return ConfigManager(Path(override) if override else None)


def _agent_tools() -> ToolRegistry:
    return ToolRegistry(
        [ShellTool(), ReadFileTool(), WriteFileTool(), NoteSearchTool(_note_manager())]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartcli",
        description="A local-first terminal AI assistant for developer workflows.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    ask_parser = commands.add_parser("ask", help="Analyze a question or piped text")
    ask_parser.add_argument("question", nargs="?", help="Question or instruction")
    ask_parser.add_argument("--role", "-r", choices=ROLE_PROMPTS)
    ask_parser.add_argument("--model", "-m", choices=AVAILABLE_MODELS)
    ask_parser.add_argument("--save", action="store_true", help="Save the result as an AI note")
    ask_parser.add_argument("--tag", action="append", default=[], help="Tag for the saved note")
    ask_parser.add_argument("--chat", action="store_true", help=argparse.SUPPRESS)
    ask_parser.set_defaults(handler=_handle_ask)

    chat_parser = commands.add_parser("chat", help="Start a multi-turn AI conversation")
    chat_parser.add_argument("--role", "-r", choices=ROLE_PROMPTS)
    chat_parser.add_argument("--model", "-m", choices=AVAILABLE_MODELS)
    chat_parser.set_defaults(handler=_handle_chat)

    agent_parser = commands.add_parser("agent", help="Run a bounded ReAct agent task")
    agent_parser.add_argument("task", nargs="?", help="Task or instruction")
    agent_parser.add_argument("--model", "-m", choices=AVAILABLE_MODELS)
    agent_parser.add_argument("--max-steps", type=int, default=12)
    agent_parser.add_argument("--workspace", default=".")
    agent_parser.add_argument("--verbose", "-v", action="store_true")
    agent_parser.add_argument(
        "--approve-risky",
        action="store_true",
        help="Pre-approve shell actions classified as high risk",
    )
    agent_parser.set_defaults(handler=_handle_agent)

    note_parser = commands.add_parser("note", help="Manage local knowledge notes")
    note_commands = note_parser.add_subparsers(dest="note_action", required=True)
    note_add = note_commands.add_parser("add", help="Add a manual note")
    note_add.add_argument("content")
    note_add.add_argument("--tag", action="append", default=[])
    note_add.set_defaults(handler=_handle_note_add)
    note_list = note_commands.add_parser("list", help="List notes")
    note_list.set_defaults(handler=_handle_note_list)
    note_show = note_commands.add_parser("show", help="Show a complete note")
    note_show.add_argument("id")
    note_show.set_defaults(handler=_handle_note_show)
    note_search = note_commands.add_parser("search", help="Search notes")
    note_search.add_argument("keyword")
    note_search.set_defaults(handler=_handle_note_search)
    note_delete = note_commands.add_parser("delete", help="Delete a note")
    note_delete.add_argument("id")
    note_delete.set_defaults(handler=_handle_note_delete)

    config_parser = commands.add_parser("config", help="Manage non-secret defaults")
    config_commands = config_parser.add_subparsers(dest="config_action", required=True)
    config_show = config_commands.add_parser("show", help="Show configuration")
    config_show.set_defaults(handler=_handle_config_show)
    config_set = config_commands.add_parser("set", help="Set a configuration value")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_set.set_defaults(handler=_handle_config_set)
    return parser


def _resolved_ai_options(args: argparse.Namespace) -> tuple[str, str]:
    config = _config_manager().load()
    return args.role or config["default_role"], args.model or config["default_model"]


def _handle_ask(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
    role, model = _resolved_ai_options(args)
    if args.chat:
        print("Warning: ask --chat is deprecated; use smartcli chat.", file=stderr)
        chat(role, model, stdin, stdout, stderr)
        return
    piped = read_piped_input(stdin)
    user_message = combine_input(args.question, piped)
    answer = ask_once(user_message, role, model)
    print(answer, file=stdout)
    if getattr(answer, "truncated", False):
        print(TRUNCATION_WARNING, file=stderr)
    if args.save:
        input_summary = piped[:500] + ("..." if len(piped) > 500 else "")
        content = (
            f"Question:\n{(args.question or '').strip() or '(stdin only)'}\n\n"
            f"Input summary:\n{input_summary or '(none)'}\n\nAnswer:\n{answer}"
        )
        note = _note_manager().add(
            content,
            args.tag,
            title=(args.question or "AI analysis").strip(),
            source="ai",
            model=model,
            role=role,
        )
        print(f"Saved note [{note.id}]", file=stderr)


def _handle_chat(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
    role, model = _resolved_ai_options(args)
    chat(role, model, stdin, stdout, stderr)


def _handle_agent(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
    if not 1 <= args.max_steps <= 100:
        raise InputError("--max-steps must be between 1 and 100")
    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        raise InputError(f"Workspace is not a directory: {workspace}")
    piped = read_piped_input(stdin)
    task = combine_input(args.task, piped)
    config = _config_manager().load()
    model = args.model or config["default_model"]

    def confirm(tool: str, arguments: dict[str, Any], reason: str) -> bool:
        if args.approve_risky:
            return True
        print(f"High-risk action requested by {tool}: {reason}", file=stderr)
        print(json.dumps(arguments, ensure_ascii=False, indent=2), file=stderr)
        if not getattr(stdin, "isatty", lambda: False)():
            print("Denied: confirmation requires an interactive terminal.", file=stderr)
            return False
        print("Approve this action? [y/N]: ", end="", flush=True, file=stderr)
        return stdin.readline().strip().casefold() in {"y", "yes"}

    def on_event(kind: str, content: str) -> None:
        if args.verbose and kind != "final":
            print(f"{kind.title()}: {content}", file=stderr)

    agent = ReActAgent(
        LLMService(model),
        _agent_tools(),
        workspace=workspace,
        confirm=confirm,
        on_event=on_event,
        max_steps=args.max_steps,
    )
    result = agent.run(task)
    if not result.success:
        raise AgentError(result.final)
    print(result.final, file=stdout)


def _handle_note_add(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    note = _note_manager().add(args.content, args.tag)
    print(f"Added note [{note.id}]", file=stdout)


def _print_note_summary(note: Any, stdout: TextIO) -> None:
    tags = f" [{', '.join(note.tags)}]" if note.tags else ""
    print(f"{note.id}  {note.created_at[:10]}  {note.title}{tags}", file=stdout)


def _handle_note_list(
    _args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    for note in _note_manager().list_all():
        _print_note_summary(note, stdout)


def _handle_note_show(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    print(
        json.dumps(asdict(_note_manager().get(args.id)), ensure_ascii=False, indent=2), file=stdout
    )


def _handle_note_search(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    for note in _note_manager().search(args.keyword):
        _print_note_summary(note, stdout)


def _handle_note_delete(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    _note_manager().delete(args.id)
    print(f"Deleted note [{args.id}]", file=stdout)


def _handle_config_show(
    _args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    print(json.dumps(_config_manager().load(), ensure_ascii=False, indent=2), file=stdout)


def _handle_config_set(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    config = _config_manager().set(args.key, args.value)
    print(f"{args.key}={config[args.key]}", file=stdout)


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        args.handler(args, input_stream, output_stream, error_stream)
    except (
        AgentError,
        ConfigurationError,
        InputError,
        LLMRequestError,
        NoteNotFoundError,
        NoteStorageError,
        UnknownRoleError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=error_stream)
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
