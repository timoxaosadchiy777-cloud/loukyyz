"""Одноразовый вход в Kwork (сохраняет сессию браузера).

Запустите ОДИН раз:  python kwork_login.py

Откроется окно браузера — войдите в свой аккаунт Kwork вручную (при
необходимости решите капчу). Затем вернитесь в консоль и нажмите Enter.
Сессия сохранится в `storage_state.json`, и бот будет заходить на Kwork уже
залогиненным. Пароль в проекте НЕ хранится.
"""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from config import get_settings


async def main() -> None:
    s = get_settings()

    print("Открываю браузер…")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://kwork.ru/", wait_until="domcontentloaded")

        print("\n➡️  В открывшемся окне войдите в свой аккаунт Kwork.")
        print("    Когда увидите, что вошли — вернитесь сюда и нажмите Enter.")
        await asyncio.to_thread(input, "Нажмите Enter после входа… ")

        await context.storage_state(path=s.kwork_storage_state)
        print(f"\n✅ Сессия сохранена в «{s.kwork_storage_state}».")
        print("Теперь запускайте бота:  python main.py")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
