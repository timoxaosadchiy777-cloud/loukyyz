"""Одноразовый вход в Telegram (создаёт файл сессии).

Запустите ОДИН раз:  python login.py
Введите код из Telegram — и создастся файл *.session. После этого обычный
запуск `python main.py` уже не будет спрашивать код.

⚠️  Код подтверждения приходит СООБЩЕНИЕМ внутри приложения Telegram
    (от официального аккаунта «Telegram»), а НЕ по СМС.
"""

from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PhoneNumberInvalidError,
)

from config import get_settings


async def main() -> None:
    s = get_settings()

    if not s.telegram_ready:
        print("❌ Сначала заполните TG_API_ID и TG_API_HASH в файле .env")
        return

    print("Подключаюсь к Telegram…")
    print("ℹ️  Код придёт СООБЩЕНИЕМ внутри приложения Telegram (чат «Telegram»),")
    print("    а не по СМС. Введите его сюда, когда попросит.\n")

    client = TelegramClient(s.tg_session, s.tg_api_id, s.tg_api_hash)
    try:
        await client.start(phone=s.tg_phone or None)
        me = await client.get_me()
        print(f"\n✅ Готово! Вошли как {me.first_name} (@{me.username}), id={me.id}")
        print(f"Файл сессии «{s.tg_session}.session» создан.")
        print("Теперь запускайте бота:  python main.py")
    except ApiIdInvalidError:
        print("\n❌ Неверные TG_API_ID / TG_API_HASH.")
        print("   Проверьте их на https://my.telegram.org (раздел API development tools).")
        print("   api_id — это число, api_hash — длинная строка из букв и цифр. Не перепутайте местами.")
    except PhoneNumberInvalidError:
        print("\n❌ Неверный номер телефона.")
        print("   Нужен международный формат с плюсом, например: +79991234567")
    except FloodWaitError as exc:
        print(f"\n❌ Слишком много попыток входа. Подождите {exc.seconds} сек и повторите.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
