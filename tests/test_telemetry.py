from __future__ import annotations

from smartcli.telemetry import TelemetryCollector, TokenUsage


def test_telemetry_aggregates_only_safe_operational_fields():
    ticks = iter((10.0, 10.25))
    collector = TelemetryCollector(clock=lambda: next(ticks), execution_backend="docker")
    collector.record_model(120, attempts=2, usage=TokenUsage(10, 5, 15))
    collector.record_model(80, attempts=1, usage=None)
    collector.record_tool(
        "run_check", 45, success=True, output_truncated=False, backend="docker"
    )
    collector.record_tool("read_file", 5, success=False, output_truncated=True)
    collector.record_protocol_error()
    collector.record_denial()
    collector.record_context_trim()
    collector.finish()

    value = collector.to_dict()
    assert value["duration_ms"] == 250
    assert value["execution_backend"] == "docker"
    assert value["model"] == {
        "calls": 2,
        "attempts": 3,
        "retries": 1,
        "duration_ms": 200,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "usage_complete": False,
    }
    assert value["tools"]["calls"] == 2
    assert value["tools"]["failures"] == 1
    assert value["tools"]["output_truncations"] == 1
    assert value["tools"]["by_name"]["run_check"]["backend"] == "docker"
    assert value["protocol_errors"] == 1 and value["approval_denials"] == 1
    assert value["context_trims"] == 1
    assert "secret" not in str(value).casefold()


def test_empty_telemetry_keeps_unknown_token_usage_null():
    ticks = iter((1.0, 1.0))
    collector = TelemetryCollector(clock=lambda: next(ticks))
    collector.finish()
    model = collector.to_dict()["model"]
    assert model["prompt_tokens"] is None
    assert model["completion_tokens"] is None
    assert model["total_tokens"] is None
