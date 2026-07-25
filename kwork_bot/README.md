# kwork_bot

Коммерческий бот мониторинга заказов **Kwork.ru** с генерацией откликов через
**Google Gemini** и криптографической защитой лицензии (Ed25519).

Пайплайн:

```
Playwright (Kwork) → LeadService → dedup → filter → Gemini → DeliveryService → Telegram
```

- **Playwright** читает биржу проектов Kwork (сессия из `storage_state.json`).
- **SQLAlchemy 2.0 async + SQLite (WAL)** — дедупликация и история (миграции Alembic).
- **Gemini** (`gemini-1.5-flash` → fallback `gemini-2.5-flash`) пишет отклик на русском.
- **aiogram 3.x** доставляет карточку владельцу с кнопками: открыть / обновить / скопировать.
- **Лицензия** проверяется криптографически (подпись + срок + привязка к машине).

Стек: Python 3.11+, asyncio (TaskGroup), SQLAlchemy 2.0 async, Alembic, Playwright,
aiogram 3.x, Pydantic v2, cryptography.

---

## 1. Установка локально

```bash
cd kwork_bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # Windows: copy .env.example .env
```

Запуск (пакеты лежат в `src/`, поэтому нужен `PYTHONPATH=src`):

```bash
# миграции (создать схему БД)
alembic upgrade head
# запуск бота
PYTHONPATH=src python -m main       # Windows: set PYTHONPATH=src && python -m main
```

---

## 2. Создание `.env`

Скопируйте `.env.example` в `.env` и заполните:

| Переменная | Что это | Где взять |
|---|---|---|
| `BOT_TOKEN` | токен Telegram-бота | [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | ваш Telegram id | [@userinfobot](https://t.me/userinfobot) |
| `GEMINI_API_KEY` | ключ Google Gemini | https://aistudio.google.com |
| `LICENSE_KEY` | подписанный токен лицензии | генерируется (см. §4) |
| `LICENSE_PUBLIC_KEY` | публичный ключ издателя | генерируется (см. §4) |

Остальные параметры (`GEMINI_MODEL`, `KWORK_*`, `RETRY_*`, `DATABASE_PATH`, …) имеют
рабочие значения по умолчанию — меняйте при необходимости.

---

## 3. Добавление `storage_state.json` (сессия Kwork)

Бот не логинится сам — используйте готовую сессию браузера. Один раз выполните
интерактивный вход и сохраните состояние (на машине с графикой) готовым скриптом:

```bash
python scripts/save_kwork_session.py
```

Откроется окно браузера — войдите в аккаунт Kwork и нажмите Enter в консоли.
Сессия сохранится по пути из `KWORK_STORAGE_STATE` (по умолчанию `data/storage_state.json`).

Файл `data/storage_state.json` подхватится по умолчанию (`KWORK_STORAGE_STATE`).
Обновляйте его, когда сессия Kwork протухнет (в логах: «сессия не активна»).

---

## 4. Генерация ключей лицензии

Утилита `scripts/license_tool.py`:

```bash
# 1) пара ключей издателя (private храните у себя, public — клиенту в .env)
python scripts/license_tool.py keygen

# 2) отпечаток машины клиента (если нужна привязка)
python scripts/license_tool.py fingerprint

# 3) выпуск лицензии клиенту (365 дней; --bind — привязать к текущей машине)
python scripts/license_tool.py issue --private <PRIVATE_B64> --key CUST-001 --days 365
```

- `LICENSE_PUBLIC_KEY` из шага 1 → в `.env` клиента.
- Токен из шага 3 → в `LICENSE_KEY` клиента.
- Приватный ключ **никогда** не попадает к клиенту — им подписываются лицензии.
- Подделать лицензию без приватного ключа нельзя; подмена строк в БД доступ не даёт
  (решение принимается по подписи токена, БД — только кэш/аудит).

---

## 5. Команды миграций (Alembic)

```bash
alembic upgrade head                     # применить все миграции
alembic downgrade -1                     # откатить последнюю
alembic revision --autogenerate -m "msg" # создать новую миграцию по изменениям моделей
alembic current                          # текущая ревизия
```

`alembic.ini` использует `prepend_sys_path = src`, а URL БД берётся из настроек
(`migrations/env.py`) — отдельно прописывать его не нужно.

---

## 6. Запуск в Docker

```bash
cp .env.example .env         # заполнить ключи
# положить data/storage_state.json (см. §3) — каталог ./data монтируется в контейнер
docker compose up -d --build
docker compose logs -f
docker compose down
```

- Контейнер стартует под **non-root** пользователем (`appuser`).
- `entrypoint` сам применяет `alembic upgrade head`, затем запускает бота.
- **Тома:** `./data` (SQLite + `storage_state.json`) и `./logs`.
- **HEALTHCHECK** вызывает `python -m utils.healthcheck` (проверяет свежесть heartbeat).
- `restart: unless-stopped` поднимает сервис после сбоя/перезагрузки хоста.

---

## 7. Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Покрытие: фильтрация лидов (`test_filters`), fallback Gemini через мок (`test_ai`),
валидная/невалидная/просроченная/подделанная лицензия (`test_license`), парсер на
фиктивном DOM без обращения к Kwork (`test_parser`).

---

## 8. Troubleshooting

| Симптом | Причина / решение |
|---|---|
| `Лицензия недействительна: …` на старте | Проверьте `LICENSE_KEY`/`LICENSE_PUBLIC_KEY`; перевыпустите токен (§4). Просрочка — новый `--days`. |
| В логах «сессия не активна» / карточек нет | Протухла сессия Kwork — обновите `data/storage_state.json` (§3). |
| `Kwork: карточки не найдены` при наличии проектов | Сменилась вёрстка — обновите селекторы в `src/parsers/kwork_parser.py`. |
| Gemini `429` / пустые отклики | Исчерпана квота — сработает fallback-модель; при обеих исчерпанных карточка уйдёт без ИИ-текста (жмите «Обновить отклик» позже). |
| `ModuleNotFoundError: config/models/...` | Не задан `PYTHONPATH=src` при локальном запуске. |
| Бот не отвечает на `/start` | Неверный `BOT_TOKEN`, или лицензия невалидна (её проверяет middleware). |
| Playwright не стартует локально | Выполните `playwright install chromium` (в Docker уже встроено). |
| Healthcheck «unhealthy» | Процесс не пишет heartbeat — смотрите `./logs/kwork_bot.log`. |
