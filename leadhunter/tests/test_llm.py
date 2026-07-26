"""Тесты слоя LLM: fallback роутера между провайдерами и разбор HTTP-провайдера."""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from ai.llm import LLMRouter, _build_providers, _combine
from ai.providers.base import AIProvider, ProviderError
from ai.providers.openrouter import OpenRouterProvider
from core.runtime_config import LlmConfig


class FakeProvider(AIProvider):
    def __init__(self, name, *, configured=True, result="ok", error=None):
        self.name = name
        self._configured = configured
        self._result = result
        self._error = error
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    async def generate(self, prompt, *, json_mode=False, max_tokens=1024, temperature=0.7):
        self.calls += 1
        if self._error is not None:
            raise ProviderError(self.name, self._error)
        return self._result


async def _complete(router: LLMRouter):
    return await router.complete(
        system="sys", user="usr", max_output_tokens=10, temperature=0.0, label="t"
    )


# --- Роутер: порядок и fallback ---

async def test_uses_first_configured_provider() -> None:
    a = FakeProvider("A", result="from-A")
    b = FakeProvider("B", result="from-B")
    router = LLMRouter([a, b])
    assert await _complete(router) == "from-A"
    assert router.current_provider == "A"
    assert b.calls == 0  # второй провайдер не трогали


async def test_falls_back_on_error() -> None:
    a = FakeProvider("A", error="лимит (429)")
    b = FakeProvider("B", result="from-B")
    router = LLMRouter([a, b])
    assert await _complete(router) == "from-B"
    assert router.current_provider == "B"
    assert a.calls == 1 and b.calls == 1
    assert router.last_error == ""  # успех сбрасывает ошибку


async def test_skips_unconfigured() -> None:
    a = FakeProvider("A", configured=False)
    b = FakeProvider("B", result="from-B")
    router = LLMRouter([a, b])
    assert await _complete(router) == "from-B"
    assert a.calls == 0  # ненастроенного не вызывают


async def test_all_fail_returns_none_with_last_error() -> None:
    a = FakeProvider("A", error="quota exceeded")
    b = FakeProvider("B", error="model not found")
    router = LLMRouter([a, b])
    assert await _complete(router) is None
    assert "A: quota exceeded" in router.last_error
    assert "B: model not found" in router.last_error


async def test_no_providers() -> None:
    router = LLMRouter([])
    assert await _complete(router) is None
    assert "нет настроенных" in router.last_error


def test_combine_prompt() -> None:
    combined = _combine("SYS", "USR")
    assert "SYS" in combined and "USR" in combined
    assert _combine("", "only user") == "only user"


# --- Порядок провайдеров из настроек ---

def _fake_settings(ai_provider="ollama"):
    """Настройки без единого ключа — как у пользователя без платных API."""
    return SimpleNamespace(
        ai_provider=ai_provider,
        openrouter_api_key="", openrouter_model="m",
        groq_api_key="", groq_model="m",
        ollama_enabled=False, ollama_host="http://x", ollama_model="m",
        gemini_api_key="", gemini_model="m",
    )


def test_local_only_chain_without_keys() -> None:
    """Без ключей цепочка — только локальный Ollama: платные API не дёргаются."""
    names = [p.name for p in _build_providers(_fake_settings(), LlmConfig())]
    assert names == ["Ollama"]


def test_ollama_is_default_primary() -> None:
    """Дефолтный провайдер — локальный Ollama с моделью из settings.yaml."""
    cfg = LlmConfig()
    assert cfg.provider == "ollama"
    assert cfg.model == "llama3.1:8b"
    assert cfg.base_url == "http://localhost:11434"
    provider = _build_providers(_fake_settings(), cfg)[0]
    assert provider.name == "Ollama"
    assert provider.is_configured() is True  # ключи не нужны


def test_paid_provider_appended_only_with_key() -> None:
    """Платный провайдер попадает в хвост цепочки, только если задан его ключ."""
    settings = _fake_settings()
    settings.groq_api_key = "gk"
    names = [p.name for p in _build_providers(settings, LlmConfig())]
    assert names == ["Ollama", "Groq"]  # Ollama первый, Groq — резерв
    assert "OpenRouter" not in names and "Gemini" not in names


def test_missing_dependency_skips_provider(monkeypatch) -> None:
    """Провайдер с неустановленной зависимостью (напр. google-genai) пропускается,
    а не роняет сборку цепочки — остальные работают."""
    import ai.llm as llm_mod

    real_import = llm_mod.importlib.import_module

    def fake_import(path):
        if path.endswith(".gemini"):
            raise ModuleNotFoundError("No module named 'google'")
        return real_import(path)

    monkeypatch.setattr(llm_mod.importlib, "import_module", fake_import)
    settings = _fake_settings()
    settings.gemini_api_key = "gemkey"  # ключ есть, но пакет не установлен
    names = [p.name for p in _build_providers(settings, LlmConfig())]
    assert "Gemini" not in names   # пропущен из-за отсутствия зависимости
    assert "Ollama" in names       # локальный провайдер на месте


# --- HTTP-провайдер (OpenAI-совместимый) через мок-транспорт ---

def _openrouter_with(handler) -> OpenRouterProvider:
    p = OpenRouterProvider("test-key", "test-model")
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return p


async def test_openai_chat_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    provider = _openrouter_with(handler)
    try:
        assert await provider.generate("ping") == "pong"
    finally:
        await provider.aclose()


async def test_openai_chat_429_maps_to_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limit"})

    provider = _openrouter_with(handler)
    try:
        try:
            await provider.generate("ping")
            assert False, "ожидалась ProviderError"
        except ProviderError as exc:
            assert exc.provider == "OpenRouter"
            assert "429" in exc.reason
    finally:
        await provider.aclose()


async def test_openai_chat_401_maps_to_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    provider = _openrouter_with(handler)
    try:
        try:
            await provider.generate("ping")
            assert False, "ожидалась ProviderError"
        except ProviderError as exc:
            assert "401" in exc.reason
    finally:
        await provider.aclose()
