"""Одноразовый вход в Telegram (создаёт файл сессии).

Запустите ОДИН раз:  python login.py

Код подтверждения по умолчанию приходит СООБЩЕНИЕМ внутри приложения Telegram
(чат «Telegram»). Если он туда не доходит — введите здесь слово `sms`, и код
придёт по СМС. Слово `resend` — повторно отправить код в приложение.
"""

from __future__ import annotations

import asyncio
from getpass import getpass

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from config import get_settings


async def main() -> None:
    s = get_settings()

    if not s.telegram_ready:
        print("❌ Сначала заполните TG_API_ID и TG_API_HASH в файле .env")
        return

    phone = s.tg_phone.strip()
    if not phone:
        phone = input("Введите номер телефона (например +79991234567): ").strip()

    client = TelegramClient(s.tg_session, s.tg_api_id, s.tg_api_hash)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✅ Уже авторизованы: {me.first_name} (@{me.username}). Запускайте: python main.py")
        await client.disconnect()
        return

    # 1) Запрашиваем код (сначала — в приложение Telegram).
    try:
        await client.send_code_request(phone)
    except ApiIdInvalidError:
        print("\n❌ Неверные TG_API_ID / TG_API_HASH. Проверьте на https://my.telegram.org")
        await client.disconnect()
        return
    except PhoneNumberInvalidError:
        print("\n❌ Неверный номер. Нужен формат с плюсом, например +79991234567")
        await client.disconnect()
        return
    except FloodWaitError as exc:
        print(f"\n❌ Слишком много попыток. Подождите {exc.seconds} сек и повторите.")
        await client.disconnect()
        return

    print("\n📩 Код отправлен в приложение Telegram (чат «Telegram»).")
    print("   • не пришёл в приложение? введите  sms   — пришлём по СМС")
    print("   • ввести код заново позже?  введите  resend — отправим ещё раз\n")

    # 2) Интерактивный ввод кода с возможностью пересылки по СМС.
    try:
        while True:
            entry = input("Код из Telegram (или 'sms' / 'resend'): ").strip()

            if entry.lower() == "sms":
                try:
                    await client.send_code_request(phone, force_sms=True)
                    print("📲 Запросили код по СМС. Дождитесь сообщения и введите его.")
                except FloodWaitError as exc:
                    print(f"⏳ Подождите {exc.seconds} сек перед повторным запросом.")
                continue

            if entry.lower() == "resend":
                try:
                    await client.send_code_request(phone)
                    print("📩 Код отправлен повторно в приложение Telegram.")
                except FloodWaitError as exc:
                    print(f"⏳ Подождите {exc.seconds} сек перед повторным запросом.")
                continue

            if not entry:
                continue

            try:
                await client.sign_in(phone=phone, code=entry)
                break
            except PhoneCodeInvalidError:
                print("❌ Неверный код. Возьмите самый свежий и введите ещё раз.")
            except PhoneCodeExpiredError:
                print("❌ Код истёк. Введите 'resend' (в приложение) или 'sms' (по СМС).")
            except SessionPasswordNeededError:
                # Включена двухэтапная проверка (облачный пароль).
                while True:
                    pwd = getpass("🔐 Введите облачный пароль (2FA): ")
                    try:
                        await client.sign_in(password=pwd)
                        break
                    except Exception:
                        print("❌ Неверный пароль, попробуйте ещё раз.")
                break

        me = await client.get_me()
        print(f"\n✅ Готово! Вошли как {me.first_name} (@{me.username}), id={me.id}")
        print(f"Файл сессии «{s.tg_session}.session» создан. Запускайте: python main.py")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
