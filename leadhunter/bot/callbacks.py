"""Фабрики callback-данных для инлайн-кнопок."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class OrderAction(CallbackData, prefix="ord"):
    """Действие над заказом (не меняющее воронку).

    action: ``"copy"`` — прислать чистый текст отклика для копирования/отправки.
    order_id: id заказа в БД.
    """

    action: str
    order_id: int


class CrmAction(CallbackData, prefix="crm"):
    """Смена статуса воронки продаж (CRM).

    status: целевой статус — см. :class:`core.models.CrmStatus`.
    order_id: id заказа в БД.
    """

    status: str
    order_id: int


# --- Мастер настройки и панель управления ---------------------------------

# Экран, с которого пришло нажатие: мастер онбординга или экран настроек.
# От него зависит, куда возвращаться после переключения фильтра.
CTX_WIZARD = "w"
CTX_SETTINGS = "s"


class MenuAction(CallbackData, prefix="mn"):
    """Кнопка главного меню.

    action: ``menu`` | ``settings`` | ``check`` | ``saved`` | ``sources``.
    """

    action: str


class WizardAction(CallbackData, prefix="wz"):
    """Навигация по мастеру онбординга.

    step: экран назначения — ``sources`` | ``categories`` | ``keywords``
        | ``budget`` | ``done`` | ``kw_input`` (запрос своих ключевых слов).
    ctx: откуда пришли — мастер или экран настроек.
    """

    step: str
    ctx: str


class ToggleAction(CallbackData, prefix="tg"):
    """Переключение одного пункта фильтра.

    kind: ``src`` (биржа, по id) | ``cat`` | ``kw`` (по ИНДЕКСУ в пресетах).
    value: id источника либо индекс в кортеже пресетов.
    ctx: :data:`CTX_WIZARD` или :data:`CTX_SETTINGS` — куда вернуться.

    Категории и ключевые слова передаются индексом, а не текстом: Telegram
    ограничивает callback_data 64 байтами, и кириллица в UTF-8 этот лимит
    пробивает.
    """

    kind: str
    value: str
    ctx: str


class BudgetAction(CallbackData, prefix="bg"):
    """Выбор минимального бюджета из пресетов.

    value: сумма в USD (0 = без ограничения).
    """

    value: int
    ctx: str


class EditAction(CallbackData, prefix="ed"):
    """Переход к редактированию одного фильтра из экрана настроек.

    field: ``sources`` | ``categories`` | ``keywords`` | ``budget``.
    """

    field: str


class HelpAction(CallbackData, prefix="hlp"):
    """Открыть справку."""

    action: str = "show"


# --- Доступ и админка -----------------------------------------------------


class AccessAction(CallbackData, prefix="ac"):
    """Заявка на доступ.

    action: ``request`` — нажал пользователь; ``grant`` / ``decline`` — решение
        администратора прямо из уведомления о заявке.
    user_id: кого касается решение (у ``request`` совпадает с нажавшим).
    """

    action: str
    user_id: int


class AdminAction(CallbackData, prefix="ad"):
    """Навигация по админ-панели.

    action: ``panel`` | ``users`` | ``requests`` | ``stats``.
    page: страница списка пользователей (по 0 для остальных экранов).
    """

    action: str
    page: int = 0


class UserAction(CallbackData, prefix="au"):
    """Переключение доступа конкретному пользователю из списка админки."""

    user_id: int
    grant: bool
    page: int = 0
