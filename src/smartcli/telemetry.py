"""Content-free operational telemetry for Agent runs."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class TelemetryCollector:
    """Aggregate counters and durations without accepting prompts or tool arguments."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        execution_backend: str = "local",
    ) -> None:
        self.clock = clock
        self.started = clock()
        self.finished: float | None = None
        self.execution_backend = execution_backend
        self.model_calls = 0
        self.model_attempts = 0
        self.model_duration_ms = 0
        self.usage_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.tool_calls = 0
        self.tool_failures = 0
        self.tool_duration_ms = 0
        self.output_truncations = 0
        self.tools_by_name: dict[str, dict[str, Any]] = {}
        self.protocol_errors = 0
        self.approval_denials = 0
        self.context_trims = 0

    def record_model(
        self, duration_ms: int, *, attempts: int = 1, usage: TokenUsage | None = None
    ) -> None:
        self.model_calls += 1
        self.model_attempts += max(1, attempts)
        self.model_duration_ms += max(0, duration_ms)
        if usage is not None:
            self.usage_calls += 1
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            self.total_tokens += usage.total_tokens

    def record_tool(
        self,
        name: str,
        duration_ms: int,
        *,
        success: bool,
        output_truncated: bool,
        backend: str | None = None,
    ) -> None:
        duration = max(0, duration_ms)
        self.tool_calls += 1
        self.tool_duration_ms += duration
        self.tool_failures += not success
        self.output_truncations += output_truncated
        item = self.tools_by_name.setdefault(
            name, {"calls": 0, "failures": 0, "duration_ms": 0, "backend": None}
        )
        item["calls"] += 1
        item["failures"] += not success
        item["duration_ms"] += duration
        if backend is not None:
            item["backend"] = backend

    def record_protocol_error(self) -> None:
        self.protocol_errors += 1

    def record_denial(self) -> None:
        self.approval_denials += 1

    def record_context_trim(self) -> None:
        self.context_trims += 1

    def finish(self) -> None:
        if self.finished is None:
            self.finished = self.clock()

    def to_dict(self) -> dict[str, Any]:
        duration = 0 if self.finished is None else _elapsed_ms(self.started, self.finished)
        has_usage = self.usage_calls > 0
        return {
            "duration_ms": duration,
            "execution_backend": self.execution_backend,
            "model": {
                "calls": self.model_calls,
                "attempts": self.model_attempts,
                "retries": max(0, self.model_attempts - self.model_calls),
                "duration_ms": self.model_duration_ms,
                "prompt_tokens": self.prompt_tokens if has_usage else None,
                "completion_tokens": self.completion_tokens if has_usage else None,
                "total_tokens": self.total_tokens if has_usage else None,
                "usage_complete": self.usage_calls == self.model_calls and self.model_calls > 0,
            },
            "tools": {
                "calls": self.tool_calls,
                "failures": self.tool_failures,
                "duration_ms": self.tool_duration_ms,
                "output_truncations": self.output_truncations,
                "by_name": self.tools_by_name,
            },
            "protocol_errors": self.protocol_errors,
            "approval_denials": self.approval_denials,
            "context_trims": self.context_trims,
        }


def _elapsed_ms(started: float, ended: float) -> int:
    return max(0, round((ended - started) * 1000))
