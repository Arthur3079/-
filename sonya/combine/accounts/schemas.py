"""Pydantic schemas for the combine `accounts` and `proxies` REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sonya.db.models_combine import (
    AccountRole,
    AccountStatus,
    ProxyHealth,
    ProxyType,
)

# ---------- PROXY ----------


class ProxyIn(BaseModel):
    type: ProxyType
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    mtproto_secret: str | None = Field(default=None, max_length=128)
    note: str | None = None


class ProxyUpdate(BaseModel):
    type: ProxyType | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    mtproto_secret: str | None = Field(default=None, max_length=128)
    note: str | None = None


class ProxyOut(BaseModel):
    """Public proxy view — password is intentionally never returned."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    type: ProxyType
    host: str
    port: int
    username: str | None
    has_password: bool
    has_mtproto_secret: bool
    health: ProxyHealth
    last_checked_at: datetime | None
    latency_ms: int | None
    note: str | None


class ProxyHealthOut(BaseModel):
    id: int
    health: ProxyHealth
    latency_ms: int | None
    error: str | None = None


# ---------- ACCOUNT ----------


class AccountIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)
    role: AccountRole = AccountRole.MULTI
    proxy_id: int | None = None
    api_id: int | None = None
    api_hash: str | None = Field(default=None, max_length=64)
    note: str | None = None


class AccountUpdate(BaseModel):
    role: AccountRole | None = None
    proxy_id: int | None = None
    api_id: int | None = None
    api_hash: str | None = Field(default=None, max_length=64)
    note: str | None = None
    is_enabled: bool | None = None
    status: AccountStatus | None = None


class AccountOut(BaseModel):
    """Public account view — never exposes the session blob."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    proxy_id: int | None
    phone: str
    tg_user_id: int | None
    username: str | None
    first_name: str | None
    last_name: str | None
    api_id: int | None
    has_session: bool
    status: AccountStatus
    role: AccountRole
    trust_score: int
    last_active_at: datetime | None
    spam_block_until: datetime | None
    flood_until: datetime | None
    note: str | None
    is_enabled: bool


# ---------- LOGIN FLOW ----------


class LoginStartIn(BaseModel):
    """Optional override of the credentials stored on the account row.

    If both `api_id`/`api_hash` are omitted, we use the values already stored
    on `combine_accounts`. If those are also empty, we fall back to
    `Settings.telegram_api_id` / `telegram_api_hash`.
    """

    api_id: int | None = None
    api_hash: str | None = None


class LoginStartOut(BaseModel):
    login_token: str
    """Opaque handle used to continue the flow with /login/code (and later /login/password)."""
    expires_at: datetime


class LoginCodeIn(BaseModel):
    login_token: str
    code: str = Field(min_length=1, max_length=16)


class LoginCodeOut(BaseModel):
    status: str
    """`done` (logged in) or `password_required` (2FA enabled — call /login/password)."""
    account: AccountOut | None = None


class LoginPasswordIn(BaseModel):
    login_token: str
    password: str = Field(min_length=1, max_length=512)


class LoginPasswordOut(BaseModel):
    status: str  # always "done" on success
    account: AccountOut


class SessionImportIn(BaseModel):
    """Import an already-authorised Telethon `StringSession` blob."""

    session: str = Field(min_length=1, description="Telethon StringSession.save() output")


class HealthCheckOut(BaseModel):
    id: int
    status: AccountStatus
    is_authorized: bool
    error: str | None = None
    tg_user_id: int | None = None
    username: str | None = None


__all__ = [
    "AccountIn",
    "AccountOut",
    "AccountUpdate",
    "HealthCheckOut",
    "LoginCodeIn",
    "LoginCodeOut",
    "LoginPasswordIn",
    "LoginPasswordOut",
    "LoginStartIn",
    "LoginStartOut",
    "ProxyHealthOut",
    "ProxyIn",
    "ProxyOut",
    "ProxyUpdate",
    "SessionImportIn",
]
