"""Regression test: ``scripts.run_worker._build_runner`` registers every
combine plugin, in a stable order, without triggering any network or
Telegram-side effects.

The test deliberately avoids ``runner.run_forever()`` / ``runner.run()``
so CI never has to deal with a real polling loop or real Telethon
clients. It only inspects ``registry.names``.
"""

from __future__ import annotations

from scripts.run_worker import _build_runner


def test_build_runner_registers_all_four_plugins() -> None:
    runner = _build_runner()

    assert runner.registry.names == [
        "parser",
        "commenting",
        "reactions",
        "warming",
    ]
