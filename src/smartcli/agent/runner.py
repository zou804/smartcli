"""Bounded ReAct execution loop."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..memory import LongTermMemory, NullLongTermMemory, ShortTermMemory
from ..output_style import normalize_terminal_markdown
from ..policy import WorkspacePolicy
from ..services.llm import LLMRequestError
from ..telemetry import TelemetryCollector, TokenUsage
from ..tools import RiskLevel, ToolContext, ToolRegistry, ToolResult
from .prompts import build_system_prompt
from .protocol import AgentDecision, ProtocolError, parse_decision


class AgentError(RuntimeError):
    """Raised when the bounded agent loop cannot safely continue."""


@dataclass(frozen=True)
class AgentResult:
    success: bool
    final: str
    steps: int
    plan: tuple[str, ...] = ()


ConfirmCallback = Callable[[str, dict[str, Any], str], bool]
EventCallback = Callable[[str, str], None]
AuditCallback = Callable[[dict[str, Any]], None]
BeforeActionCallback = Callable[[str, dict[str, Any], ToolContext], Any]
AfterActionCallback = Callable[[str, dict[str, Any], ToolResult, Any], None]
VerificationProvider = Callable[[], dict[str, Any]]


class ReActAgent:
    def __init__(
        self,
        llm: Any,
        tools: ToolRegistry,
        *,
        workspace: Path,
        workspace_policy: WorkspacePolicy | None = None,
        memory: ShortTermMemory | None = None,
        long_term_memory: LongTermMemory | None = None,
        confirm: ConfirmCallback | None = None,
        on_event: EventCallback | None = None,
        audit: AuditCallback | None = None,
        dry_run: bool = False,
        max_steps: int = 12,
        max_consecutive_failures: int = 3,
        model_retries: int = 0,
        max_task_chars: int = 40_000,
        run_id: str | None = None,
        before_action: BeforeActionCallback | None = None,
        after_action: AfterActionCallback | None = None,
        telemetry: TelemetryCollector | None = None,
        clock: Callable[[], float] = time.monotonic,
        verification_provider: VerificationProvider | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.context = ToolContext(workspace.resolve(), workspace_policy)
        self.memory = memory or ShortTermMemory()
        self.long_term_memory = long_term_memory or NullLongTermMemory()
        self.confirm = confirm or (lambda tool, arguments, reason: False)
        self.on_event = on_event or (lambda kind, content: None)
        self.audit = audit or (lambda event: None)
        self.dry_run = dry_run
        self.max_steps = max_steps
        self.max_consecutive_failures = max_consecutive_failures
        self.model_retries = model_retries
        self.max_task_chars = max_task_chars
        self.run_id = run_id
        self.before_action = before_action or (lambda tool, arguments, context: None)
        self.after_action = after_action or (
            lambda tool, arguments, result, checkpoint: None
        )
        self.telemetry = telemetry
        self.clock = clock
        self.verification_provider = verification_provider

    def run(self, task: str) -> AgentResult:
        try:
            return self._run(task)
        finally:
            if self.telemetry is not None:
                self.telemetry.finish()

    def _run(self, task: str) -> AgentResult:
        task = task.strip()
        if not task:
            raise AgentError("Agent task cannot be empty")
        if len(task) > self.max_task_chars:
            raise AgentError(
                f"Agent task exceeds the {self.max_task_chars:,}-character context budget"
            )
        system_prompt = build_system_prompt(self.tools.specs())
        recalled = self.long_term_memory.search(task, limit=5)
        if recalled:
            self.memory.add("long_term_memory", "\n".join(recalled))
        failures = 0
        plan: tuple[str, ...] = ()

        for step in range(1, self.max_steps + 1):
            decision = self._next_decision(system_prompt, task, step)
            if decision is None:
                failures += 1
                if failures >= self.max_consecutive_failures:
                    raise AgentError("Model repeatedly violated the agent JSON protocol")
                continue
            if decision.plan:
                plan = decision.plan
            if decision.thought:
                self.memory.add("thought", decision.thought)
                self.on_event("thought", decision.thought)
            if decision.final is not None:
                final = normalize_terminal_markdown(decision.final)
                self.on_event("final", final)
                return AgentResult(True, final, step, plan)
            assert decision.action is not None
            observation = self._execute_action(decision)
            self.memory.add("observation", observation)
            self.on_event("observation", observation)
            if observation.startswith("Tool status: success"):
                failures = 0
            else:
                failures += 1
                if failures >= self.max_consecutive_failures:
                    raise AgentError("Agent stopped after repeated action failures")

        return AgentResult(
            False, f"Agent reached the {self.max_steps}-step limit", self.max_steps, plan
        )

    def _next_decision(
        self, system_prompt: str, task: str, step: int
    ) -> AgentDecision | None:
        remaining = self.max_steps - step + 1
        final_instruction = (
            "This is the final step. Return `final` now using the available evidence; do not call "
            "another tool. Clearly state any uncertainty.\n"
            if remaining == 1
            else ""
        )
        verification_instruction = ""
        if remaining == 1 and self.verification_provider is not None:
            try:
                evidence = self.verification_provider()
            except Exception as exc:
                evidence = {"status": "unavailable", "error_type": type(exc).__name__}
            verification_instruction = (
                "Machine-generated verification evidence follows. Do not claim verification "
                "beyond this evidence.\n"
                f"<verification>{json.dumps(evidence, ensure_ascii=False)}</verification>\n"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Current bounded ReAct state follows. Continue from the latest event.\n"
                    f"Original task: {task}\n"
                    f"Task SHA-256: {hashlib.sha256(task.encode('utf-8')).hexdigest()}\n"
                    f"Step {step} of {self.max_steps}; {remaining} step(s) remain.\n"
                    f"{final_instruction}"
                    f"{verification_instruction}"
                    f"Runtime platform: {platform.system()}; workspace: {self.context.workspace}\n"
                    "<react_state>\n"
                    f"{self.memory.render()}\n"
                    "</react_state>"
                ),
            },
        ]
        response = None
        for attempt in range(self.model_retries + 1):
            started = self.clock()
            try:
                response = self.llm.request(messages)
                if self.telemetry is not None:
                    reported_duration = getattr(response, "duration_ms", None)
                    duration = (
                        reported_duration
                        if isinstance(reported_duration, int)
                        else max(0, round((self.clock() - started) * 1000))
                    )
                    usage = getattr(response, "usage", None)
                    self.telemetry.record_model(
                        duration,
                        attempts=int(getattr(response, "attempts", 1)),
                        usage=usage if isinstance(usage, TokenUsage) else None,
                    )
                break
            except LLMRequestError:
                if self.telemetry is not None:
                    elapsed = max(0, round((self.clock() - started) * 1000))
                    self.telemetry.record_model(elapsed)
                if attempt >= self.model_retries:
                    raise
        assert response is not None
        try:
            return parse_decision(str(response))
        except ProtocolError as exc:
            if self.telemetry is not None:
                self.telemetry.record_protocol_error()
            observation = f"Protocol error: {exc}. Return one valid JSON object."
            self.memory.add("observation", observation)
            self.on_event("observation", observation)
            return None

    def _execute_action(self, decision: AgentDecision) -> str:
        assert decision.action is not None
        action = decision.action
        try:
            tool = self.tools.get(action.tool)
            tool.validate(action.arguments)
            risk, reason = tool.assess_risk(action.arguments)
            event_arguments = dict(action.arguments)
            if isinstance(event_arguments.get("content"), str):
                event_arguments["content"] = f"<{len(event_arguments['content'])} chars>"
            self.on_event("action", f"{action.tool} {event_arguments}")
            if risk is RiskLevel.BLOCKED:
                self._audit_action(action.tool, action.arguments, risk, reason, False, False, False)
                return ToolResult(False, f"Action blocked by safety policy: {reason}").observation()
            if self.dry_run and tool.has_side_effects:
                self._audit_action(action.tool, action.arguments, risk, reason, False, False, True)
                return ToolResult(
                    True, f"Dry run: would execute {action.tool} with risk={risk.value}"
                ).observation()
            if risk in {RiskLevel.REVIEW, RiskLevel.HIGH} and not self.confirm(
                action.tool, action.arguments, reason
            ):
                if self.telemetry is not None:
                    self.telemetry.record_denial()
                self._audit_action(action.tool, action.arguments, risk, reason, False, False, False)
                return ToolResult(
                    False, f"User denied {risk.value}-risk action: {reason}"
                ).observation()
            self._audit_action(action.tool, action.arguments, risk, reason, True, False, False)
            checkpoint = self.before_action(action.tool, action.arguments, self.context)
            started = self.clock()
            result = tool.execute(action.arguments, self.context)
            elapsed = max(0, round((self.clock() - started) * 1000))
            if self.telemetry is not None:
                backend = result.metadata.get("backend")
                self.telemetry.record_tool(
                    action.tool,
                    elapsed,
                    success=result.success,
                    output_truncated=len(result.output) > 12_000,
                    backend=backend if isinstance(backend, str) else None,
                )
            observation = result.observation()
            try:
                self.after_action(action.tool, action.arguments, result, checkpoint)
            except Exception as exc:
                observation = (
                    f"{observation}\nRun report warning: action completed but checkpoint update "
                    f"failed: {exc}"
                )
            try:
                self._audit_action(
                    action.tool, action.arguments, risk, reason, True, True, False, result.success
                )
            except Exception as exc:
                observation = (
                    f"{observation}\nAudit warning: action completed but result audit failed: {exc}"
                )
            return observation
        except Exception as exc:
            return ToolResult(False, f"Tool invocation error: {exc}").observation()

    def _audit_action(
        self,
        tool: str,
        arguments: dict[str, Any],
        risk: RiskLevel,
        reason: str,
        approved: bool,
        executed: bool,
        dry_run: bool,
        success: bool | None = None,
    ) -> None:
        self.audit(
            {
                "tool": tool,
                "arguments": arguments,
                "risk": risk.value,
                "reason": reason,
                "approved": approved,
                "executed": executed,
                "dry_run": dry_run,
                "success": success,
                "run_id": self.run_id,
            }
        )
