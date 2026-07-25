"""Разовое сохранение сессии Kwork в storage_state.json.

Запустите на машине с графикой:  python scripts/save_kwork_session.py
Откроется браузер — войдите в аккаунт Kwork вручную, вернитесь в консоль и нажмите
Enter. Файл сессии будет сохранён по пути из настроек (KWORK_STORAGE_STATE).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.settings import get_settings  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402


async def main() -> None:
    settings = get_settings()
    target = Path(settings.kwork_storage_state)
    target.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://kwork.ru/", wait_until="domcontentloaded")
        await asyncio.to_thread(input, "Войдите в аккаунт Kwork и нажмите Enter… ")
        await context.storage_state(path=str(target))
        print(f"✅ Сессия сохранена в {target}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
