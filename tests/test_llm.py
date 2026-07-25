from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from smartcli.config import ConfigManager, ConfigurationError, ModelProfile, get_model_config
from smartcli.services.llm import EmptyResponseError, LLMRequestError, LLMService


class Completions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def client_for(response=None, error=None):
    completions = Completions(response, error)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def test_missing_api_key_and_unknown_model():
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
        LLMService("deepseek", environ={})
    with pytest.raises(ConfigurationError, match="Unknown model"):
        get_model_config("missing")


def test_deepseek_alias_uses_current_flash_model():
    assert get_model_config("deepseek").model_id == "deepseek-v4-flash"


def test_structured_request_uses_mock_client():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=" result "))]
    )
    client, calls = client_for(response)
    service = LLMService("deepseek", client=client, environ={"DEEPSEEK_API_KEY": "fake"})
    messages = [{"role": "user", "content": "hello"}]
    assert service.request(messages) == " result "
    assert calls.calls[0]["messages"] == messages


def test_ollama_adapter_does_not_require_an_api_key():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="local result"))]
    )
    client, _ = client_for(response)
    service = LLMService("ollama", client=client, environ={})
    assert service.request([]) == "local result"
    assert service.config.provider == "ollama"


def test_length_finish_reason_marks_response_as_truncated():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="partial"),
            )
        ]
    )
    client, _ = client_for(response)
    service = LLMService("deepseek", client=client, environ={"DEEPSEEK_API_KEY": "fake"})
    answer = service.request([])
    assert answer == "partial"
    assert answer.truncated is True


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace(message=None)]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  "))]),
    ],
)
def test_empty_responses_are_reported(response):
    client, _ = client_for(response)
    service = LLMService("deepseek", client=client, environ={"DEEPSEEK_API_KEY": "fake"})
    with pytest.raises(EmptyResponseError):
        service.request([])


def test_provider_exception_is_wrapped_without_secrets():
    client, _ = client_for(error=RuntimeError("offline"))
    service = LLMService("deepseek", client=client, environ={"DEEPSEEK_API_KEY": "secret"})
    with pytest.raises(LLMRequestError, match="offline") as exc:
        service.request([])
    assert "secret" not in str(exc.value)


def test_provider_exception_redacts_key_if_provider_echoes_it():
    client, _ = client_for(error=RuntimeError("request contained secret-value"))
    service = LLMService(
        "deepseek", client=client, environ={"DEEPSEEK_API_KEY": "secret-value"}
    )
    with pytest.raises(LLMRequestError) as exc:
        service.request([])
    assert "secret-value" not in str(exc.value)


def test_transient_failures_retry_with_backoff(tmp_path):
    class FlakyCompletions:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("temporary")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="recovered"))]
            )

    completions = FlakyCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    manager = ConfigManager(tmp_path / "config.json")
    manager.add_profile(
        "retrying",
        ModelProfile(
            "ollama",
            "local",
            "http://localhost:11434/v1",
            None,
            max_retries=2,
        ),
    )
    delays = []
    service = LLMService("retrying", client=client, manager=manager, sleep=delays.append)
    service.adapter._is_retryable = lambda exc: True
    answer = service.request([])
    assert answer == "recovered" and answer.attempts == 3
    assert delays == [0.5, 1.0]


def test_custom_profile_is_resolved_by_llm_service(tmp_path):
    manager = ConfigManager(tmp_path / "config.json")
    manager.add_profile(
        "localtest",
        ModelProfile("ollama", "test-model", "http://localhost:11434/v1", None),
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="custom result"))]
    )
    client, _ = client_for(response)
    service = LLMService("localtest", client=client, manager=manager, environ={})
    assert service.request([]) == "custom result"
    assert service.config.model_id == "test-model"


def test_profile_timeouts_disable_sdk_retries(tmp_path, monkeypatch):
    captured = {}
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr("smartcli.services.llm.OpenAI", fake_openai)
    manager = ConfigManager(tmp_path / "config.json")
    manager.add_profile(
        "timed",
        ModelProfile(
            "ollama",
            "local",
            "http://localhost:11434/v1",
            None,
            timeout_seconds=45,
            connect_timeout_seconds=4,
        ),
    )
    LLMService("timed", manager=manager, environ={})
    assert captured["max_retries"] == 0
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["timeout"].connect == 4
    assert captured["timeout"].read == 45
