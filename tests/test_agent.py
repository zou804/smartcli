from __future__ import annotations

import json

import pytest

from smartcli.agent import AgentError, ReActAgent, parse_decision
from smartcli.agent.protocol import ProtocolError
from smartcli.memory import ShortTermMemory
from smartcli.tools import RiskLevel, Tool, ToolContext, ToolRegistry, ToolResult


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def request(self, messages):
        self.requests.append(messages)
        return next(self.responses)


class EchoTool(Tool):
    name = "echo"
    description = "Echo text"
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, arguments, context: ToolContext):
        self.validate(arguments)
        return ToolResult(True, str(arguments["text"]), {"workspace": str(context.workspace)})


class HighRiskTool(EchoTool):
    name = "danger"
    risk_level = RiskLevel.HIGH


def decision(**value):
    return json.dumps(value)


def test_protocol_accepts_action_and_rejects_ambiguous_output():
    parsed = parse_decision(
        decision(thought="inspect", plan=["one"], action={"tool": "echo", "arguments": {}})
    )
    assert parsed.action and parsed.action.tool == "echo" and parsed.plan == ("one",)
    with pytest.raises(ProtocolError, match="exactly one"):
        parse_decision(decision(thought="bad", action=None, final=None))


def test_react_agent_closes_action_observation_final_loop(tmp_path):
    llm = FakeLLM(
        [
            decision(
                thought="use tool",
                plan=["echo", "finish"],
                action={"tool": "echo", "arguments": {"text": "observed"}},
            ),
            decision(thought="done", final="complete"),
        ]
    )
    events = []
    agent = ReActAgent(
        llm,
        ToolRegistry([EchoTool()]),
        workspace=tmp_path,
        on_event=lambda kind, content: events.append((kind, content)),
    )
    result = agent.run("test task")
    assert result.success and result.final == "complete" and result.steps == 2
    assert "observed" in llm.requests[1][1]["content"]
    assert [kind for kind, _ in events] == ["thought", "action", "observation", "thought", "final"]


def test_high_risk_action_requires_confirmation(tmp_path):
    llm = FakeLLM(
        [
            decision(
                thought="try",
                action={"tool": "danger", "arguments": {"text": "do it"}},
            ),
            decision(thought="denied", final="not executed"),
        ]
    )
    agent = ReActAgent(
        llm,
        ToolRegistry([HighRiskTool()]),
        workspace=tmp_path,
        confirm=lambda tool, arguments, reason: False,
    )
    assert agent.run("dangerous task").final == "not executed"
    assert "User denied" in llm.requests[1][1]["content"]


def test_agent_stops_after_repeated_protocol_failures(tmp_path):
    agent = ReActAgent(
        FakeLLM(["bad", "still bad", "bad again"]),
        ToolRegistry([EchoTool()]),
        workspace=tmp_path,
    )
    with pytest.raises(AgentError, match="JSON protocol"):
        agent.run("task")


def test_short_term_memory_uses_a_sliding_window():
    memory = ShortTermMemory(max_events=2, max_chars=40)
    memory.add("first", "a" * 20)
    memory.add("second", "b" * 20)
    memory.add("third", "latest")
    assert len(memory.events()) <= 2
    assert memory.events()[-1].content == "latest"
    assert len(memory.render()) <= 40
