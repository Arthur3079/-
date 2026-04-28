"""Дамп полных промтов и ответов LLM в файл — для отладки.

Включается автоматически когда `LOG_LEVEL=DEBUG`. Создаёт по файлу на каждый
LLM-вызов в `logs/prompts/`. Это даёт возможность глазами посмотреть что
именно Соня видит и что отвечает (без необходимости лазить по коду).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from sonya.llm.client import ChatMessage


def is_debug_enabled(log_level: str) -> bool:
    return log_level.upper() == "DEBUG"


def dump_exchange(
    *,
    log_dir: Path,
    fan_id: int | None,
    model: str,
    messages: list[ChatMessage],
    response_text: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_s: float,
) -> Path | None:
    """Записать в файл полный обмен (system + history + reply)."""
    try:
        prompts_dir = log_dir / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        fan_part = f"fan{fan_id}" if fan_id else "unknown"
        path = prompts_dir / f"{ts}_{fan_part}.md"

        lines: list[str] = [
            f"# LLM exchange @ {ts}",
            f"- fan_id: `{fan_id}`",
            f"- model: `{model}`",
            f"- prompt_tokens: `{prompt_tokens}`",
            f"- completion_tokens: `{completion_tokens}`",
            f"- latency_s: `{latency_s:.2f}`",
            "",
            "---",
            "",
        ]
        for i, m in enumerate(messages):
            lines.append(f"## [{i}] {m.role}")
            lines.append("")
            lines.append("```")
            lines.append(m.content)
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## reply")
        lines.append("")
        lines.append("```")
        lines.append(response_text)
        lines.append("```")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    except Exception as e:
        logger.warning("Не удалось записать prompt-дамп: {}", e)
        return None
