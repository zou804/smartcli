from __future__ import annotations

import io

from smartcli.commands.ask import chat
from smartcli.services.llm import LLMRequestError, ResponseText


class FakeService:
    def __init__(self):
        self.requests = []

    def request(self, messages):
        self.requests.append([dict(message) for message in messages])
        return f"answer-{len(self.requests)}"


def test_chat_preserves_multiturn_history_and_skips_empty_input():
    service = FakeService()
    stdout, stderr = io.StringIO(), io.StringIO()
    chat(
        "debug",
        "deepseek",
        io.StringIO("first\n\nsecond\nq\n"),
        stdout,
        stderr,
        service_factory=lambda model: service,
    )
    assert len(service.requests) == 2
    assert [message["role"] for message in service.requests[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert service.requests[1][1]["content"] == "first"
    assert "answer-1\nanswer-2" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_chat_continues_after_request_error():
    class FlakyService:
        calls = 0

        def request(self, messages):
            self.calls += 1
            if self.calls == 1:
                raise LLMRequestError("offline")
            return "recovered"

    service = FlakyService()
    stdout, stderr = io.StringIO(), io.StringIO()
    chat(
        "default",
        "deepseek",
        io.StringIO("fail\nretry\nq\n"),
        stdout,
        stderr,
        service_factory=lambda model: service,
    )
    assert "recovered" in stdout.getvalue()
    assert "offline" in stderr.getvalue()


def test_chat_handles_keyboard_interrupt_cleanly():
    class InterruptingInput:
        def isatty(self):
            return True

        def readline(self):
            raise KeyboardInterrupt

    stdout, stderr = io.StringIO(), io.StringIO()
    chat(
        "default",
        "deepseek",
        InterruptingInput(),
        stdout,
        stderr,
        service_factory=lambda model: FakeService(),
    )
    assert "Chat ended." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_chat_normalizes_output_and_history_while_preserving_metadata():
    class MarkdownService:
        def __init__(self):
            self.requests = []

        def request(self, messages):
            self.requests.append([dict(message) for message in messages])
            return ResponseText("# Result\n\n```text\nvalue\n```", truncated=True, attempts=2)

    service = MarkdownService()
    stdout, stderr = io.StringIO(), io.StringIO()
    chat(
        "default",
        "deepseek",
        io.StringIO("first\nsecond\nq\n"),
        stdout,
        stderr,
        service_factory=lambda model: service,
    )
    assert "### Result\n\nvalue" in stdout.getvalue()
    assert service.requests[1][2]["content"] == "### Result\n\nvalue"
    assert stderr.getvalue().count("output limit") == 2
