"""SmartCLI command-line interface."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .agent import AgentError, ReActAgent
from .audit import AuditLogError, AuditLogger, summarize_arguments
from .commands.ask import (
    TRUNCATION_WARNING,
    InputError,
    ask_once,
    chat,
    combine_input,
    read_piped_input,
)
from .commands.note import NoteManager, NoteNotFoundError, NoteStorageError
from .config import BUILTIN_PROFILES, ConfigManager, ConfigurationError, ModelProfile
from .doctor import run_doctor
from .rendering import render_markdown
from .runs import RunStorageError, RunStore
from .services.llm import LLMRequestError, LLMService
from .services.prompts import ROLE_PROMPTS, UnknownRoleError
from .tools import (
    ApplyPatchTool,
    GitTool,
    ListFilesTool,
    NoteSearchTool,
    ProjectCheckTool,
    ReadFileTool,
    ToolRegistry,
    WriteFileTool,
)


def _note_manager() -> NoteManager:
    override = os.getenv("SMARTCLI_NOTES_PATH")
    return NoteManager(Path(override) if override else None)


def _config_manager() -> ConfigManager:
    override = os.getenv("SMARTCLI_CONFIG_PATH")
    return ConfigManager(Path(override) if override else None)


def _agent_tools(allowed: set[str] | None = None) -> ToolRegistry:
    capabilities = allowed or set()
    tools = [ListFilesTool(), ReadFileTool(), NoteSearchTool(_note_manager())]
    if "write" in capabilities:
        tools.extend((WriteFileTool(), ApplyPatchTool()))
    if "git" in capabilities:
        tools.append(GitTool())
    if "check" in capabilities:
        tools.append(ProjectCheckTool())
    return ToolRegistry(tools)


def _audit_logger() -> AuditLogger:
    override = os.getenv("SMARTCLI_AUDIT_PATH")
    return AuditLogger(Path(override) if override else None)


def _run_store() -> RunStore:
    override = os.getenv("SMARTCLI_RUNS_PATH")
    return RunStore(Path(override) if override else None)


def _add_json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="Emit stable JSON output"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartcli",
        description="A local-first terminal AI assistant for developer workflows.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--json", action="store_true", help="Emit stable JSON output")
    commands = parser.add_subparsers(dest="command", required=True)

    ask_parser = commands.add_parser("ask", help="Analyze a question or piped text")
    ask_parser.add_argument("question", nargs="?", help="Question or instruction")
    ask_parser.add_argument("--role", "-r", choices=ROLE_PROMPTS)
    ask_parser.add_argument("--model", "-m")
    ask_parser.add_argument("--save", action="store_true", help="Save the result as an AI note")
    ask_parser.add_argument("--tag", action="append", default=[], help="Tag for the saved note")
    ask_parser.add_argument("--chat", action="store_true", help=argparse.SUPPRESS)
    _add_json_option(ask_parser)
    ask_parser.set_defaults(handler=_handle_ask)

    chat_parser = commands.add_parser("chat", help="Start a multi-turn AI conversation")
    chat_parser.add_argument("--role", "-r", choices=ROLE_PROMPTS)
    chat_parser.add_argument("--model", "-m")
    _add_json_option(chat_parser)
    chat_parser.set_defaults(handler=_handle_chat)

    agent_parser = commands.add_parser("agent", help="Run a bounded ReAct agent task")
    agent_parser.add_argument("task", nargs="?", help="Task or instruction")
    agent_parser.add_argument("--model", "-m")
    agent_parser.add_argument("--max-steps", type=int, default=12)
    agent_parser.add_argument("--workspace", default=".")
    agent_parser.add_argument("--verbose", "-v", action="store_true")
    agent_parser.add_argument(
        "--allow",
        action="append",
        choices=("write", "git", "check"),
        default=[],
        help="Enable an Agent capability; repeat for multiple capabilities",
    )
    _add_json_option(agent_parser)
    agent_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and plan while skipping side-effecting tools",
    )
    agent_parser.add_argument(
        "--approve-risky",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    agent_parser.set_defaults(handler=_handle_agent)

    note_parser = commands.add_parser("note", help="Manage local knowledge notes")
    note_commands = note_parser.add_subparsers(dest="note_action", required=True)
    note_add = note_commands.add_parser("add", help="Add a manual note")
    note_add.add_argument("content")
    note_add.add_argument("--tag", action="append", default=[])
    _add_json_option(note_add)
    note_add.set_defaults(handler=_handle_note_add)
    note_list = note_commands.add_parser("list", help="List notes")
    _add_json_option(note_list)
    note_list.set_defaults(handler=_handle_note_list)
    note_show = note_commands.add_parser("show", help="Show a complete note")
    note_show.add_argument("id")
    _add_json_option(note_show)
    note_show.set_defaults(handler=_handle_note_show)
    note_search = note_commands.add_parser("search", help="Search notes")
    note_search.add_argument("keyword")
    _add_json_option(note_search)
    note_search.set_defaults(handler=_handle_note_search)
    note_delete = note_commands.add_parser("delete", help="Delete a note")
    note_delete.add_argument("id")
    _add_json_option(note_delete)
    note_delete.set_defaults(handler=_handle_note_delete)

    config_parser = commands.add_parser("config", help="Manage non-secret defaults")
    config_commands = config_parser.add_subparsers(dest="config_action", required=True)
    config_show = config_commands.add_parser("show", help="Show configuration")
    _add_json_option(config_show)
    config_show.set_defaults(handler=_handle_config_show)
    config_set = config_commands.add_parser("set", help="Set a configuration value")
    config_set.add_argument("key")
    config_set.add_argument("value")
    _add_json_option(config_set)
    config_set.set_defaults(handler=_handle_config_set)

    model_parser = commands.add_parser("model", help="Manage non-secret model profiles")
    model_commands = model_parser.add_subparsers(dest="model_action", required=True)
    model_list = model_commands.add_parser("list", help="List model profiles")
    _add_json_option(model_list)
    model_list.set_defaults(handler=_handle_model_list)
    model_show = model_commands.add_parser("show", help="Show a model profile")
    model_show.add_argument("name")
    _add_json_option(model_show)
    model_show.set_defaults(handler=_handle_model_show)
    model_add = model_commands.add_parser("add", help="Add a custom model profile")
    model_add.add_argument("name")
    model_add.add_argument("--provider", choices=("openai_compatible", "ollama"), required=True)
    model_add.add_argument("--model-id", required=True)
    model_add.add_argument("--base-url", required=True)
    model_add.add_argument("--api-key-env")
    model_add.add_argument("--max-tokens", type=int, default=2048)
    model_add.add_argument("--temperature", type=float, default=0.7)
    model_add.add_argument("--timeout", type=float, default=60.0)
    model_add.add_argument("--connect-timeout", type=float, default=10.0)
    model_add.add_argument("--retries", type=int, default=2)
    model_add.add_argument("--replace", action="store_true")
    _add_json_option(model_add)
    model_add.set_defaults(handler=_handle_model_add)
    model_remove = model_commands.add_parser("remove", help="Remove a custom model profile")
    model_remove.add_argument("name")
    _add_json_option(model_remove)
    model_remove.set_defaults(handler=_handle_model_remove)

    doctor_parser = commands.add_parser("doctor", help="Check installation and model readiness")
    doctor_parser.add_argument("--model")
    doctor_parser.add_argument(
        "--connect", action="store_true", help="Send a minimal request to the selected model"
    )
    _add_json_option(doctor_parser)
    doctor_parser.set_defaults(handler=_handle_doctor)

    run_parser = commands.add_parser("run", help="Inspect and undo Agent runs")
    run_commands = run_parser.add_subparsers(dest="run_action", required=True)
    run_list = run_commands.add_parser("list", help="List Agent runs")
    _add_json_option(run_list)
    run_list.set_defaults(handler=_handle_run_list)
    run_show = run_commands.add_parser("show", help="Show a redacted Agent run report")
    run_show.add_argument("id")
    _add_json_option(run_show)
    run_show.set_defaults(handler=_handle_run_show)
    run_undo = run_commands.add_parser("undo", help="Undo unchanged files from an Agent run")
    run_undo.add_argument("id")
    _add_json_option(run_undo)
    run_undo.set_defaults(handler=_handle_run_undo)
    return parser


def _resolved_ai_options(args: argparse.Namespace) -> tuple[str, str]:
    config = _config_manager().load()
    return args.role or config["default_role"], args.model or config["default_model"]


def _command_name(args: argparse.Namespace) -> str:
    action = getattr(args, f"{args.command}_action", None)
    return f"{args.command}.{action}" if action else args.command


def _emit_json(args: argparse.Namespace, stdout: TextIO, data: Any) -> bool:
    if not getattr(args, "json", False):
        return False
    print(
        json.dumps(
            {"ok": True, "command": _command_name(args), "data": data},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        file=stdout,
    )
    return True


def _handle_ask(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
    role, model = _resolved_ai_options(args)
    if args.chat:
        if args.json:
            raise InputError("JSON output is not supported by deprecated ask --chat")
        print("Warning: ask --chat is deprecated; use smartcli chat.", file=stderr)
        chat(role, model, stdin, stdout, stderr)
        return
    piped = read_piped_input(stdin)
    user_message = combine_input(args.question, piped)
    answer = ask_once(user_message, role, model)
    saved_note = None
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
        saved_note = note.id
    truncated = bool(getattr(answer, "truncated", False))
    if not _emit_json(
        args,
        stdout,
        {
            "answer": str(answer),
            "model": model,
            "role": role,
            "truncated": truncated,
            "attempts": int(getattr(answer, "attempts", 1)),
            "saved_note_id": saved_note,
        },
    ):
        render_markdown(answer, stdout)
        if truncated:
            print(TRUNCATION_WARNING, file=stderr)
        if saved_note:
            print(f"Saved note [{saved_note}]", file=stderr)


def _handle_chat(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
    if args.json:
        raise InputError("JSON output is not supported for interactive chat")
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
    allowed = set(args.allow)
    config = _config_manager().load()
    model = args.model or config["default_model"]

    def confirm(tool: str, arguments: dict[str, Any], reason: str) -> bool:
        print(f"Action requires confirmation ({tool}): {reason}", file=stderr)
        display_arguments = dict(arguments)
        content = display_arguments.pop("content", None)
        if isinstance(content, str):
            display_arguments["content_chars"] = len(content)
            display_arguments["content_sha256"] = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            display_arguments["content_preview"] = content[:2_000]
        print(json.dumps(display_arguments, ensure_ascii=False, indent=2), file=stderr)
        if not getattr(stdin, "isatty", lambda: False)():
            print("Denied: confirmation requires an interactive terminal.", file=stderr)
            return False
        print("Approve this action? [y/N]: ", end="", flush=True, file=stderr)
        return stdin.readline().strip().casefold() in {"y", "yes"}

    def on_event(kind: str, content: str) -> None:
        if (args.verbose or args.dry_run) and kind not in {"thought", "final"}:
            print(f"{kind.title()}: {content}", file=stderr)

    service = LLMService(model)
    logger = _audit_logger()
    journal = _run_store().start(workspace, task)

    def audit(event: dict[str, Any]) -> None:
        logger.record({**event, "arguments": summarize_arguments(event["arguments"])})

    agent = ReActAgent(
        service,
        _agent_tools(allowed),
        workspace=workspace,
        confirm=confirm,
        on_event=on_event,
        audit=audit,
        dry_run=args.dry_run,
        max_steps=args.max_steps,
        run_id=journal.run_id,
        before_action=journal.prepare_action,
        after_action=journal.record_action,
    )
    try:
        result = agent.run(task)
    except Exception as exc:
        try:
            journal.fail(str(exc))
        except RunStorageError:
            pass
        raise
    if not result.success:
        journal.fail(result.final)
        raise AgentError(result.final)
    journal.complete(final=result.final, steps=result.steps, plan=result.plan)
    if not _emit_json(
        args,
        stdout,
        {
            "final": result.final,
            "model": model,
            "steps": result.steps,
            "plan": list(result.plan),
            "run_id": journal.run_id,
        },
    ):
        render_markdown(result.final, stdout)
        print(f"Run ID: {journal.run_id}", file=stderr)


def _handle_note_add(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    note = _note_manager().add(args.content, args.tag)
    if not _emit_json(args, stdout, asdict(note)):
        print(f"Added note [{note.id}]", file=stdout)


def _print_note_summary(note: Any, stdout: TextIO) -> None:
    tags = f" [{', '.join(note.tags)}]" if note.tags else ""
    print(f"{note.id}  {note.created_at[:10]}  {note.title}{tags}", file=stdout)


def _handle_note_list(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    notes = _note_manager().list_all()
    if _emit_json(args, stdout, [asdict(note) for note in notes]):
        return
    for note in notes:
        _print_note_summary(note, stdout)


def _handle_note_show(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    note = asdict(_note_manager().get(args.id))
    if not _emit_json(args, stdout, note):
        print(json.dumps(note, ensure_ascii=False, indent=2), file=stdout)


def _handle_note_search(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    notes = _note_manager().search(args.keyword)
    if _emit_json(args, stdout, [asdict(note) for note in notes]):
        return
    for note in notes:
        _print_note_summary(note, stdout)


def _handle_note_delete(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    _note_manager().delete(args.id)
    if not _emit_json(args, stdout, {"id": args.id, "deleted": True}):
        print(f"Deleted note [{args.id}]", file=stdout)


def _handle_config_show(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    config = _config_manager().load()
    if not _emit_json(args, stdout, config):
        print(json.dumps(config, ensure_ascii=False, indent=2), file=stdout)


def _handle_config_set(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    config = _config_manager().set(args.key, args.value)
    if not _emit_json(args, stdout, config):
        print(f"{args.key}={config[args.key]}", file=stdout)


def _profile_data(name: str, profile: ModelProfile, *, builtin: bool) -> dict[str, Any]:
    return {"name": name, "builtin": builtin, **profile.to_dict()}


def _handle_model_list(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    manager = _config_manager()
    profiles = [
        _profile_data(name, profile, builtin=name in BUILTIN_PROFILES)
        for name, profile in sorted(manager.profiles().items())
    ]
    if not _emit_json(args, stdout, profiles):
        for profile in profiles:
            source = "builtin" if profile["builtin"] else "custom"
            print(
                f"{profile['name']}  {source}  {profile['provider']}  {profile['model_id']}",
                file=stdout,
            )


def _handle_model_show(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    manager = _config_manager()
    data = _profile_data(
        args.name, manager.get_profile(args.name), builtin=args.name in BUILTIN_PROFILES
    )
    if not _emit_json(args, stdout, data):
        print(json.dumps(data, ensure_ascii=False, indent=2), file=stdout)


def _handle_model_add(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    profile = ModelProfile(
        provider=args.provider,
        model_id=args.model_id,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        timeout_seconds=args.timeout,
        connect_timeout_seconds=args.connect_timeout,
        max_retries=args.retries,
    )
    manager = _config_manager()
    manager.add_profile(args.name, profile, replace=args.replace)
    data = _profile_data(args.name, profile, builtin=False)
    if not _emit_json(args, stdout, data):
        print(f"Added model profile {args.name}", file=stdout)


def _handle_model_remove(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    _config_manager().remove_profile(args.name)
    data = {"name": args.name, "removed": True}
    if not _emit_json(args, stdout, data):
        print(f"Removed model profile {args.name}", file=stdout)


def _handle_doctor(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    checks = run_doctor(_config_manager(), model_name=args.model, connect=args.connect)
    data = {
        "healthy": not any(check.status == "error" for check in checks),
        "checks": [check.to_dict() for check in checks],
    }
    if not _emit_json(args, stdout, data):
        for check in checks:
            print(f"[{check.status.upper():7}] {check.name}: {check.message}", file=stdout)
    if not data["healthy"]:
        args.exit_code = 1


def _handle_run_list(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    reports = _run_store().list()
    if _emit_json(args, stdout, reports):
        return
    for report in reports:
        print(
            f"{report['run_id']}  {report['status']}  "
            f"actions={report['actions']} changes={report['changes']}  "
            f"{report['task_preview']}",
            file=stdout,
        )


def _handle_run_show(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    report = _run_store().public_report(args.id)
    if not _emit_json(args, stdout, report):
        print(json.dumps(report, ensure_ascii=False, indent=2), file=stdout)


def _handle_run_undo(
    args: argparse.Namespace, _stdin: TextIO, stdout: TextIO, _stderr: TextIO
) -> None:
    result = _run_store().undo(args.id)
    if not _emit_json(args, stdout, result):
        print(
            f"Undid {args.id}: restored={len(result['restored'])}, "
            f"removed={len(result['removed'])}",
            file=stdout,
        )


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
        AuditLogError,
        ConfigurationError,
        InputError,
        LLMRequestError,
        NoteNotFoundError,
        NoteStorageError,
        RunStorageError,
        UnknownRoleError,
        ValueError,
    ) as exc:
        if getattr(args, "json", False):
            error_type = type(exc).__name__
            print(
                json.dumps(
                    {
                        "ok": False,
                        "command": _command_name(args),
                        "error": {"type": error_type, "message": str(exc)},
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                file=output_stream,
            )
        else:
            print(f"Error: {exc}", file=error_stream)
        return 1
    return int(getattr(args, "exit_code", 0))


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
