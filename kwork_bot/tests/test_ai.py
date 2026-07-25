"""Тесты GeminiClient: fallback моделей и graceful failure (через моки)."""

from __future__ import annotations

from types import SimpleNamespace

from google.genai import errors as genai_errors

import ai.gemini_client as gc


class _Settings:
    gemini_api_key = "test-key"
    gemini_model = "gemini-1.5-flash"
    gemini_fallback_model = "gemini-2.5-flash"
    gemini_max_tokens = 256
    gemini_temperature = 0.5
    gemini_rps = 0.0
    # Один вызов на модель: ретрай временных ошибок проверяется отдельно
    # (tests → utils.retry в Части 2), здесь фокус на переходе к fallback-модели.
    retry_attempts = 1
    retry_base_delay = 0.0
    retry_max_delay = 0.0

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)


class _NoKeySettings(_Settings):
    gemini_api_key = ""


class _ClientError(genai_errors.ClientError):
    def __init__(self, code: int) -> None:
        self.code = code


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(candidates=[object()], text=text)


def _install_fake_call(client: gc.GeminiClient, handler) -> list[str]:
    calls: list[str] = []

    async def generate_content(*, model, contents, config):  # noqa: ANN001
        calls.append(model)
        return await handler(model)

    client._client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    return calls


async def test_fallback_on_quota_exhausted() -> None:
    client = gc.GeminiClient(_Settings())

    async def handler(model: str):
        if model == "gemini-1.5-flash":
            raise _ClientError(429)  # квота исчерпана
        return _fake_response("Ответ от резервной модели")

    calls = _install_fake_call(client, handler)
    result = await client.generate("system", "user")

    assert result == "Ответ от резервной модели"
    assert calls == ["gemini-1.5-flash", "gemini-2.5-flash"]  # был переход на fallback


async def test_permanent_error_no_fallback() -> None:
    client = gc.GeminiClient(_Settings())

    async def handler(_model: str):
        raise _ClientError(400)  # постоянная ошибка запроса

    calls = _install_fake_call(client, handler)
    result = await client.generate("system", "user")

    assert result is None
    assert calls == ["gemini-1.5-flash"]  # fallback НЕ вызывается на 400


async def test_primary_success_no_fallback() -> None:
    client = gc.GeminiClient(_Settings())

    async def handler(_model: str):
        return _fake_response("Ответ основной модели")

    calls = _install_fake_call(client, handler)
    result = await client.generate("system", "user")

    assert result == "Ответ основной модели"
    assert calls == ["gemini-1.5-flash"]


async def test_graceful_without_api_key() -> None:
    client = gc.GeminiClient(_NoKeySettings())
    assert await client.generate("system", "user") is None


def test_transient_classification_and_retry_after() -> None:
    assert gc._is_transient(_ClientError(429)) is True
    assert gc._is_transient(_ClientError(400)) is False
    assert gc._is_transient(ConnectionError()) is True
    assert gc._retry_after_seconds(Exception('"retryDelay": "12s"')) == 12.0
    assert gc._retry_after_seconds(Exception("Retry-After: 5")) == 5.0
    assert gc._retry_after_seconds(Exception("no hint")) is None
