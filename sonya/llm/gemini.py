"""Google Gemini backend через нативный SDK `google-genai`.

Зачем нативный SDK, а не OpenAI-compat endpoint Gemini:
- умеем выкручивать `safety_settings` для всех harm-категорий в `OFF`
  (через OpenAI-compat это невозможно). Для OFM-кейса критично.
- нативная поддержка `system_instruction` отдельно от messages.
- доступ к `usage_metadata` (token counts).

ВНИМАНИЕ: даже с safety=OFF сама модель Gemini обучена отказывать на явный
сексуальный контент. Если упрёшься в `RECITATION` / `SAFETY` — переключайся
на Hermes / Dolphin через OpenRouter (см. `LLM_PROVIDER=openai_compat`).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from sonya.config import Settings
from sonya.llm.client import ChatMessage, LLMNotConfigured
from sonya.llm.dump import dump_exchange, is_debug_enabled

if TYPE_CHECKING:
    from google.genai import Client


def _split_messages(
    messages: list[ChatMessage],
) -> tuple[str | None, list[ChatMessage]]:
    """Gemini хочет system-инструкцию отдельно от истории. Разделяем."""
    system_parts = [m.content for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    system_instruction = "\n\n".join(p for p in system_parts if p) or None
    return system_instruction, rest


def _to_gemini_contents(messages: list[ChatMessage]):  # type: ignore[no-untyped-def]
    """Конвертировать наш ChatMessage в Gemini `Content` с ролями user/model."""
    from google.genai import types

    out = []
    for m in messages:
        # Gemini: assistant → "model"; user → "user"; system уже отфильтрован.
        role = "model" if m.role == "assistant" else "user"
        out.append(types.Content(role=role, parts=[types.Part.from_text(text=m.content)]))
    return out


def _all_off_safety_settings():  # type: ignore[no-untyped-def]
    """Выкручиваем все доступные harm-категории в OFF, чтобы Gemini максимально
    не резал OFM-флёрт. Сама модель всё равно может отказать — это её training,
    не safety filter."""
    from google.genai import types

    relevant = [
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
    ]
    return [
        types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.OFF) for c in relevant
    ]


def build_gemini_client(settings: Settings) -> Client:
    from google.genai import Client

    api_key = settings.gemini_api_key
    if not api_key:
        raise LLMNotConfigured(
            "GEMINI_API_KEY не задан в .env. Получить ключ: https://aistudio.google.com/app/apikey"
        )
    return Client(api_key=api_key)


class GeminiBackend:
    """Бэкенд для Google Gemini.

    Поддерживает thinking (если модель поддерживает; конфигурируется через
    `GEMINI_THINKING_LEVEL` в .env), стандартные generate_content. Streaming
    не используется — хендлер всё равно собирает полный текст перед отправкой.
    """

    def __init__(self, client: Client, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    @classmethod
    def from_settings(cls, settings: Settings) -> GeminiBackend:
        client = build_gemini_client(settings)
        return cls(client, settings)

    @property
    def model(self) -> str:
        return self._settings.gemini_model

    @property
    def endpoint(self) -> str:
        return "https://generativelanguage.googleapis.com (native SDK)"

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        fan_id: int | None = None,
    ) -> str:
        from google.genai import types

        system_instruction, rest = _split_messages(messages)
        contents = _to_gemini_contents(rest)

        role_counts: dict[str, int] = {}
        total_chars = 0
        for m in messages:
            role_counts[m.role] = role_counts.get(m.role, 0) + 1
            total_chars += len(m.content)
        logger.info(
            "→ Gemini call: model={} msgs={} (system={} user={} assistant={}) "
            "chars={} max_out={} temp={}",
            self.model,
            len(messages),
            role_counts.get("system", 0),
            role_counts.get("user", 0),
            role_counts.get("assistant", 0),
            total_chars,
            self._settings.llm_max_tokens,
            self._settings.llm_temperature,
        )

        cfg_kwargs: dict[str, object] = {
            "temperature": self._settings.llm_temperature,
            "max_output_tokens": self._settings.llm_max_tokens,
            "safety_settings": _all_off_safety_settings(),
        }
        if system_instruction:
            cfg_kwargs["system_instruction"] = system_instruction
        if self._settings.gemini_thinking_level:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=self._settings.gemini_thinking_level,  # type: ignore[arg-type]
            )

        cfg = types.GenerateContentConfig(**cfg_kwargs)  # type: ignore[arg-type]

        t0 = time.perf_counter()
        # SDK имеет sync API; запускаем в треде, чтобы не блокировать event loop.
        import asyncio

        try:
            resp = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.model,
                contents=contents,
                config=cfg,
            )
        except Exception as e:
            latency = time.perf_counter() - t0
            logger.error(
                "← Gemini error after {:.2f}s: {}: {}",
                latency,
                type(e).__name__,
                e,
            )
            raise

        latency = time.perf_counter() - t0
        text = (resp.text or "").strip() if hasattr(resp, "text") else ""

        usage = getattr(resp, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None

        finish = None
        candidates = getattr(resp, "candidates", None) or []
        if candidates:
            finish = getattr(candidates[0], "finish_reason", None)
            finish = getattr(finish, "name", finish) if finish is not None else None

        logger.info(
            "← Gemini ok in {:.2f}s: tokens={}/{} finish={} reply_chars={}",
            latency,
            prompt_tokens,
            completion_tokens,
            finish,
            len(text),
        )
        if not text:
            block_reason = None
            pf = getattr(resp, "prompt_feedback", None)
            if pf is not None:
                block_reason = getattr(pf, "block_reason", None)
                block_reason = getattr(block_reason, "name", block_reason)
            logger.warning(
                "← Gemini вернул пустой ответ. finish={} prompt_feedback.block={} — "
                "вероятно safety filter сработал. Для OFM рекомендую "
                "LLM_PROVIDER=openai_compat (Hermes/Dolphin).",
                finish,
                block_reason,
            )
        else:
            logger.info(
                "← Gemini reply: {!r}",
                text[:240] + ("…" if len(text) > 240 else ""),
            )

        if is_debug_enabled(self._settings.log_level):
            path = dump_exchange(
                log_dir=self._settings.log_dir,
                fan_id=fan_id,
                model=self.model,
                messages=messages,
                response_text=text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_s=latency,
            )
            if path:
                logger.debug("Prompt dump → {}", path)

        return text

    async def aclose(self) -> None:
        # google-genai Client не требует явного close (HTTP-сессия управляется
        # внутри SDK), но метод оставляем для совместимости с протоколом.
        return None
