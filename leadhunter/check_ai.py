"""Быстрая проверка интеграции с Google Gemini.

Запуск:  python check_ai.py       (из каталога leadhunter/ или из корня репозитория)

Что делает:
  1) загружает .env (через настройки проекта);
  2) показывает: найден ли GEMINI_API_KEY, версию SDK, основную и резервную модель;
  3) делает РЕАЛЬНЫЙ тестовый вызов основной модели, при неудаче — резервной;
  4) печатает ответ модели ЛИБО реальную ошибку Gemini (код/статус/сообщение +
     трейсбек), чтобы сразу понять, работает AI или нет и почему.

Скрипт намеренно НЕ импортирует парсеры (feedparser), поэтому запускается даже
если что-то не так с зависимостями парсинга.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

# Каталог проекта в sys.path — чтобы работал импорт config/ai независимо от CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from google import genai  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402
from google.genai import types  # noqa: E402

from config import get_settings  # noqa: E402

_TEST_PROMPT = "Reply with exactly one word: pong"


def _mask(key: str) -> str:
    if not key:
        return "(пусто)"
    return f"{key[:4]}…{key[-4:]} (длина {len(key)})"


async def _call(client: genai.Client, model: str) -> None:
    print(f"\n=== Тест модели: {model} ===")
    try:
        resp = await client.aio.models.generate_content(
            model=model,
            contents=_TEST_PROMPT,
            config=types.GenerateContentConfig(max_output_tokens=20, temperature=0.0),
        )
        text = (resp.text or "").strip() if resp.candidates else ""
        if text:
            print(f"✅ OK — модель ответила: {text!r}")
        else:
            print("⚠️  Пустой ответ (возможно, сработал фильтр). candidates:", resp.candidates)
    except genai_errors.APIError as exc:
        print("❌ GEMINI ERROR:")
        print(f"   code    = {getattr(exc, 'code', '?')}")
        print(f"   status  = {getattr(exc, 'status', '?')}")
        print(f"   message = {getattr(exc, 'message', None) or exc}")
        _hint(getattr(exc, "code", None))
    except Exception as exc:  # noqa: BLE001
        print(f"❌ GEMINI ERROR ({type(exc).__name__}): {exc}")
        traceback.print_exc()


def _hint(code: object) -> None:
    hints = {
        400: "Похоже на неверный запрос/ключ. Проверь GEMINI_API_KEY.",
        403: "Доступ запрещён: ключ без прав или модель недоступна для проекта.",
        404: "Модель не найдена: смени GEMINI_MODEL на актуальную (напр. gemini-2.0-flash).",
        429: "Исчерпана квота (RESOURCE_EXHAUSTED). Подожди или подключи биллинг/новый ключ.",
    }
    if code in hints:
        print(f"   💡 {hints[code]}")


async def main() -> int:
    settings = get_settings()
    print("=" * 50)
    print("LeadHunter — проверка Google Gemini")
    print("=" * 50)
    print(f"SDK google-genai : {getattr(genai, '__version__', 'unknown')}")
    print(f"GEMINI_API_KEY   : {'найден ' + _mask(settings.gemini_api_key) if settings.gemini_ready else 'НЕ НАЙДЕН'}")
    print(f"Основная модель  : {settings.gemini_model}")
    print(f"Резервная модель : {settings.gemini_fallback_model}")

    if not settings.gemini_ready:
        print("\n❌ GEMINI_API_KEY не задан. Впиши его в leadhunter/.env:")
        print("   GEMINI_API_KEY=<ключ из https://aistudio.google.com>")
        return 1

    client = genai.Client(api_key=settings.gemini_api_key)
    await _call(client, settings.gemini_model)
    if settings.gemini_fallback_model and settings.gemini_fallback_model != settings.gemini_model:
        await _call(client, settings.gemini_fallback_model)

    print("\nГотово. Если обе модели ответили ✅ — AI-слой рабочий.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
