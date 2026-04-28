"""Load `data/template_library.json` into typed `TemplateLibrary` instances.

Loaded once at import time and exposed as a module-level `LIBRARY` constant.
Callers that need a fresh load (test fixtures, hot-reload) call
`load_library(path=...)` directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sonya.library.models import (
    ActiveWindow,
    Archetype,
    Grain,
    MetaRule,
    PresendCheck,
    Stage,
    StageTimer,
    StageTransition,
    StopLists,
    Template,
)


@dataclass(frozen=True, slots=True)
class TemplateLibrary:
    """Top-level container for one parsed `template_library.json`."""

    version: str
    language_default: str
    languages_supported: tuple[str, ...]
    meta_rules: tuple[MetaRule, ...]
    stop_lists: StopLists
    presend_checklist: tuple[PresendCheck, ...]
    grains: tuple[Grain, ...]
    archetypes: tuple[Archetype, ...]
    master_stages: tuple[Stage, ...]
    templates: tuple[Template, ...]
    active_window: ActiveWindow
    grains_by_id: MappingProxyType[str, Grain] = field(default_factory=lambda: MappingProxyType({}))
    archetypes_by_id: MappingProxyType[str, Archetype] = field(
        default_factory=lambda: MappingProxyType({})
    )
    stages_by_id: MappingProxyType[str, Stage] = field(default_factory=lambda: MappingProxyType({}))
    templates_by_id: MappingProxyType[str, Template] = field(
        default_factory=lambda: MappingProxyType({})
    )


def _parse_grain(raw: dict[str, Any]) -> Grain:
    return Grain(
        id=raw["id"],
        name=raw.get("name", ""),
        when=raw.get("when", ""),
        tone=raw.get("tone", ""),
        markers=tuple(raw.get("markers", ())),
        starter_phrases=tuple(raw.get("starter_phrases", ())),
        anti_patterns=tuple(raw.get("anti_patterns", ())),
        examples_good=tuple(raw.get("examples_good", ())),
        examples_bad=tuple(raw.get("examples_bad", ())),
    )


def _parse_archetype(raw: dict[str, Any]) -> Archetype:
    return Archetype(
        id=raw["id"],
        name=raw.get("name", ""),
        category=raw.get("category", ""),
        definition=raw.get("definition", ""),
        primary_grain=raw.get("primary_grain"),
        secondary_grain=raw.get("secondary_grain"),
        signature=raw.get("signature", ""),
        detection_signals=tuple(raw.get("detection_signals", ())),
        default_rail=raw.get("default_rail", "master"),
        default_overlay=raw.get("default_overlay"),
        rules=tuple(raw.get("rules", ())),
    )


def _parse_stage(raw: dict[str, Any]) -> Stage:
    transitions = tuple(
        StageTransition(
            event=t.get("event", ""),
            next=t.get("next", ""),
            flag=t.get("flag"),
            overlay_add=t.get("overlay_add"),
            rule=t.get("rule"),
        )
        for t in raw.get("transitions", ())
    )
    timers = tuple(
        StageTimer(
            after_h=float(t.get("after_h", 0.0)),
            action=t.get("action", ""),
            template_ref=t.get("template_ref"),
        )
        for t in raw.get("timers", ())
    )
    return Stage(
        id=raw["id"],
        description=raw.get("description", ""),
        bot_action=raw.get("bot_action", ""),
        default_grain=raw.get("default_grain"),
        transitions=transitions,
        timers=timers,
        template_refs=tuple(raw.get("template_refs", ())),
    )


def _parse_template(raw: dict[str, Any]) -> Template:
    return Template(
        id=raw["id"],
        situation=raw.get("situation", ""),
        stage=raw.get("stage", ""),
        fan_types=tuple(raw.get("fan_types", ())),
        grain=raw.get("grain", ""),
        tempo=raw.get("tempo", ""),
        good=raw.get("good", ""),
        bad=raw.get("bad", ""),
        why_good=raw.get("why_good", ""),
        why_bad=raw.get("why_bad", ""),
        violations_in_bad=tuple(raw.get("violations_in_bad", ())),
        source=raw.get("source", ""),
    )


def _parse_stop_lists(raw: dict[str, Any]) -> StopLists:
    forbidden_words: dict[str, tuple[str, ...]] = {
        cat: tuple(words) for cat, words in (raw.get("forbidden_words") or {}).items()
    }
    starters: dict[str, tuple[str, ...]] = {
        gid: tuple(phrases)
        for gid, phrases in (raw.get("approved_starter_phrases_by_grain") or {}).items()
    }
    return StopLists(
        forbidden_words=forbidden_words,
        forbidden_emojis=tuple(raw.get("forbidden_emojis") or ()),
        forbidden_emoji_patterns=tuple(raw.get("forbidden_emoji_patterns") or ()),
        allowed_emojis_default_zero=tuple(raw.get("allowed_emojis_default_zero") or ()),
        allowed_emoji_rules=tuple(raw.get("allowed_emoji_rules") or ()),
        forbidden_structures=tuple(raw.get("forbidden_structures") or ()),
        approved_starter_phrases_by_grain=starters,
    )


def _parse_active_window(raw: dict[str, Any]) -> ActiveWindow:
    """Convert "HH:MM-HH:MM" → grain map into (start_hour, end_hour) tuples.

    Hours are integers in fan-local 24h, comparison is `_hour_in_window` half-open
    `start <= hour < end`. To avoid silently dropping the last hour of a window
    that ends on a non-zero minute (e.g. "18:00-22:30" otherwise excludes
    22:00-22:59), we round the end-hour UP whenever the minute component is
    non-zero. End hours of 24 wrap to 0. Crosses-midnight ranges (e.g. 23-01)
    are emitted as-is and resolved by `pick_grain` with a wrap-aware compare.
    """
    raw_map: dict[str, str] = raw.get("windows_for_grain") or {}
    out: dict[str, tuple[int, int]] = {}
    for window_str, grain_id in raw_map.items():
        try:
            start_str, end_str = window_str.split("-", 1)
            start_parts = start_str.split(":", 1)
            end_parts = end_str.split(":", 1)
            start_hour = int(start_parts[0])
            end_hour = int(end_parts[0])
            end_minute = int(end_parts[1]) if len(end_parts) > 1 else 0
        except (ValueError, AttributeError):
            continue
        if end_minute > 0:
            end_hour = (end_hour + 1) % 24
        out[grain_id] = (start_hour, end_hour)
    return ActiveWindow(windows_for_grain=out)


def _build_indexes(library: TemplateLibrary) -> None:
    """Frozen dataclass workaround: object.__setattr__ for the index dicts.

    We could add a `__post_init__` for this, but `dataclass(slots=True)`
    + `frozen=True` makes that awkward; the explicit helper is clearer.
    """
    object.__setattr__(library, "grains_by_id", MappingProxyType({g.id: g for g in library.grains}))
    object.__setattr__(
        library, "archetypes_by_id", MappingProxyType({a.id: a for a in library.archetypes})
    )
    object.__setattr__(
        library, "stages_by_id", MappingProxyType({s.id: s for s in library.master_stages})
    )
    object.__setattr__(
        library, "templates_by_id", MappingProxyType({t.id: t for t in library.templates})
    )


def load_library(path: Path | str | None = None) -> TemplateLibrary:
    """Parse a `template_library.json` file into a `TemplateLibrary`.

    With `path=None`, loads the bundled library from the package data dir.
    Tests may pass `path=` to load a custom fixture.
    """
    if path is None:
        data_text = (
            resources.files("sonya.library.data")
            .joinpath("template_library.json")
            .read_text(encoding="utf-8")
        )
    else:
        data_text = Path(path).read_text(encoding="utf-8")
    raw = json.loads(data_text)

    meta = raw.get("meta") or {}
    library = TemplateLibrary(
        version=str(meta.get("version", "0.0.0")),
        language_default=str(meta.get("language_default", "ru")),
        languages_supported=tuple(meta.get("languages_supported") or ("ru", "en")),
        meta_rules=tuple(
            MetaRule(id=r["id"], rule=r.get("rule", "")) for r in raw.get("meta_rules") or ()
        ),
        stop_lists=_parse_stop_lists(raw.get("stop_lists") or {}),
        presend_checklist=tuple(
            PresendCheck(check=int(c.get("check", 0)), question=c.get("question", ""))
            for c in raw.get("presend_checklist") or ()
        ),
        grains=tuple(_parse_grain(g) for g in raw.get("grains") or ()),
        archetypes=tuple(_parse_archetype(a) for a in raw.get("archetypes") or ()),
        master_stages=tuple(
            _parse_stage(s) for s in (raw.get("rails") or {}).get("master", {}).get("stages") or ()
        ),
        templates=tuple(_parse_template(t) for t in raw.get("templates") or ()),
        active_window=_parse_active_window(raw.get("active_window") or {}),
    )
    _build_indexes(library)
    return library


# Loaded once at import time. Tests can reload via `load_library(path=...)`.
LIBRARY: TemplateLibrary = load_library()


__all__ = ["LIBRARY", "TemplateLibrary", "load_library"]
