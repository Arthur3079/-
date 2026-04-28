"""LLM-слой.

MVP-2: OpenAI-совместимый клиент (по умолчанию OpenRouter), минимальный
системный промт «Соня», оркестратор одного хода переписки.

MVP-2.6: добавлен альтернативный бэкенд Gemini (через google-genai SDK).
Выбор провайдера через `LLM_PROVIDER` в .env: `openai_compat` (default) или
`gemini`. Бэкенды реализуют общий `LLMBackend` Protocol.
"""

from sonya.config import Settings
from sonya.llm.backend import LLMBackend
from sonya.llm.client import (
    ChatMessage,
    LLMNotConfigured,
    build_llm_client,
    complete_chat,
)
from sonya.llm.conversation import generate_reply
from sonya.llm.prompts import build_system_prompt, render_client_card


def build_backend(settings: Settings) -> LLMBackend:
    """Фабрика бэкенда по конфигу. Поднимает `LLMNotConfigured` если ключ не задан."""
    provider = settings.llm_provider.lower()
    if provider == "gemini":
        from sonya.llm.gemini import GeminiBackend

        return GeminiBackend.from_settings(settings)
    if provider in ("openai_compat", "openai", "openrouter", "compat"):
        from sonya.llm.openai_backend import OpenAICompatBackend

        return OpenAICompatBackend.from_settings(settings)
    raise LLMNotConfigured(
        f"Неизвестный LLM_PROVIDER={settings.llm_provider!r}. "
        "Допустимые значения: 'openai_compat' (default), 'gemini'."
    )


__all__ = [
    "ChatMessage",
    "LLMBackend",
    "LLMNotConfigured",
    "build_backend",
    "build_llm_client",
    "build_system_prompt",
    "complete_chat",
    "generate_reply",
    "render_client_card",
]
