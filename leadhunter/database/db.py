"""Асинхронное хранилище заказов и пользователей на aiosqlite.

Отвечает за дедупликацию (UNIQUE по source+external_id), сохранение истории,
AI-оценки (score / category / reason / should_send) и статусов:
  * ``status``     — состояние пайплайна (new / rejected / filtered);
  * ``crm_status`` — воронка продаж (new / contacted / negotiation / won / lost).

Плюс таблица ``users`` — доступ к боту (paid_status), выдаётся администратором.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

from core.models import CrmStatus, LeadState, Order
from core.sources import SOURCES
from core.user_settings import UserSettings

log = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pack(values: tuple[str, ...]) -> str:
    return ",".join(values)


def _unpack(raw: str | None) -> tuple[str, ...]:
    return tuple(part for part in (raw or "").split(",") if part)

def _settings_from_row(row) -> UserSettings:
    """Собирает UserSettings из строки user_settings (или из LEFT JOIN с NULL)."""
    try:
        onboarded = row["onboarded"]
    except (IndexError, KeyError):
        onboarded = 0
    if onboarded is None:
        # LEFT JOIN без совпадения: пользователь ещё не настраивался.
        return UserSettings()
    return UserSettings(
        sources=_unpack(row["sources"]),
        categories=_unpack(row["categories"]),
        keywords=_unpack(row["keywords"]),
        min_budget=row["min_budget"] or 0,
        onboarded=bool(onboarded),
    )


# Таблица создаётся первой. Индексы — отдельно и ПОСЛЕ миграции колонок: на
# старой БД колонки crm_status ещё нет, и индекс по ней нельзя создавать до ALTER.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,
    external_id   TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    url           TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    budget_raw    TEXT,
    budget_value  INTEGER,
    budget_currency TEXT NOT NULL DEFAULT 'USD',
    published_at  TEXT NOT NULL DEFAULT '',
    response      TEXT,
    status              TEXT    NOT NULL DEFAULT 'new',
    score               INTEGER,
    category            TEXT    NOT NULL DEFAULT '',
    reason              TEXT    NOT NULL DEFAULT '',
    probability_of_sale INTEGER,
    should_send         INTEGER,
    technology          TEXT    NOT NULL DEFAULT '',
    summary             TEXT    NOT NULL DEFAULT '',
    crm_status          TEXT    NOT NULL DEFAULT 'new',
    created_at          TEXT    NOT NULL,
    UNIQUE(source, external_id)
);
"""

# Пользователи бота. Доступ бинарный: paid_status 0 = нет доступа, 1 = есть.
# Администратор (OWNER_ID) в этой таблице не нуждается — его доступ безусловен.
_USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username    TEXT    NOT NULL DEFAULT '',
    paid_status INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
"""

# Персональные фильтры: по строке на пользователя. Списки хранятся строкой через
# запятую — их всегда читают целиком, отдельные таблицы дали бы только JOIN'ы.
_USER_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_settings (
    telegram_id INTEGER PRIMARY KEY,
    sources     TEXT    NOT NULL DEFAULT '',
    categories  TEXT    NOT NULL DEFAULT '',
    keywords    TEXT    NOT NULL DEFAULT '',
    min_budget  INTEGER NOT NULL DEFAULT 0,
    onboarded   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL
);
"""

# Доставки лидов конкретным пользователям — ядро fan-out.
#
# Одна строка = «этот пользователь уже видел этот лид». Отсюда сразу три вещи:
#   * дедупликация (PK) — повторно лид тому же человеку не уйдёт;
#   * личное состояние (sent / saved / rejected) и личный статус воронки —
#     под fan-out они не могут быть общими на заказ: иначе один пользователь
#     переводит лид в «Выиграл», и это видят все остальные;
#   * личный черновик отклика, который можно переписать, не трогая чужие.
_DELIVERIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS lead_deliveries (
    telegram_id INTEGER NOT NULL,
    order_id    INTEGER NOT NULL,
    state       TEXT    NOT NULL DEFAULT 'sent',
    response    TEXT    NOT NULL DEFAULT '',
    crm_status  TEXT    NOT NULL DEFAULT 'new',
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (telegram_id, order_id)
);
"""

# Включённые источники — по строке на пару (пользователь, биржа).
#
# Отдельная таблица, а не список в user_settings: там пустой список означал
# «все включены», и выразить «эта биржа выключена ПО УМОЛЧАНИЮ» было нечем.
# Здесь состояние трёхзначное: строка есть → явный выбор пользователя,
# строки нет → берём default_enabled из реестра источников.
_SOURCES_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources_settings (
    telegram_user_id INTEGER NOT NULL,
    source           TEXT    NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    updated_at       TEXT    NOT NULL,
    PRIMARY KEY (telegram_user_id, source)
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_orders_source_ext ON orders(source, external_id);
CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_crm        ON orders(crm_status);
CREATE INDEX IF NOT EXISTS idx_users_paid        ON users(paid_status);
CREATE INDEX IF NOT EXISTS idx_deliveries_user   ON lead_deliveries(telegram_id, state);
"""

# Колонки, добавленные в LeadHunter 2.0. Для уже существующих БД (Alembic здесь
# нет) добавляем их идемпотентно через ALTER TABLE. NOT NULL требует дефолта.
_MIGRATIONS: dict[str, str] = {
    "score": "INTEGER",
    "category": "TEXT NOT NULL DEFAULT ''",
    "reason": "TEXT NOT NULL DEFAULT ''",
    "probability_of_sale": "INTEGER",
    "should_send": "INTEGER",
    "crm_status": "TEXT NOT NULL DEFAULT 'new'",
    # LeadHunter 3.0: признаки заказа из общего AI-анализа (один раз на лид).
    "technology": "TEXT NOT NULL DEFAULT ''",
    "summary": "TEXT NOT NULL DEFAULT ''",
    # Валюта исходного бюджета; budget_value всегда нормализован в USD.
    "budget_currency": "TEXT NOT NULL DEFAULT 'USD'",
    # Дата публикации на бирже — по ней отсекаются устаревшие лиды.
    "published_at": "TEXT NOT NULL DEFAULT ''",
}

# Колонки users, добавленные после первого релиза мультиюзера.
_USER_MIGRATIONS: dict[str, str] = {
    # Момент нажатия «Запросить доступ»: пустая строка = заявки нет.
    "access_requested_at": "TEXT NOT NULL DEFAULT ''",
}


class Database:
    """Тонкая обёртка над одним соединением aiosqlite."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() не был вызван")
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._apply_pragmas()
        await self._conn.executescript(_SCHEMA)
        await self._conn.executescript(_USERS_SCHEMA)  # появляется и на старых БД
        await self._conn.executescript(_USER_SETTINGS_SCHEMA)
        await self._conn.executescript(_DELIVERIES_SCHEMA)
        await self._conn.executescript(_SOURCES_SETTINGS_SCHEMA)
        await self._migrate()  # добавляет недостающие колонки (в т.ч. crm_status)
        await self._conn.executescript(_INDEXES)  # индексы — уже по всем колонкам
        await self._conn.commit()
        log.info("SQLite подключена: %s", self._path)

    async def _apply_pragmas(self) -> None:
        """Режим работы SQLite под нагрузкой бота.

        WAL: читатели (хендлеры кнопок) не блокируют писателя (пайплайн) — без
        него нажатие в Telegram могло словить «database is locked» во время
        сохранения лида. busy_timeout добивает редкие пересечения ожиданием
        вместо ошибки. synchronous=NORMAL безопасен при WAL и заметно экономит
        обращения к диску VPS.
        """
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA busy_timeout=5000",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
        ):
            try:
                await self._connection.execute(pragma)
            except Exception as exc:  # noqa: BLE001 — на экзотической ФС WAL может быть недоступен
                log.warning("Не применился %s: %s", pragma, exc)

    async def _migrate(self) -> None:
        """Идемпотентно добавляет недостающие колонки в существующие таблицы."""
        await self._add_columns("orders", _MIGRATIONS)
        await self._add_columns("users", _USER_MIGRATIONS)
        await self._migrate_saved_leads()
        await self._migrate_sources()

    async def _add_columns(self, table: str, migrations: dict[str, str]) -> None:
        cur = await self._connection.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in await cur.fetchall()}
        for name, ddl in migrations.items():
            if name not in existing:
                await self._connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                )
                log.info("Миграция БД: %s.%s добавлена", table, name)

    async def _migrate_saved_leads(self) -> None:
        """Переносит избранное из saved_leads в lead_deliveries.

        До fan-out избранное лежало отдельной таблицей; теперь это состояние
        доставки. Старую таблицу не удаляем — на случай отката.
        """
        cur = await self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='saved_leads'"
        )
        if await cur.fetchone() is None:
            return

        cur = await self._connection.execute(
            """
            INSERT OR IGNORE INTO lead_deliveries
                (telegram_id, order_id, state, response, crm_status, created_at)
            SELECT telegram_id, order_id, 'saved', '', 'new', created_at
            FROM saved_leads
            """
        )
        if cur.rowcount:
            log.info("Миграция БД: перенесено избранное (%s шт.)", cur.rowcount)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def is_duplicate(self, source: str, external_id: str) -> bool:
        cur = await self._connection.execute(
            "SELECT 1 FROM orders WHERE source = ? AND external_id = ? LIMIT 1",
            (source, external_id),
        )
        return await cur.fetchone() is not None

    async def save_order(
        self,
        order: Order,
        response: str = "",
        status: str = "new",
        crm_status: str = CrmStatus.NEW,
    ) -> int | None:
        """Сохраняет заказ (с AI-оценкой). Возвращает id или ``None`` для дубликата."""
        should_send = (
            None if order.should_send is None else int(order.should_send)
        )
        cur = await self._connection.execute(
            """
            INSERT OR IGNORE INTO orders
                (source, external_id, title, url, description,
                 budget_raw, budget_value, budget_currency, published_at,
                 response, status,
                 score, category, reason, probability_of_sale,
                 should_send, technology, summary, crm_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.source,
                order.external_id,
                order.title,
                order.url,
                order.description,
                order.budget_raw,
                order.budget_value,
                order.budget_currency,
                order.published_at.isoformat() if order.published_at else "",
                response,
                status,
                order.score,
                order.category,
                order.reason,
                order.probability_of_sale,
                should_send,
                order.technology,
                order.summary,
                crm_status,
                order.created_at.isoformat(),
            ),
        )
        await self._connection.commit()
        # rowcount == 0 → сработал OR IGNORE (дубликат проскочил гонку).
        return cur.lastrowid if cur.rowcount else None

    async def get_order(self, order_id: int) -> aiosqlite.Row | None:
        cur = await self._connection.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        )
        return await cur.fetchone()

    async def set_status(self, order_id: int, status: str) -> None:
        await self._connection.execute(
            "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)
        )
        await self._connection.commit()

    async def set_crm_status(self, order_id: int, crm_status: str) -> None:
        """Обновляет статус воронки продаж (CRM) для заказа."""
        await self._connection.execute(
            "UPDATE orders SET crm_status = ? WHERE id = ?", (crm_status, order_id)
        )
        await self._connection.commit()

    # ------------------------------------------------------------------
    # Пользователи и доступ
    # ------------------------------------------------------------------

    async def register_user(self, telegram_id: int, username: str = "") -> None:
        """Регистрирует пользователя при первом контакте (/start).

        Уже выданный доступ НЕ сбрасывает: у существующей записи обновляется
        только username (в Telegram его можно сменить в любой момент).
        """
        await self._connection.execute(
            """
            INSERT INTO users (telegram_id, username, paid_status, created_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username
            """,
            (telegram_id, username, _utcnow_iso()),
        )
        await self._connection.commit()

    async def set_paid_status(
        self, telegram_id: int, paid: bool, username: str = ""
    ) -> None:
        """Выдаёт или отзывает доступ.

        Работает и для пользователя, которого ещё нет в базе (не нажимал /start):
        запись создаётся сразу с нужным статусом.
        """
        await self._connection.execute(
            """
            INSERT INTO users (telegram_id, username, paid_status, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET paid_status = excluded.paid_status
            """,
            (telegram_id, username, int(paid), _utcnow_iso()),
        )
        await self._connection.commit()

    async def has_paid_access(self, telegram_id: int) -> bool:
        cur = await self._connection.execute(
            "SELECT 1 FROM users WHERE telegram_id = ? AND paid_status = 1 LIMIT 1",
            (telegram_id,),
        )
        return await cur.fetchone() is not None

    async def get_user(self, telegram_id: int) -> aiosqlite.Row | None:
        cur = await self._connection.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return await cur.fetchone()

    async def list_users(
        self, limit: int = 100, offset: int = 0
    ) -> list[aiosqlite.Row]:
        """Страница списка пользователей: сначала с доступом, потом по дате.

        Постранично именно в SQL: раньше выбирались первые 50 и резались уже в
        Python, поэтому при большем числе пользователей остальные просто
        исчезали из админки — ими нельзя было управлять.
        """
        cur = await self._connection.execute(
            "SELECT * FROM users ORDER BY paid_status DESC, created_at ASC"
            " LIMIT ? OFFSET ?",
            (limit, max(0, offset)),
        )
        return list(await cur.fetchall())

    async def request_access(self, telegram_id: int, username: str = "") -> bool:
        """Фиксирует заявку на доступ.

        Returns:
            ``True`` — заявка новая; ``False`` — она уже висит (не спамим админа).
        """
        row = await self.get_user(telegram_id)
        if row is not None and row["access_requested_at"]:
            return False

        await self._connection.execute(
            """
            INSERT INTO users (telegram_id, username, paid_status, created_at,
                               access_requested_at)
            VALUES (?, ?, 0, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                access_requested_at = excluded.access_requested_at
            """,
            (telegram_id, username, _utcnow_iso(), _utcnow_iso()),
        )
        await self._connection.commit()
        return True

    async def clear_access_request(self, telegram_id: int) -> None:
        """Снимает заявку — после выдачи доступа или отказа."""
        await self._connection.execute(
            "UPDATE users SET access_requested_at = '' WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._connection.commit()

    async def list_access_requests(self, limit: int = 50) -> list[aiosqlite.Row]:
        """Незакрытые заявки от пользователей без доступа, старые сверху."""
        cur = await self._connection.execute(
            """
            SELECT * FROM users
            WHERE access_requested_at != '' AND paid_status = 0
            ORDER BY access_requested_at ASC LIMIT ?
            """,
            (limit,),
        )
        return list(await cur.fetchall())

    async def stats(self) -> dict[str, int]:
        """Сводка для админ-панели."""

        async def scalar(sql: str) -> int:
            cur = await self._connection.execute(sql)
            row = await cur.fetchone()
            return int(row[0] or 0) if row else 0

        return {
            "users_total": await scalar("SELECT COUNT(*) FROM users"),
            "users_paid": await scalar(
                "SELECT COUNT(*) FROM users WHERE paid_status = 1"
            ),
            "requests": await scalar(
                "SELECT COUNT(*) FROM users"
                " WHERE access_requested_at != '' AND paid_status = 0"
            ),
            "orders_total": await scalar("SELECT COUNT(*) FROM orders"),
            "orders_delivered": await scalar(
                "SELECT COUNT(*) FROM orders WHERE status = 'new'"
            ),
            "deliveries": await scalar("SELECT COUNT(*) FROM lead_deliveries"),
            "saved": await scalar(
                "SELECT COUNT(*) FROM lead_deliveries WHERE state = 'saved'"
            ),
        }

    async def user_stats(self, telegram_id: int) -> tuple[int, int]:
        """``(получено лидов, сохранено)`` — для панели пользователя."""
        cur = await self._connection.execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(state = 'saved'), 0) AS saved"
            " FROM lead_deliveries WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = await cur.fetchone()
        return (row["total"], row["saved"]) if row else (0, 0)

    async def count_users(self) -> tuple[int, int]:
        """Возвращает ``(всего, с доступом)``."""
        cur = await self._connection.execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(paid_status), 0) AS paid FROM users"
        )
        row = await cur.fetchone()
        return (row["total"], row["paid"]) if row else (0, 0)

    # ------------------------------------------------------------------
    # Персональные фильтры
    # ------------------------------------------------------------------

    async def get_user_settings(self, telegram_id: int) -> UserSettings:
        """Фильтры пользователя. Для незнакомого id — дефолтные (onboarded=False)."""
        cur = await self._connection.execute(
            "SELECT * FROM user_settings WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cur.fetchone()
        base = UserSettings() if row is None else _settings_from_row(row)
        # Источники живут в отдельной таблице — подставляем разрешённый список.
        return base.replace(
            sources=await self.get_enabled_sources(telegram_id), sources_explicit=True
        )

    async def save_user_settings(
        self, telegram_id: int, settings: UserSettings
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO user_settings
                (telegram_id, sources, categories, keywords, min_budget,
                 onboarded, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                sources    = excluded.sources,
                categories = excluded.categories,
                keywords   = excluded.keywords,
                min_budget = excluded.min_budget,
                onboarded  = excluded.onboarded,
                updated_at = excluded.updated_at
            """,
            (
                telegram_id,
                _pack(settings.sources),
                _pack(settings.categories),
                _pack(settings.keywords),
                settings.min_budget,
                int(settings.onboarded),
                _utcnow_iso(),
            ),
        )
        await self._connection.commit()

    # ------------------------------------------------------------------
    # Избранные лиды и подбор по фильтрам
    # ------------------------------------------------------------------

    async def mark_delivered(
        self, telegram_id: int, order_id: int, response: str = ""
    ) -> bool:
        """Фиксирует доставку лида пользователю.

        Returns:
            ``True`` — доставка новая; ``False`` — этот лид пользователь уже
            получал (дедупликация fan-out).
        """
        cur = await self._connection.execute(
            """
            INSERT OR IGNORE INTO lead_deliveries
                (telegram_id, order_id, state, response, crm_status, created_at)
            VALUES (?, ?, 'sent', ?, ?, ?)
            """,
            (telegram_id, order_id, response, CrmStatus.NEW, _utcnow_iso()),
        )
        await self._connection.commit()
        return bool(cur.rowcount)

    async def was_delivered(self, telegram_id: int, order_id: int) -> bool:
        cur = await self._connection.execute(
            "SELECT 1 FROM lead_deliveries WHERE telegram_id = ? AND order_id = ? LIMIT 1",
            (telegram_id, order_id),
        )
        return await cur.fetchone() is not None

    async def get_delivery(
        self, telegram_id: int, order_id: int
    ) -> aiosqlite.Row | None:
        cur = await self._connection.execute(
            "SELECT * FROM lead_deliveries WHERE telegram_id = ? AND order_id = ?",
            (telegram_id, order_id),
        )
        return await cur.fetchone()

    async def _upsert_delivery(self, telegram_id: int, order_id: int, **fields) -> None:
        """Меняет поля доставки, создавая строку, если её ещё нет."""
        columns = ", ".join(fields)
        assignments = ", ".join(f"{name} = excluded.{name}" for name in fields)
        placeholders = ", ".join("?" for _ in fields)
        await self._connection.execute(
            f"""
            INSERT INTO lead_deliveries
                (telegram_id, order_id, created_at, {columns})
            VALUES (?, ?, ?, {placeholders})
            ON CONFLICT(telegram_id, order_id) DO UPDATE SET {assignments}
            """,
            (telegram_id, order_id, _utcnow_iso(), *fields.values()),
        )
        await self._connection.commit()

    async def set_delivery_state(
        self, telegram_id: int, order_id: int, state: str
    ) -> None:
        """Личное состояние лида: ``sent`` / ``saved`` / ``rejected``."""
        await self._upsert_delivery(telegram_id, order_id, state=state)

    async def set_delivery_response(
        self, telegram_id: int, order_id: int, response: str
    ) -> None:
        """Личный черновик отклика — правка не задевает других получателей."""
        await self._upsert_delivery(telegram_id, order_id, response=response)

    async def set_delivery_crm(
        self, telegram_id: int, order_id: int, crm_status: str
    ) -> None:
        """Личный статус воронки: под fan-out он не может быть общим на заказ."""
        await self._upsert_delivery(telegram_id, order_id, crm_status=crm_status)

    async def list_leads_by_state(
        self, telegram_id: int, state: str, limit: int = 20
    ) -> list[aiosqlite.Row]:
        cur = await self._connection.execute(
            """
            SELECT o.* FROM lead_deliveries d
            JOIN orders o ON o.id = d.order_id
            WHERE d.telegram_id = ? AND d.state = ?
            ORDER BY d.created_at DESC
            LIMIT ?
            """,
            (telegram_id, state, limit),
        )
        return list(await cur.fetchall())

    # Избранное — частный случай состояния доставки (LeadHunter 2.x API).

    async def save_lead(self, telegram_id: int, order_id: int) -> None:
        await self.set_delivery_state(telegram_id, order_id, LeadState.SAVED)

    async def unsave_lead(self, telegram_id: int, order_id: int) -> None:
        await self.set_delivery_state(telegram_id, order_id, LeadState.SENT)

    async def is_lead_saved(self, telegram_id: int, order_id: int) -> bool:
        row = await self.get_delivery(telegram_id, order_id)
        return row is not None and row["state"] == LeadState.SAVED

    async def list_saved_leads(
        self, telegram_id: int, limit: int = 20
    ) -> list[aiosqlite.Row]:
        """Сохранённые лиды пользователя, свежие сверху."""
        return await self.list_leads_by_state(telegram_id, LeadState.SAVED, limit)

    async def list_recipients(self, owner_id: int = 0) -> list[tuple[int, UserSettings]]:
        """Получатели лидов вместе с фильтрами — ОДНИМ запросом.

        Раньше это было ``list_active_user_ids()`` плюс ``get_user_settings()``
        на каждого, то есть 1+N запросов НА КАЖДЫЙ лид: при 50 пользователях и
        25 лидах за опрос — больше тысячи обращений к базе на ровном месте.

        Владелец идёт первым и без дубля: его доступ не хранится в users, а
        фильтров у него обычно нет — дефолтные пропускают всё.
        """
        cur = await self._connection.execute(
            """
            SELECT u.telegram_id, s.sources, s.categories, s.keywords,
                   s.min_budget, s.onboarded
            FROM users u
            LEFT JOIN user_settings s ON s.telegram_id = u.telegram_id
            WHERE u.paid_status = 1
            ORDER BY u.telegram_id
            """
        )
        recipients = []
        for row in await cur.fetchall():
            settings = _settings_from_row(row)
            recipients.append((
                row["telegram_id"],
                settings.replace(
                    sources=await self.get_enabled_sources(row["telegram_id"]),
                    sources_explicit=True,
                ),
            ))

        if owner_id:
            others = [item for item in recipients if item[0] != owner_id]
            owner_settings = await self.get_user_settings(owner_id)
            recipients = [(owner_id, owner_settings), *others]
        return recipients

    # ------------------------------------------------------------------
    # Источники лидов, включённые пользователем
    # ------------------------------------------------------------------

    async def get_enabled_sources(self, telegram_id: int) -> tuple[str, ...]:
        """Какие биржи включены у пользователя.

        Явный выбор берётся из ``sources_settings``; для бирж, которых там нет,
        применяется ``default_enabled`` из реестра. Так новая площадка
        появляется у всех сама, а осознанно выключенная остаётся выключенной.
        """
        cur = await self._connection.execute(
            "SELECT source, enabled FROM sources_settings WHERE telegram_user_id = ?",
            (telegram_id,),
        )
        chosen = {row["source"]: bool(row["enabled"]) for row in await cur.fetchall()}

        return tuple(
            source.id
            for source in SOURCES
            if source.available and chosen.get(source.id, source.default_enabled)
        )

    async def sources_with_subscribers(self, owner_id: int = 0) -> set[str]:
        """Биржи, которые включил хотя бы один активный пользователь.

        Парсер процессный — один на биржу для всех. Поднимать его на каждого
        пользователя нельзя: при полусотне клиентов это полсотни одинаковых
        запросов к сайту и быстрый бан. Поэтому опрашиваем биржу, пока она
        нужна хоть кому-то, и не трогаем совсем, если её не выбрал никто.
        """
        recipients = [uid for uid, _ in await self.list_recipients(owner_id)]
        wanted: set[str] = set()
        for telegram_id in recipients:
            wanted.update(await self.get_enabled_sources(telegram_id))
        return wanted

    async def set_source_enabled(
        self, telegram_id: int, source: str, enabled: bool
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO sources_settings (telegram_user_id, source, enabled, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_user_id, source) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (telegram_id, source, int(enabled), _utcnow_iso()),
        )
        await self._connection.commit()

    async def toggle_source(self, telegram_id: int, source: str) -> bool:
        """Переключает биржу. Возвращает новое состояние."""
        enabled = source in await self.get_enabled_sources(telegram_id)
        await self.set_source_enabled(telegram_id, source, not enabled)
        return not enabled

    async def _migrate_sources(self) -> None:
        """Переносит выбор бирж из user_settings.sources в отдельную таблицу.

        Старый формат — CSV, где пустая строка означала «все включены».
        Переносим только непустой выбор: он был осознанным.

        Перенос — РОВНО ОДИН раз, поэтому legacy-колонка сразу очищается.
        Без этого миграция повторялась бы на каждом старте и гасила каждую
        новую биржу реестра: её нет в списке, записанном полгода назад, значит
        ей выставлялось enabled=0 — и биржа молча не работала у всех, кто
        обновился. Снимок выбора имеет смысл только на момент переезда.
        """
        cur = await self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_settings'"
        )
        if await cur.fetchone() is None:
            return

        cur = await self._connection.execute(
            "SELECT telegram_id, sources FROM user_settings WHERE sources != ''"
        )
        rows = list(await cur.fetchall())
        if not rows:
            return

        moved = 0
        for row in rows:
            picked = set(_unpack(row["sources"]))
            for source in SOURCES:
                if not source.available:
                    continue
                cur = await self._connection.execute(
                    """
                    INSERT OR IGNORE INTO sources_settings
                        (telegram_user_id, source, enabled, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (row["telegram_id"], source.id, int(source.id in picked), _utcnow_iso()),
                )
                moved += cur.rowcount

        await self._connection.execute("UPDATE user_settings SET sources = ''")
        await self._connection.commit()
        if moved:
            log.info(
                "Миграция БД: перенесён выбор бирж (%s записей, пользователей %s). "
                "Проверьте список в боте: ⚙️ Настройки → 🌐 Биржи",
                moved, len(rows),
            )

    async def list_active_user_ids(self) -> list[int]:
        """Кому рассылать лиды: все пользователи с доступом.

        Владелец (OWNER_ID) сюда не входит — его доступ не хранится в users,
        получателем он добавляется отдельно (см. ``main.recipients``).
        """
        cur = await self._connection.execute(
            "SELECT telegram_id FROM users WHERE paid_status = 1 ORDER BY telegram_id"
        )
        return [row["telegram_id"] for row in await cur.fetchall()]

    async def recent_orders(
        self, limit: int = 100, *, max_age_hours: int = 0
    ) -> list[aiosqlite.Row]:
        """Последние доставленные лиды — сырьё для «🔍 Проверить сейчас».

        Отсеянные пайплайном (rejected/filtered) не возвращаем: пользователь
        ждёт подходящие заказы, а не мусор.

        Args:
            max_age_hours: Отсечка по времени попадания в базу (0 = без неё).
                Слово «сейчас» на кнопке обещает свежие заказы, а не всё, что
                когда-либо накопилось: заказ недельной давности с биржи уже
                ушёл, и показывать его как подходящий — обман.
        """
        if max_age_hours > 0:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            ).isoformat()
            cur = await self._connection.execute(
                "SELECT * FROM orders WHERE status = 'new' AND created_at >= ?"
                " ORDER BY id DESC LIMIT ?",
                (cutoff, limit),
            )
        else:
            cur = await self._connection.execute(
                "SELECT * FROM orders WHERE status = 'new' ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return list(await cur.fetchall())
