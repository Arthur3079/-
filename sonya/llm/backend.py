"""Backend-агностичный интерфейс для LLM-вызовов.

Хендлеры и оркестратор переписки работают через этот Protocol; конкретная
реализация (OpenAI-compat / Gemini / future Anthropic) скрыта внутри.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sonya.llm.client import ChatMessage


@runtime_checkable
class LLMBackend(Protocol):
    """Минимальный контракт для любого LLM-провайдера."""

    @property
    def model(self) -> str:
        """Имя модели для логов и аналитики."""

    @property
    def endpoint(self) -> str:
        """База URL / описание эндпоинта для логов."""

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        fan_id: int | None = None,
    ) -> str:
        """Сгенерировать текст ответа на сообщения. system-роль допустима."""

    async def aclose(self) -> None:
        """Закрыть базовый HTTP-клиент / соединения."""
