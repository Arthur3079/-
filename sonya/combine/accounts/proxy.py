"""Translate our :class:`Proxy` ORM row into a tuple Telethon understands.

Telethon's ``TelegramClient`` takes a single ``proxy`` kwarg that accepts:

* a tuple ``(proxy_type, host, port)`` or
  ``(proxy_type, host, port, rdns, username, password)`` for SOCKS/HTTP
  (where ``proxy_type`` is a ``python-socks`` / ``pysocks`` constant), or
* a dict ``{"proxy_type": "mtproto", "addr": host, "port": port,
  "secret": hex}`` for MTProto proxies.

We keep the dependency on ``python-socks`` optional — the build tuple only
needs an integer that ``socks`` interprets as the type. Using plain ints here
avoids an import-time hard dependency on ``socks`` / ``python-socks`` so unit
tests can exercise this module without it installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sonya.db.models_combine import Proxy, ProxyType

# python-socks / PySocks numeric constants. Re-declared so this module has no
# import-time dependency on either library.
_SOCKS5 = 2
_HTTP = 3


@dataclass(frozen=True, slots=True)
class TelethonProxy:
    """Pre-built argument for ``TelegramClient(..., proxy=...)``.

    ``as_telethon_arg`` returns the raw value Telethon actually wants; the
    dataclass wrapper is purely for type-safety and testing.
    """

    value: tuple[int, str, int, bool, str | None, str | None] | dict[str, Any]

    def as_telethon_arg(
        self,
    ) -> tuple[int, str, int, bool, str | None, str | None] | dict[str, Any]:
        return self.value


def build_telethon_proxy(proxy: Proxy | None) -> TelethonProxy | None:
    """Convert a :class:`Proxy` row into the value Telethon expects, or None.

    ``None`` in ``None`` out — accounts without an assigned proxy connect
    directly. MTProto proxies return a dict; SOCKS5/HTTP return a 6-tuple.
    """

    if proxy is None:
        return None

    if proxy.type is ProxyType.MTPROTO:
        if not proxy.mtproto_secret:
            raise ValueError(f"proxy {proxy.id}: mtproto proxy requires mtproto_secret")
        return TelethonProxy(
            value={
                "proxy_type": "mtproto",
                "addr": proxy.host,
                "port": proxy.port,
                "secret": proxy.mtproto_secret,
            }
        )

    proxy_type = _SOCKS5 if proxy.type is ProxyType.SOCKS5 else _HTTP
    return TelethonProxy(
        value=(
            proxy_type,
            proxy.host,
            proxy.port,
            True,  # rdns — resolve hostnames through the proxy
            proxy.username,
            proxy.password,
        )
    )


__all__ = ["TelethonProxy", "build_telethon_proxy"]
