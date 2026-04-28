"""Tiny async wrapper around the Telegram Bot API for invoice + getUpdates.

We don't pull aiogram/python-telegram-bot for this — the surface area we need
is small (`sendInvoice`, `answerPreCheckoutQuery`, `getUpdates`,
`sendMessage`) and avoids introducing a 200-class framework just to talk to
six endpoints.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger


class BotApiError(RuntimeError):
    """Telegram returned `ok: false` or HTTP error."""

    def __init__(self, method: str, code: int, description: str) -> None:
        super().__init__(f"{method}: {code} {description}")
        self.method = method
        self.code = code
        self.description = description


class BotApi:
    """Minimal Bot API client. One process == one bot token."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        timeout: float = 30.0,
    ) -> None:
        if not token:
            raise ValueError("BotApi requires a non-empty bot token")
        self._base = f"{base_url.rstrip('/')}/bot{token}"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, **params: Any) -> Any:
        url = f"{self._base}/{method}"
        clean = {k: v for k, v in params.items() if v is not None}
        try:
            r = await self._client.post(url, json=clean)
        except httpx.HTTPError as e:
            logger.error("BotApi {} network error: {}", method, e)
            raise BotApiError(method, -1, str(e)) from e
        try:
            data = r.json()
        except ValueError as e:
            raise BotApiError(method, r.status_code, "non-JSON response") from e
        if not data.get("ok"):
            raise BotApiError(
                method,
                int(data.get("error_code", r.status_code)),
                str(data.get("description", "")),
            )
        return data.get("result")

    # ---- typed helpers ----

    async def send_invoice(
        self,
        *,
        chat_id: int,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: list[dict[str, Any]],
        provider_token: str = "",
    ) -> dict[str, Any]:
        """Stars: provider_token must be empty and currency must be "XTR"."""
        return await self.call(
            "sendInvoice",
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency=currency,
            prices=prices,
        )

    async def answer_pre_checkout_query(
        self,
        *,
        pre_checkout_query_id: str,
        ok: bool,
        error_message: str | None = None,
    ) -> bool:
        return await self.call(
            "answerPreCheckoutQuery",
            pre_checkout_query_id=pre_checkout_query_id,
            ok=ok,
            error_message=error_message,
        )

    async def send_message(self, *, chat_id: int, text: str) -> dict[str, Any]:
        return await self.call("sendMessage", chat_id=chat_id, text=text)

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 25,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return await self.call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=allowed_updates,
        )


async def long_poll(
    api: BotApi,
    *,
    on_update: Any,  # Callable[[dict], Awaitable[None]]
    allowed_updates: list[str] | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the long-polling loop. `on_update(update_dict)` is awaited per update.

    If `stop_event` is supplied, the loop returns cleanly when it's set.
    """
    offset: int | None = None
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            updates = await api.get_updates(
                offset=offset, timeout=25, allowed_updates=allowed_updates
            )
        except BotApiError as e:
            logger.warning("Bot API getUpdates failed: {}", e)
            await asyncio.sleep(2.0)
            continue
        for upd in updates:
            offset = int(upd["update_id"]) + 1
            try:
                await on_update(upd)
            except Exception:  # pragma: no cover - one bad update mustn't kill the loop
                logger.opt(exception=True).error("on_update crashed")
