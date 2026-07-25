"""Bounded ReAct execution loop."""

from __future__ import annotations

import platform
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..memory import LongTermMemory, NullLongTermMemory, ShortTermMemory
from ..output_style import normalize_terminal_markdown
from ..services.llm import LLMRequestError
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


class ReActAgent:
    def __init__(
        self,
        llm: Any,
        tools: ToolRegistry,
        *,
        workspace: Path,
        memory: ShortTermMemory | None = None,
        long_term_memory: LongTermMemory | None = None,
        confirm: ConfirmCallback | None = None,
        on_event: EventCallback | None = None,
        audit: AuditCallback | None = None,
        dry_run: bool = False,
        max_steps: int = 12,
        max_consecutive_failures: int = 3,
        model_retries: int = 0,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.context = ToolContext(workspace.resolve())
        self.memory = memory or ShortTermMemory()
        self.long_term_memory = long_term_memory or NullLongTermMemory()
        self.confirm = confirm or (lambda tool, arguments, reason: False)
        self.on_event = on_event or (lambda kind, content: None)
        self.audit = audit or (lambda event: None)
        self.dry_run = dry_run
        self.max_steps = max_steps
        self.max_consecutive_failures = max_consecutive_failures
        self.model_retries = model_retries

    def run(self, task: str) -> AgentResult:
        task = task.strip()
        if not task:
            raise AgentError("Agent task cannot be empty")
        system_prompt = build_system_prompt(self.tools.specs())
        recalled = self.long_term_memory.search(task, limit=5)
        self.memory.add("task", task)
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
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Current bounded ReAct state follows. Continue from the latest event.\n"
                    f"Original task: {task}\n"
                    f"Step {step} of {self.max_steps}; {remaining} step(s) remain.\n"
                    f"{final_instruction}"
                    f"Runtime platform: {platform.system()}; workspace: {self.context.workspace}\n"
                    "<react_state>\n"
                    f"{self.memory.render()}\n"
                    "</react_state>"
                ),
            },
        ]
        response = None
        for attempt in range(self.model_retries + 1):
            try:
                response = self.llm.request(messages)
                break
            except LLMRequestError:
                if attempt >= self.model_retries:
                    raise
        assert response is not None
        try:
            return parse_decision(str(response))
        except ProtocolError as exc:
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
                self._audit_action(action.tool, action.arguments, risk, reason, False, False, False)
                return ToolResult(
                    False, f"User denied {risk.value}-risk action: {reason}"
                ).observation()
            self._audit_action(action.tool, action.arguments, risk, reason, True, False, False)
            result = tool.execute(action.arguments, self.context)
            self._audit_action(
                action.tool, action.arguments, risk, reason, True, True, False, result.success
            )
            return result.observation()
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
            }
        )
