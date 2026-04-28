"""Async-обёртка над OpenAI-совместимым chat completions API.

OpenRouter (по умолчанию), Anthropic, OpenAI, Together — всё это работает
через один и тот же `openai.AsyncOpenAI` при правильном `base_url`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, cast

from loguru import logger
from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from sonya.config import Settings
from sonya.llm.dump import dump_exchange, is_debug_enabled


class LLMNotConfigured(RuntimeError):
    """Поднимается если в .env не задан API-ключ для LLM."""


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


def build_llm_client(settings: Settings) -> AsyncOpenAI:
    """Создать AsyncOpenAI, направленный на любой OpenAI-совместимый эндпоинт.

    По умолчанию это OpenRouter, но можно подключить NVIDIA NIM, Groq,
    DeepSeek, Together AI и т.д. — просто меняешь `LLM_BASE_URL` и
    `LLM_MODEL` в `.env`.
    """
    api_key = settings.effective_llm_api_key
    if not api_key:
        raise LLMNotConfigured(
            "LLM_API_KEY не задан в .env. Бесплатные варианты: "
            "OpenRouter (https://openrouter.ai/keys), NVIDIA NIM "
            "(https://build.nvidia.com), Groq (https://console.groq.com/keys)."
        )

    # OpenRouter рекомендует слать referer/title для аналитики и более стабильного роутинга.
    return AsyncOpenAI(
        api_key=api_key,
        base_url=settings.llm_base_url,
        default_headers={
            "HTTP-Referer": "https://github.com/pvrmj88vmj-ops/AI-tg",
            "X-Title": "Sonya",
        },
        max_retries=2,
    )


async def complete_chat(
    client: AsyncOpenAI,
    *,
    settings: Settings,
    messages: list[ChatMessage],
    fan_id: int | None = None,
) -> str:
    """Сделать один вызов chat completions и вернуть текст ответа.

    Логирует размер промта, latency, потраченные токены. При `LOG_LEVEL=DEBUG`
    дополнительно сохраняет полный обмен в `logs/prompts/<timestamp>_fan<id>.md`.
    """
    payload = cast(
        list[ChatCompletionMessageParam],
        [{"role": m.role, "content": m.content} for m in messages],
    )

    role_counts: dict[str, int] = {}
    total_chars = 0
    for m in messages:
        role_counts[m.role] = role_counts.get(m.role, 0) + 1
        total_chars += len(m.content)
    logger.info(
        "→ LLM call: model={} msgs={} (system={} user={} assistant={}) chars={} max_out={} temp={}",
        settings.llm_model,
        len(messages),
        role_counts.get("system", 0),
        role_counts.get("user", 0),
        role_counts.get("assistant", 0),
        total_chars,
        settings.llm_max_tokens,
        settings.llm_temperature,
    )

    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            messages=payload,
        )
    except APIError as e:
        latency = time.perf_counter() - t0
        logger.error(
            "← LLM API error after {:.2f}s: status={} message={}",
            latency,
            getattr(e, "status_code", "?"),
            e,
        )
        raise

    latency = time.perf_counter() - t0

    if not resp.choices:
        logger.warning("← LLM вернул пустой choices ({:.2f}s): {}", latency, resp)
        return ""

    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
    finish_reason = getattr(resp.choices[0], "finish_reason", None)

    logger.info(
        "← LLM ok in {:.2f}s: tokens={}/{} finish={} reply_chars={}",
        latency,
        prompt_tokens,
        completion_tokens,
        finish_reason,
        len(text),
    )
    logger.info("← LLM reply: {!r}", text[:240] + ("…" if len(text) > 240 else ""))

    if is_debug_enabled(settings.log_level):
        path = dump_exchange(
            log_dir=settings.log_dir,
            fan_id=fan_id,
            model=settings.llm_model,
            messages=messages,
            response_text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_s=latency,
        )
        if path:
            logger.debug("Prompt dump → {}", path)

    return text
