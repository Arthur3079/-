"""Глобальный конфиг приложения, читается из .env через pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Все runtime-настройки. Все поля имеют дефолты, чтобы запуск без .env
    падал на конкретной операции (отправка в Telegram, вызов LLM),
    а не на инициализации.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram userbot ---
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_phone: str | None = None
    telegram_session_name: str = "sonya"

    # --- Pay bot ---
    pay_bot_token: str | None = None
    pay_bot_username: str | None = None
    # Currency the payment bot uses. "XTR" = Telegram Stars (no provider token
    # required). Override only if you set up a third-party payment provider.
    pay_currency: str = "XTR"

    # --- Admin / operator ---
    # Telegram user IDs allowed to send /commands to the userbot. CSV in .env:
    # ADMIN_USER_IDS="111,222". Empty = no admin chat (default).
    admin_user_ids: list[int] = Field(default_factory=list)

    # --- LLM ---
    # Какой бэкенд использовать: 'openai_compat' (OpenRouter / NVIDIA NIM /
    # Groq / DeepSeek / Together / OpenAI / Polza) или 'gemini' (Google AI).
    llm_provider: str = "openai_compat"

    # Общие LLM-параметры (применяются к любому бэкенду).
    llm_max_tokens: int = 400
    llm_temperature: float = 0.85
    llm_history_limit: int = 12

    # --- OpenAI-compat (provider='openai_compat') ---
    llm_api_key: str | None = None
    # Back-compat alias: старые .env с OPENROUTER_API_KEY всё ещё работают.
    openrouter_api_key: str | None = None
    llm_base_url: str = "https://openrouter.ai/api/v1"
    # Hermes 3 405B (free) — uncensored, отлично подходит для OFM-флёрта.
    llm_model: str = "nousresearch/hermes-3-llama-3.1-405b:free"

    # --- Google Gemini (provider='gemini') ---
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3-flash-preview"
    # 'HIGH' / 'MEDIUM' / 'LOW' / None. None отключает thinking.
    gemini_thinking_level: str | None = None

    @property
    def effective_llm_api_key(self) -> str | None:
        """Resolve the API key, preferring the new neutral name."""
        return self.llm_api_key or self.openrouter_api_key

    # --- DB ---
    database_url: str = "sqlite+aiosqlite:///./sonya.db"

    # --- Logging ---
    log_level: str = "INFO"
    log_dir: Path = PROJECT_ROOT / "logs"

    # --- Behaviour ---
    default_language: str = "en"
    sonya_timezone: str = "Europe/Madrid"
    enable_humanizer: bool = True
    dry_run: bool = True

    # --- Runtime safety / orchestration ---
    # Quiet window (seconds) before we answer after the latest incoming PM.
    # Lets us collapse "hi", "you there?", "?" into a single reply.
    incoming_debounce_seconds: float = 3.0
    # Cap on how long we'll sleep on a Telegram FloodWait before giving up
    # on a single send (and dropping that reply).
    telegram_max_flood_wait_seconds: float = 120.0

    # --- Knowledge retrieval ---
    knowledge_max_snippets: int = 4
    knowledge_max_chars: int = 1800

    # --- Dialogue / humanizer ---
    # Max number of "bubbles" we split one LLM reply into. 1 = never split,
    # 2-3 = more human-feeling. Set to 1 if you want strictly one message.
    max_reply_bubbles: int = 2
    # Short pause between bubbles (seconds) so it doesn't look like a bot
    # spamming. Awareness/typing delays still apply per bubble.
    inter_bubble_delay_seconds: float = 0.6

    # --- Paths ---
    project_root: Path = Field(default=PROJECT_ROOT, exclude=True)
    knowledge_dir: Path = Field(default=PROJECT_ROOT / "knowledge", exclude=True)

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _parse_admin_user_ids(cls, value: object) -> object:
        """Accept CSV strings from .env (e.g. ADMIN_USER_IDS=111,222,333)."""
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return []
            return [int(p.strip()) for p in v.split(",") if p.strip()]
        return value

    @model_validator(mode="before")
    @classmethod
    def _drop_blank_env_values(cls, data: object) -> object:
        """Treat empty/whitespace strings in env as missing keys.

        pydantic-settings reads `KEY=` from .env as an empty string, which then
        fails parsing on Optional[int] and on plain `str` fields whose default
        is non-empty. We drop blank values entirely so pydantic falls back to
        the declared field default (None for Optional, the literal default for
        the rest).
        """
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not (isinstance(v, str) and v.strip() == "")}
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кэшированный синглтон. Юзается везде через `from sonya.config import get_settings`."""
    return Settings()
