"""Single-turn and interactive AI workflows."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TextIO

from ..output_style import normalize_terminal_markdown
from ..rendering import render_markdown
from ..services.llm import LLMRequestError, LLMService, ResponseText
from ..services.prompts import get_role_prompt

MAX_STDIN_CHARS = 100_000
MAX_CHAT_MESSAGE_CHARS = 20_000
MAX_CHAT_CONTEXT_CHARS = 60_000
EXIT_WORDS = frozenset({"exit", "quit", "q"})
TRUNCATION_WARNING = "Warning: The model stopped at its output limit; the answer may be incomplete."


class InputError(ValueError):
    """Raised for missing or excessive command input."""


def read_piped_input(stream: TextIO, limit: int = MAX_STDIN_CHARS) -> str:
    """Read redirected input without blocking an interactive terminal."""
    if getattr(stream, "isatty", lambda: False)():
        return ""
    if os.name == "nt":
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    value = stream.read(limit + 1)
    if len(value) > limit:
        raise InputError(f"Standard input exceeds the {limit:,}-character limit")
    return _replace_surrogates(value).strip()


def _replace_surrogates(value: str) -> str:
    """Ensure provider JSON encoders only receive valid Unicode text."""
    return value.encode("utf-8", errors="replace").decode("utf-8")


def combine_input(question: str | None, piped_input: str) -> str:
    """Build an unambiguous user message from instruction and stdin."""
    clean_question = (question or "").strip()
    clean_input = piped_input.strip()
    if clean_question and clean_input:
        return f"User instruction:\n{clean_question}\n\nInput from stdin:\n{clean_input}"
    if clean_question:
        return clean_question
    if clean_input:
        return f"Input from stdin:\n{clean_input}"
    raise InputError("Provide a question or pipe text to standard input")


def ask_once(
    user_message: str,
    role: str,
    model: str,
    *,
    service_factory: Callable[[str], LLMService] = LLMService,
) -> str:
    messages = [
        {"role": "system", "content": get_role_prompt(role)},
        {"role": "user", "content": user_message},
    ]
    response = service_factory(model).request(messages)
    return _normalize_response(response)


def _normalize_response(response: str) -> str:
    normalized = normalize_terminal_markdown(response)
    if isinstance(response, ResponseText):
        return ResponseText(
            normalized,
            truncated=response.truncated,
            attempts=response.attempts,
        )
    return normalized


def chat(
    role: str,
    model: str,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    *,
    service_factory: Callable[[str], LLMService] = LLMService,
) -> None:
    service = service_factory(model)
    messages: list[dict[str, str]] = [{"role": "system", "content": get_role_prompt(role)}]
    interactive = getattr(stdin, "isatty", lambda: False)()
    if interactive:
        print("Chat started. Type exit, quit, or q to leave.", file=stdout)
    try:
        while True:
            if interactive:
                print("You: ", end="", flush=True, file=stdout)
            line = stdin.readline()
            if line == "":
                break
            user_input = line.strip()
            if user_input.casefold() in EXIT_WORDS:
                break
            if not user_input:
                continue
            if len(user_input) > MAX_CHAT_MESSAGE_CHARS:
                print(
                    f"Error: Chat message exceeds the {MAX_CHAT_MESSAGE_CHARS:,}-character limit",
                    file=stderr,
                )
                continue
            messages.append({"role": "user", "content": user_input})
            try:
                answer = _normalize_response(
                    service.request(_bounded_chat_messages(messages, MAX_CHAT_CONTEXT_CHARS))
                )
            except LLMRequestError as exc:
                messages.pop()
                print(f"Error: {exc}", file=stderr)
                continue
            messages.append({"role": "assistant", "content": answer})
            render_markdown(answer, stdout)
            if getattr(answer, "truncated", False):
                print(TRUNCATION_WARNING, file=stderr)
    except (EOFError, KeyboardInterrupt):
        if interactive:
            print(file=stdout)
    if interactive:
        print("Chat ended.", file=stdout)


def _bounded_chat_messages(
    messages: list[dict[str, str]], max_chars: int
) -> list[dict[str, str]]:
    """Keep the system prompt and the newest complete conversation turns."""
    bounded = [dict(message) for message in messages]
    omitted = False
    while len(bounded) > 2 and sum(len(item["content"]) for item in bounded) > max_chars:
        del bounded[1 : min(3, len(bounded) - 1)]
        omitted = True
    if omitted:
        bounded.insert(
            1,
            {
                "role": "system",
                "content": (
                    "Earlier conversation turns were omitted to stay within the context budget."
                ),
            },
        )
    return bounded
