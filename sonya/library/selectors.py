"""Pick grain / archetype / few-shot templates / persona-block from the library.

These are pure, deterministic selectors. They take a `TemplateLibrary` (or
default to the singleton) plus a small dict of context and return a slice
of the library suitable for prompt assembly.

Design notes:
- All selectors fall back gracefully when context is missing: a brand-new
  fan with no `fan_type` and no time hint still gets a sensible default
  grain (G7 friendly-clear, the master-rail S1 default).
- Few-shot retrieval is filter-then-rank: filter by hard predicates
  (fan_type / situation / stage / grain), rank by specificity, return up
  to N. We never invent or paraphrase template text — it's an opaque
  payload for the LLM prompt.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sonya.library.loader import LIBRARY, TemplateLibrary
from sonya.library.models import Archetype, Grain, Template

# Match a leading "G<digits>" token in window values like "G7+G4 (peak)" or
# "G10 only (reactive)" — we want the first grain id, ignoring any
# qualifier suffix.
_GRAIN_TOKEN_RE = re.compile(r"\bG\d+\b")

# Grain that the master rail uses by default for the welcome / first-contact
# stages — friendly-clear (G7). When nothing else is known about the fan we
# pick this rather than guessing.
DEFAULT_GRAIN_ID = "G7"
# Archetype A1 (Newcomer) is the default for fans without prior history.
DEFAULT_ARCHETYPE_ID = "A1"

# CRM-side `clients.current_stage` strings (welcome, warmup, …) → master
# rail stage ids in the library. The CRM model is coarser than the rail
# (15 stages vs 8 statuses); we collapse to the closest entry-point id.
_CRM_STAGE_TO_RAIL: dict[str, str] = {
    "welcome": "S1_WELCOME",
    "warmup": "S3_WARMUP_Q",
    "qualify": "S2_FIRST_CONTACT",
    "offer_pending": "S6_FIRST_PPV",
    "aftercare": "S7a_AFTERCARE_BOUGHT",
    "repeat_ready": "S10_REPEAT_CYCLE",
    "ghost": "S9_GHOST_NEW",
    "paused_safety": "S_LOST",
    "handoff": "S_LOST",
}


def crm_stage_to_rail_id(crm_stage: str | None) -> str | None:
    """Translate CRM `clients.current_stage` into the master rail's stage id.

    Returns `None` if the stage is unknown — callers should treat that as
    "no stage hint" rather than defaulting silently. The mapping is a
    best-effort bridge until rail state lives directly in the DB.
    """
    if not crm_stage:
        return None
    return _CRM_STAGE_TO_RAIL.get(crm_stage.strip().lower())


@dataclass(frozen=True, slots=True)
class FewShotBundle:
    """Result of `pick_few_shot`: an ordered list of (good, bad) pairs."""

    good: tuple[Template, ...]
    bad: tuple[Template, ...]


def _hour_in_window(hour: int, window: tuple[int, int]) -> bool:
    """True if `hour` (0..23) is within `(start, end)`, wrap-around aware.

    A normal window is `start < end` (e.g. 06..11). Windows that cross
    midnight have `start > end` (e.g. 23..01) and need OR-style matching.
    Equal start/end is treated as a single-hour bucket.
    """
    start, end = window
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def pick_grain(
    *,
    fan_local_hour: int | None = None,
    archetype: Archetype | None = None,
    library: TemplateLibrary = LIBRARY,
) -> Grain:
    """Pick the active grain for the current turn.

    Precedence (latest-tone wins):
    1. `active_window.windows_for_grain` lookup by the fan's local hour
       (the library's time-of-day tone, e.g. G1 mornings, G3 evenings,
       G10 late-night). If a window value is `Gx+Gy` (composite peak),
       the first grain wins — overlay-aware mixing comes in a later phase.
    2. `archetype.primary_grain` as a fan-specific fallback when we have
       no usable time signal (e.g. unknown timezone, hard-pause band 02-06).
    3. `DEFAULT_GRAIN_ID` (G7) when neither yields a hit.

    Rationale: time-of-day is universal context every fan shares, while
    archetype primary_grain encodes the fan's typical tone. We let the
    universal signal win when it's present so a whale's morning still
    sounds like a morning; specialized archetype overrides will land via
    an explicit override layer (overlays / stage rules) in a later phase.
    """
    if fan_local_hour is not None and 0 <= fan_local_hour < 24:
        for grain_str, window in library.active_window.windows_for_grain.items():
            if _hour_in_window(fan_local_hour, window):
                # Window values can be `G7+G4 (peak)` or `G10 only (reactive)`;
                # extract the first `Gnn` token rather than splitting on `+`
                # so qualifier suffixes don't poison the lookup.
                match = _GRAIN_TOKEN_RE.search(grain_str)
                if match is None:
                    continue
                hit = library.grains_by_id.get(match.group(0))
                if hit is not None:
                    return hit

    if archetype is not None and archetype.primary_grain:
        candidate = library.grains_by_id.get(archetype.primary_grain)
        if candidate is not None:
            return candidate

    return library.grains_by_id.get(DEFAULT_GRAIN_ID, library.grains[0])


# Map our existing CRM `fan_type` strings (regular, whale, freeloader,
# silent, etc.) to the closest archetype id. The library's archetypes are
# split across funnel_stage (A1-A5), economics (B1-B5), psychology (C1-C8),
# and request_type (D1+) groups; CRM's coarse taxonomy aligns best with
# the funnel + economics groups. Best-effort bridge until the behavioural
# classifier ships in a later phase.
_FAN_TYPE_TO_ARCHETYPE: dict[str, str] = {
    "regular": "A1",
    "newcomer": "A1",
    "subscriber": "A2",
    "mid_funnel": "A2",
    "returning": "A4",
    "repeat_buyer": "A5",
    "whale": "B1",
    "mid_spender": "B2",
    "spender": "B2",
    "supporter": "B2",
    "budget": "B3",
    "tipper": "B4",
    "free_loader": "B5",
    "freeloader": "B5",
    "lurker": "B5",
    "free_chatter": "B5",
    "silent": "A3",
    "ghost": "A3",
    "vip": "B1",
}


def pick_archetype_strict(
    *,
    fan_type: str | None = None,
    explicit_id: str | None = None,
    library: TemplateLibrary = LIBRARY,
) -> Archetype | None:
    """Return a confidently-classified archetype, or `None` when no signal matched.

    Use this when the caller needs to *know* whether an archetype came from
    real input (operator override / classifier) vs a default fallback. The
    archetype's `primary_grain` should only override time-of-day grain
    selection when the classification was confident.
    """
    if explicit_id and explicit_id in library.archetypes_by_id:
        return library.archetypes_by_id[explicit_id]

    if fan_type:
        mapped = _FAN_TYPE_TO_ARCHETYPE.get(fan_type.strip().lower())
        if mapped and mapped in library.archetypes_by_id:
            return library.archetypes_by_id[mapped]

    return None


def pick_archetype(
    *,
    fan_type: str | None = None,
    explicit_id: str | None = None,
    library: TemplateLibrary = LIBRARY,
) -> Archetype:
    """Look up an archetype by explicit id, then by CRM fan_type, else default.

    `explicit_id` wins when the orchestrator already classified the fan
    (e.g. via behavioural signals); otherwise we fall back to the CRM
    `fan_type` mapping. Unknown values quietly resolve to A1 (Newcomer).
    """
    confirmed = pick_archetype_strict(fan_type=fan_type, explicit_id=explicit_id, library=library)
    if confirmed is not None:
        return confirmed
    return library.archetypes_by_id.get(DEFAULT_ARCHETYPE_ID, library.archetypes[0])


def pick_few_shot(
    *,
    situation: str | None = None,
    stage_id: str | None = None,
    fan_type_id: str | None = None,
    grain_id: str | None = None,
    library: TemplateLibrary = LIBRARY,
    max_good: int = 5,
    max_bad: int = 2,
) -> FewShotBundle:
    """Filter templates by (situation OR stage) AND fan_type AND grain.

    Returns up to `max_good` good examples + up to `max_bad` bad foils. Templates
    that match more filters rank higher; ties broken by stable id order.
    Missing filters degrade gracefully — passing nothing returns a stable
    cross-section of the library so the prompt still has *some* anchor.
    """
    fan_norm = fan_type_id.strip() if fan_type_id else None
    situation_norm = situation.strip().lower() if situation else None
    stage_norm = stage_id.strip() if stage_id else None
    grain_norm = grain_id.strip() if grain_id else None

    has_any_filter = any(x is not None for x in (situation_norm, stage_norm, grain_norm, fan_norm))

    scored: list[tuple[int, Template]] = []
    for tpl in library.templates:
        score = 0
        if situation_norm and tpl.situation.lower() == situation_norm:
            score += 4
        if stage_norm and tpl.stage == stage_norm:
            score += 3
        if grain_norm and tpl.grain == grain_norm:
            score += 2

        # Fan-type matching: templates with an explicit fan_types list that
        # does NOT include the requested fan_type (and isn't "any") are a
        # hard mismatch — exclude them entirely.
        fan_match = True
        if fan_norm:
            if not tpl.fan_types or "any" in tpl.fan_types:
                score += 1
            elif fan_norm in tpl.fan_types:
                score += 1
            else:
                fan_match = False

        # Hard-filter: when filters are specified, exclude templates that
        # (a) scored zero on all soft dimensions, or (b) hard-mismatched fan_type.
        if has_any_filter and (not fan_match or score == 0):
            continue

        scored.append((score, tpl))

    # Stable sort: by score desc, then template id asc.
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))

    good: list[Template] = []
    for _score, tpl in scored:
        if len(good) >= max_good:
            break
        if tpl.good:
            good.append(tpl)

    bad: list[Template] = []
    for _score, tpl in scored:
        if len(bad) >= max_bad:
            break
        if tpl.bad:
            bad.append(tpl)

    return FewShotBundle(good=tuple(good), bad=tuple(bad))


def render_persona_block(
    *,
    grain: Grain,
    archetype: Archetype | None = None,
    stage_id: str | None = None,
    library: TemplateLibrary = LIBRARY,
) -> str:
    """Render a compact persona block for injection into the system prompt.

    Layout follows `runtime_recipe.step_by_step[8].structure` from the
    template library: STYLE / RULES_FOR_THIS_STAGE / STARTER_PHRASES.
    Stop-lists / meta-rules already live in the static prompt; we don't
    re-emit them here to avoid token bloat.
    """
    lines: list[str] = []

    lines.append(f"[STYLE] active grain: {grain.id} {grain.name}.")
    if grain.tone:
        lines.append(f"  tone: {grain.tone}")
    if grain.markers:
        lines.append("  markers: " + " | ".join(grain.markers[:5]))
    if grain.starter_phrases:
        lines.append("  starter phrases: " + " | ".join(grain.starter_phrases[:5]))
    if grain.anti_patterns:
        lines.append("  AVOID: " + " | ".join(grain.anti_patterns[:5]))

    if archetype is not None:
        lines.append("")
        lines.append(
            f"[ARCHETYPE] {archetype.id} {archetype.name}"
            + (f" — {archetype.signature}" if archetype.signature else "")
        )
        if archetype.rules:
            lines.append("  rules: " + " | ".join(archetype.rules[:5]))

    if stage_id:
        stage = library.stages_by_id.get(stage_id)
        if stage is not None:
            lines.append("")
            lines.append(f"[STAGE] {stage.id} — {stage.bot_action}")

    return "\n".join(lines)


def render_few_shot_block(bundle: FewShotBundle) -> str:
    """Format a `FewShotBundle` for inclusion in the system prompt.

    Each good example carries `why_good`; each bad carries `why_bad` so the
    LLM learns *why* a given line is on which side. We never echo the
    template id back to the model.
    """
    lines: list[str] = []
    if bundle.good:
        lines.append("[FEW_SHOT good]")
        for tpl in bundle.good:
            lines.append(f"  ✓ {tpl.good}")
            if tpl.why_good:
                lines.append(f"    why: {tpl.why_good}")
    if bundle.bad:
        if lines:
            lines.append("")
        lines.append("[FEW_SHOT bad — do NOT mimic]")
        for tpl in bundle.bad:
            lines.append(f"  ✗ {tpl.bad}")
            if tpl.why_bad:
                lines.append(f"    why bad: {tpl.why_bad}")
    return "\n".join(lines)


def starter_phrases_for_grain(
    grain_id: str, *, library: TemplateLibrary = LIBRARY
) -> Sequence[str]:
    """Return the JSON-vetted starter phrases for a grain, or `()` if none.

    Used by the prompt builder to seed `[STARTER_OPTIONS]` for the LLM. The
    JSON keys look like `G1_morning`; we accept both the bare id (`G1`) and
    the prefix form.
    """
    bank = library.stop_lists.approved_starter_phrases_by_grain
    if grain_id in bank:
        return bank[grain_id]
    for key, phrases in bank.items():
        if key.startswith(grain_id + "_") or key == grain_id:
            return phrases
    return ()


__all__ = [
    "DEFAULT_ARCHETYPE_ID",
    "DEFAULT_GRAIN_ID",
    "FewShotBundle",
    "pick_archetype",
    "pick_archetype_strict",
    "pick_few_shot",
    "pick_grain",
    "render_few_shot_block",
    "render_persona_block",
    "starter_phrases_for_grain",
]
