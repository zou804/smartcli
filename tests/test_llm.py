from __future__ import annotations

from types import SimpleNamespace

import pytest

from smartcli.config import ConfigurationError, get_model_config
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
