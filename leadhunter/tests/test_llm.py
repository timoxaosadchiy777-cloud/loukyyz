"""Тесты GeminiLLM: переход на резервную модель при 404/сбое (через моки)."""

from __future__ import annotations

from types import SimpleNamespace

from google.genai import errors as genai_errors

import ai.llm as llm_mod


class _Settings:
    gemini_api_key = "test-key"
    gemini_model = "primary-model"
    gemini_fallback_model = "fallback-model"
    gemini_max_tokens = 128
    gemini_temperature = 0.0
    # Один вызов на модель — фокус на переходе к fallback, не на ретраях.
    retry_attempts = 1
    retry_base_delay = 0.0

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)


class _NoKeySettings(_Settings):
    gemini_api_key = ""

    @property
    def gemini_ready(self) -> bool:
        return False


class _ClientError(genai_errors.ClientError):
    def __init__(self, code: int) -> None:
        self.code = code


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(candidates=[object()], text=text)


def _install(client: llm_mod.GeminiLLM, handler) -> list[str]:
    calls: list[str] = []

    async def generate_content(*, model, contents, config):  # noqa: ANN001
        calls.append(model)
        return await handler(model)

    client._client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    return calls


async def _complete(client: llm_mod.GeminiLLM) -> str | None:
    return await client.complete(
        system="s", user="u", max_output_tokens=10, temperature=0.0, label="t"
    )


async def test_fallback_on_404() -> None:
    client = llm_mod.GeminiLLM(_Settings())

    async def handler(model: str):
        if model == "primary-model":
            raise _ClientError(404)  # модель снята с обслуживания
        return _fake_response("ответ резервной модели")

    calls = _install(client, handler)
    assert await _complete(client) == "ответ резервной модели"
    assert calls == ["primary-model", "fallback-model"]


async def test_primary_success_no_fallback() -> None:
    client = llm_mod.GeminiLLM(_Settings())

    async def handler(_model: str):
        return _fake_response("ответ основной модели")

    calls = _install(client, handler)
    assert await _complete(client) == "ответ основной модели"
    assert calls == ["primary-model"]  # резерв не вызывался


async def test_empty_response_triggers_fallback() -> None:
    client = llm_mod.GeminiLLM(_Settings())

    async def handler(model: str):
        if model == "primary-model":
            return SimpleNamespace(candidates=[], text=None)  # пусто/фильтр
        return _fake_response("ответ резервной модели")

    calls = _install(client, handler)
    assert await _complete(client) == "ответ резервной модели"
    assert calls == ["primary-model", "fallback-model"]


async def test_all_models_fail_returns_none() -> None:
    client = llm_mod.GeminiLLM(_Settings())

    async def handler(_model: str):
        raise _ClientError(404)

    calls = _install(client, handler)
    assert await _complete(client) is None
    assert calls == ["primary-model", "fallback-model"]


async def test_no_api_key_returns_none() -> None:
    client = llm_mod.GeminiLLM(_NoKeySettings())
    assert await _complete(client) is None
