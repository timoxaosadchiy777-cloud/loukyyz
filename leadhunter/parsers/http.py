"""Общий HTTP-клиент для парсеров бирж.

Один переиспользуемый ``httpx.AsyncClient`` на парсер: соединения держатся в
пуле, TLS-хендшейк не повторяется на каждом опросе. Ретраятся только временные
сбои (таймауты, сетевые ошибки, 5xx, 429) — на 403/404 повторять бессмысленно,
это сигнал о смене вёрстки или бане, и он должен всплыть сразу.
"""

from __future__ import annotations

import logging

import httpx

from core.retry import retry_async

log = logging.getLogger(__name__)

# Представляемся обычным браузером: голый httpx многие площадки режут.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Коды, при которых повтор осмыслен: сервер жив, но сейчас не отдаёт.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """Не удалось получить страницу — с человекочитаемой причиной."""


class HttpFetcher:
    """Тонкая обёртка над httpx с ретраями и общими заголовками."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        attempts: int = 3,
        base_delay: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        cookie: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._attempts = max(1, attempts)
        self._base_delay = base_delay
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            **(headers or {}),
        }
        if cookie:
            # Сессионная кука: часть площадок отдаёт заказы только залогиненным.
            self._headers["Cookie"] = cookie
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def authenticated(self) -> bool:
        return "Cookie" in self._headers

    def _ensure_client(self) -> httpx.AsyncClient:
        # Ленивое создание: клиент привязывается к текущему event loop, поэтому
        # его нельзя строить в __init__ (парсер может конструироваться до запуска).
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=self._headers,
                follow_redirects=True,
            )
        return self._client

    async def get_text(self, url: str, *, label: str = "fetch") -> str:
        """Возвращает тело страницы. Бросает :class:`FetchError` при неудаче."""

        async def _once() -> str:
            client = self._ensure_client()
            response = await client.get(url)
            if response.status_code in _RETRYABLE_STATUS:
                # Поднимаем как retryable — retry_async повторит с backoff.
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            if response.status_code >= 400:
                raise FetchError(
                    f"{url}: HTTP {response.status_code} — повтор не поможет"
                )
            return response.text

        try:
            return await retry_async(
                _once,
                attempts=self._attempts,
                base_delay=self._base_delay,
                exceptions=(httpx.HTTPError,),
                label=label,
            )
        except FetchError:
            raise
        except httpx.HTTPError as exc:
            raise FetchError(f"{url}: {type(exc).__name__}: {exc}") from exc

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
