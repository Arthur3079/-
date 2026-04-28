"""OpenAI-совместимый бэкенд: OpenRouter, NVIDIA NIM, Groq, DeepSeek, Together, OpenAI."""

from __future__ import annotations

from openai import AsyncOpenAI

from sonya.config import Settings
from sonya.llm.client import ChatMessage, build_llm_client, complete_chat


class OpenAICompatBackend:
    """Тонкая обёртка над `complete_chat` чтобы соответствовать `LLMBackend`."""

    def __init__(self, client: AsyncOpenAI, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAICompatBackend:
        client = build_llm_client(settings)
        return cls(client, settings)

    @property
    def model(self) -> str:
        return self._settings.llm_model

    @property
    def endpoint(self) -> str:
        return self._settings.llm_base_url

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        fan_id: int | None = None,
    ) -> str:
        return await complete_chat(
            self._client,
            settings=self._settings,
            messages=messages,
            fan_id=fan_id,
        )

    async def aclose(self) -> None:
        await self._client.close()
