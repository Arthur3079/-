"""LLM-prompt-dump viewer.

Читает файлы из `logs/prompts/<timestamp>_fan<fan_id>.md` (формат, который
пишет `sonya.llm.dump.dump_exchange` при `LOG_LEVEL=DEBUG`).

Безопасно: только read-only доступ к файлам в `logs/prompts/`, валидируем,
что путь не выходит за её пределы.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from sonya.config import get_settings

router = APIRouter()


def _prompts_dir() -> Path:
    settings = get_settings()
    log_dir = getattr(settings, "log_dir", None) or Path("logs")
    return Path(log_dir) / "prompts"


def _parse_meta(name: str) -> dict[str, object]:
    """File name format: `YYYYMMDD_HHMMSS_NNNNNN_fan<id>.md` (or `unknown`)."""
    stem = Path(name).stem
    parts = stem.split("_")
    fan_id: int | None = None
    if parts and parts[-1].startswith("fan"):
        try:
            fan_id = int(parts[-1].removeprefix("fan"))
        except ValueError:
            fan_id = None
    ts: str | None = None
    if len(parts) >= 3:
        date_str, time_str = parts[0], parts[1]
        try:
            ts = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S").isoformat()
        except ValueError:
            ts = None
    return {"fan_id": fan_id, "timestamp": ts}


@router.get("/llm/dumps")
async def list_dumps(
    fan_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, object]:
    base = _prompts_dir()
    if not base.exists():
        return {"items": [], "dir": str(base), "exists": False}
    files = sorted(base.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    items: list[dict[str, object]] = []
    for f in files:
        meta = _parse_meta(f.name)
        if fan_id is not None and meta.get("fan_id") != fan_id:
            continue
        items.append(
            {
                "name": f.name,
                "size": f.stat().st_size,
                "fan_id": meta.get("fan_id"),
                "timestamp": meta.get("timestamp"),
            }
        )
        if len(items) >= limit:
            break
    return {"items": items, "dir": str(base), "exists": True}


@router.get("/llm/dumps/{name}")
async def get_dump(name: str) -> dict[str, object]:
    base = _prompts_dir().resolve()
    target = (base / name).resolve()
    if not str(target).startswith(str(base) + "/") and target != base:
        raise HTTPException(status_code=400, detail="path traversal")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"dump {name} not found")
    return {
        "name": name,
        "content": target.read_text(encoding="utf-8", errors="replace"),
        **_parse_meta(name),
    }
