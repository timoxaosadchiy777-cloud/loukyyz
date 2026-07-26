"""Диагностика AI-провайдеров LeadHunter.

Запуск:  python check_ai.py   (из каталога leadhunter/ или из корня репозитория)

Показывает по каждому провайдеру (OpenRouter, Groq, Ollama, Gemini): настроен ли
он, какая модель, и делает РЕАЛЬНЫЙ тестовый вызов (Status: OK / FAILED + причина).
В конце — какой провайдер станет основным (первый ответивший из цепочки роутера).

Скрипт НЕ импортирует парсеры (feedparser), поэтому запускается всегда.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai.llm import _build_providers  # noqa: E402
from ai.providers.base import ProviderError  # noqa: E402
from config import get_settings  # noqa: E402

_TEST_PROMPT = "Reply with exactly one word: pong"


async def _probe(provider) -> tuple[bool, str]:
    """Пробный вызов провайдера. Возвращает (успех, детали)."""
    if not provider.is_configured():
        return False, "не настроен (нет ключа/выключен)"
    try:
        text = await provider.generate(_TEST_PROMPT, max_tokens=20, temperature=0.0)
        return True, f"ответ: {text.strip()[:60]!r}"
    except ProviderError as exc:
        return False, exc.reason
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def main() -> int:
    settings = get_settings()
    providers = _build_providers(settings)

    print("=" * 40)
    print("LeadHunter AI Check")
    print("=" * 40)
    print(f"\nОсновной (AI_PROVIDER): {settings.ai_provider}")
    print(f"Порядок fallback: {', '.join(p.name for p in providers)}")

    first_ok: str | None = None
    for provider in providers:
        ok, detail = await _probe(provider)
        print(f"\n{provider.name}:")
        print(f"  Модель: {getattr(provider, '_model', '—')}")
        print(f"  Настроен: {'да' if provider.is_configured() else 'нет'}")
        print(f"  Status: {'OK' if ok else 'FAILED'}")
        if not ok:
            print(f"  Причина: {detail}")
        else:
            print(f"  {detail}")
        if ok and first_ok is None:
            first_ok = provider.name
        await provider.aclose()

    print("\n" + "=" * 40)
    if first_ok:
        print(f"Текущий провайдер (будет использован): {first_ok}")
        print("AI-слой рабочий ✅")
        return 0
    print("Текущий провайдер: НЕТ — ни один провайдер не ответил ❌")
    print("Впиши ключ в .env: OPENROUTER_API_KEY (или GROQ_API_KEY), "
          "получить бесплатно: https://openrouter.ai/keys , https://console.groq.com/keys")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
