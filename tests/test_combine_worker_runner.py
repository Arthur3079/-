"""Unit tests for the worker runner / plugin registry / WorkerContext."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from sonya.combine.worker import (
    PluginRegistry,
    WorkerContext,
    WorkerRunner,
)
from sonya.combine.worker.plugin import WorkerPlugin


class _FakePlugin:
    """Plugin that does ``n`` units of work then idles forever."""

    def __init__(
        self,
        name: str,
        *,
        work_left: int = 0,
        on_step: Callable[[], None] | None = None,
        raises: BaseException | None = None,
    ) -> None:
        self.name = name
        self._work_left = work_left
        self._on_step = on_step
        self._raises = raises
        self.calls = 0

    async def step(self, ctx: WorkerContext) -> bool:
        self.calls += 1
        if self._on_step is not None:
            self._on_step()
        if self._raises is not None:
            exc, self._raises = self._raises, None
            raise exc
        if self._work_left > 0:
            self._work_left -= 1
            return True
        return False


def _ctx() -> WorkerContext:
    """Build a WorkerContext that's safe to inspect but never used."""

    # The runner doesn't touch any of these — plugins do, and our fake
    # plugins ignore the context. ``object()`` keeps Pyright happy.
    return WorkerContext(
        session_factory=object(),  # type: ignore[arg-type]
        telethon_factory=object(),  # type: ignore[arg-type]
        rate_limiter=object(),  # type: ignore[arg-type]
    )


# ----------------------- registry -----------------------


def test_registry_preserves_registration_order() -> None:
    a, b, c = _FakePlugin("a"), _FakePlugin("b"), _FakePlugin("c")
    reg = PluginRegistry([a, b])
    reg.register(c)
    assert reg.names == ["a", "b", "c"]
    assert list(reg) == [a, b, c]
    assert len(reg) == 3
    assert reg.get("b") is b


def test_registry_rejects_duplicate_names() -> None:
    reg = PluginRegistry()
    reg.register(_FakePlugin("a"))
    with pytest.raises(ValueError):
        reg.register(_FakePlugin("a"))


def test_registry_unregister_removes_plugin() -> None:
    a, b = _FakePlugin("a"), _FakePlugin("b")
    reg = PluginRegistry([a, b])
    reg.unregister("a")
    assert reg.names == ["b"]
    with pytest.raises(KeyError):
        reg.unregister("missing")


# ----------------------- runner: run_once -----------------------


@pytest.mark.asyncio
async def test_run_once_calls_every_plugin_in_order() -> None:
    a, b = _FakePlugin("a", work_left=1), _FakePlugin("b", work_left=1)
    runner = WorkerRunner(registry=PluginRegistry([a, b]), ctx=_ctx())

    report = await runner.run_once()
    assert report.did_work == 2
    assert a.calls == 1
    assert b.calls == 1
    assert report.errors == []


@pytest.mark.asyncio
async def test_run_once_skips_plugins_that_idle() -> None:
    a = _FakePlugin("a", work_left=0)
    b = _FakePlugin("b", work_left=2)
    runner = WorkerRunner(registry=PluginRegistry([a, b]), ctx=_ctx())

    first = await runner.run_once()
    second = await runner.run_once()
    assert first.did_work == 1
    assert second.did_work == 1
    assert a.calls == 2
    assert b.calls == 2


@pytest.mark.asyncio
async def test_run_once_isolates_plugin_errors() -> None:
    boom = RuntimeError("bad")
    a = _FakePlugin("a", raises=boom, work_left=1)  # raises on first tick only
    b = _FakePlugin("b", work_left=1)
    runner = WorkerRunner(registry=PluginRegistry([a, b]), ctx=_ctx())

    report = await runner.run_once()
    assert report.errors == [("a", boom)]
    assert report.did_work == 1  # b still ran
    assert a.calls == 1
    assert b.calls == 1

    # Next tick: a clears (raises is consumed) and now does work_left=1.
    second = await runner.run_once()
    assert second.errors == []
    assert second.did_work == 1


@pytest.mark.asyncio
async def test_run_once_propagates_cancellation() -> None:
    a = _FakePlugin("a", raises=asyncio.CancelledError())
    runner = WorkerRunner(registry=PluginRegistry([a]), ctx=_ctx())
    with pytest.raises(asyncio.CancelledError):
        await runner.run_once()


# ----------------------- runner: run_forever -----------------------


@pytest.mark.asyncio
async def test_run_forever_drains_then_stops_on_request() -> None:
    a = _FakePlugin("a", work_left=3)
    runner = WorkerRunner(
        registry=PluginRegistry([a]),
        ctx=_ctx(),
        # Tiny so the empty-tick wait is short if we somehow miss a stop.
        poll_interval=0.01,
    )

    async def stop_after_drain() -> None:
        # Wait until the plugin has nothing left, then ask the runner to stop.
        for _ in range(100):
            if a.calls >= 3:
                break
            await asyncio.sleep(0.005)
        runner.request_stop()

    await asyncio.gather(runner.run_forever(), stop_after_drain())
    assert a.calls >= 3
    assert runner.stop_requested


@pytest.mark.asyncio
async def test_run_forever_sleeps_between_empty_ticks() -> None:
    a = _FakePlugin("a", work_left=0)
    runner = WorkerRunner(
        registry=PluginRegistry([a]),
        ctx=_ctx(),
        poll_interval=0.05,
    )

    task = asyncio.create_task(runner.run_forever())
    await asyncio.sleep(0.12)  # ~2 empty ticks
    runner.request_stop()
    await task

    # If the runner hadn't slept between empty ticks, calls would be huge.
    assert 1 <= a.calls <= 5


@pytest.mark.asyncio
async def test_run_forever_with_zero_poll_interval_rejected() -> None:
    with pytest.raises(ValueError):
        WorkerRunner(registry=PluginRegistry(), ctx=_ctx(), poll_interval=0)


# ----------------------- Protocol structural typing -----------------------


def test_fake_plugin_satisfies_protocol() -> None:
    # ``runtime_checkable`` would require an extra decorator in plugin.py;
    # we just rely on the duck-typing the runner already uses. This test
    # documents the expected attribute surface.
    plugin: WorkerPlugin = _FakePlugin("a")  # type: ignore[assignment]
    assert plugin.name == "a"
    assert callable(plugin.step)
