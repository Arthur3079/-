"""In-memory plugin registry for the worker.

A registry preserves registration order so the runner always polls
plugins in a deterministic sequence — handy for tests and predictable
load patterns. Names must be unique; re-registering raises.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from sonya.combine.worker.plugin import WorkerPlugin


class PluginRegistry:
    """Ordered, by-name registry of :class:`WorkerPlugin`s."""

    def __init__(self, plugins: Iterable[WorkerPlugin] | None = None) -> None:
        self._plugins: dict[str, WorkerPlugin] = {}
        if plugins:
            for p in plugins:
                self.register(p)

    def register(self, plugin: WorkerPlugin) -> None:
        if plugin.name in self._plugins:
            raise ValueError(f"plugin {plugin.name!r} already registered")
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str) -> None:
        if name not in self._plugins:
            raise KeyError(name)
        del self._plugins[name]

    def get(self, name: str) -> WorkerPlugin:
        return self._plugins[name]

    def __iter__(self) -> Iterator[WorkerPlugin]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    @property
    def names(self) -> list[str]:
        return list(self._plugins)


__all__ = ["PluginRegistry"]
