"""Настройка логирования через loguru. Зовётся один раз при старте."""

from __future__ import annotations

import sys

from loguru import logger

from sonya.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "<level>{level:<8}</level> "
            "<cyan>{name}:{line}</cyan> | <level>{message}</level>"
        ),
    )
    logger.add(
        settings.log_dir / "sonya.log",
        level=settings.log_level,
        rotation="20 MB",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
    )
