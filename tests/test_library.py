"""Tests for `sonya.library` — loader, selectors, persona/few-shot rendering."""

from __future__ import annotations

import pytest

from sonya.library import LIBRARY, pick_archetype, pick_few_shot, pick_grain
from sonya.library.loader import load_library
from sonya.library.selectors import (
    DEFAULT_ARCHETYPE_ID,
    DEFAULT_GRAIN_ID,
    crm_stage_to_rail_id,
    render_few_shot_block,
    render_persona_block,
    starter_phrases_for_grain,
)


class TestLoader:
    def test_library_loaded_with_expected_shape(self) -> None:
        # Sanity: the bundled JSON parses and has roughly the expected counts.
        # If the JSON is replaced these counts will change; bump them in lockstep.
        assert len(LIBRARY.grains) == 12
        assert len(LIBRARY.archetypes) == 37
        assert len(LIBRARY.master_stages) >= 10
        assert len(LIBRARY.templates) >= 30

    def test_indexes_built(self) -> None:
        assert "G7" in LIBRARY.grains_by_id
        assert "A1" in LIBRARY.archetypes_by_id
        assert "S1_WELCOME" in LIBRARY.stages_by_id
        # Templates have human-friendly ids like "welcome.silent".
        assert any("." in tid for tid in LIBRARY.templates_by_id)

    def test_meta_rules_present(self) -> None:
        # The handoff describes 10 meta-rules MR1..MR10.
        ids = {r.id for r in LIBRARY.meta_rules}
        assert {"MR1", "MR2", "MR3"}.issubset(ids)

    def test_load_library_accepts_path(self, tmp_path) -> None:
        # Round-trip via custom path: shouldn't crash on the bundled JSON.
        bundled = tmp_path / "lib.json"
        from importlib import resources

        bundled.write_text(
            resources.files("sonya.library.data")
            .joinpath("template_library.json")
            .read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        copy = load_library(path=bundled)
        assert len(copy.grains) == len(LIBRARY.grains)


class TestPickGrain:
    def test_morning_window_returns_g1(self) -> None:
        # 06-11 fan local maps to G1 (warm morning).
        assert pick_grain(fan_local_hour=8).id == "G1"

    def test_evening_window_returns_g3(self) -> None:
        # 18-22:30 maps to "G3+G4 (peak)" → first wins → G3.
        assert pick_grain(fan_local_hour=20).id == "G3"

    def test_late_night_window_returns_g10(self) -> None:
        # 23-01 wraps midnight; G10 reactive only.
        assert pick_grain(fan_local_hour=23).id == "G10"
        assert pick_grain(fan_local_hour=0).id == "G10"

    def test_unknown_hour_uses_default(self) -> None:
        # 02:00 is in the hard-pause band; no window assigned → G7 default.
        assert pick_grain(fan_local_hour=2).id == DEFAULT_GRAIN_ID

    def test_no_hour_no_archetype_returns_default(self) -> None:
        assert pick_grain().id == DEFAULT_GRAIN_ID

    def test_time_of_day_wins_over_archetype_primary_grain(self) -> None:
        # B1 (Whale) has primary_grain=G6, but at 8AM the active-window says
        # G1 (warm morning). Time-of-day is the universal context; archetype
        # primary_grain is only the fallback when no hour is available.
        whale = LIBRARY.archetypes_by_id["B1"]
        assert pick_grain(fan_local_hour=8, archetype=whale).id == "G1"

    def test_archetype_primary_grain_used_when_hour_missing(self) -> None:
        # No hour signal — archetype primary_grain must take over.
        whale = LIBRARY.archetypes_by_id["B1"]
        assert pick_grain(archetype=whale).id == "G6"

    def test_archetype_primary_grain_used_when_hour_in_pause_band(self) -> None:
        # 02:00-05:00 has no active window assigned in the JSON. With an
        # archetype hint, fall through to primary_grain.
        whale = LIBRARY.archetypes_by_id["B1"]
        assert pick_grain(fan_local_hour=2, archetype=whale).id == "G6"

    def test_peak_window_includes_last_hour_with_non_zero_minutes(self) -> None:
        # The library has "18:00-22:30" → "G3+G4 (peak)". Hour 22 (i.e.
        # 22:00-22:59) must remain inside the peak window even though the
        # JSON end-time is 22:30. Regression for end-minute truncation bug.
        assert pick_grain(fan_local_hour=22).id == "G3"


class TestPickArchetype:
    def test_explicit_id_wins(self) -> None:
        assert pick_archetype(explicit_id="C1").id == "C1"

    def test_explicit_archetype_code_wins_over_coarse_label(self) -> None:
        # Mirrors how DialogueService calls it: fine-grained code from the DB
        # (`client.fan_type`) goes via `explicit_id`, coarse classifier label
        # via `fan_type`. The fine-grained code must take priority.
        assert pick_archetype(fan_type="newcomer", explicit_id="B1").id == "B1"

    def test_unknown_explicit_falls_back_to_fan_type(self) -> None:
        # Unknown explicit id → fall through to fan_type mapping.
        assert pick_archetype(explicit_id="ZZZ", fan_type="whale").id == "B1"

    def test_fan_type_whale_maps_to_b1(self) -> None:
        assert pick_archetype(fan_type="whale").id == "B1"

    def test_fan_type_freeloader_maps_to_b5(self) -> None:
        assert pick_archetype(fan_type="freeloader").id == "B5"

    def test_unknown_fan_type_returns_default(self) -> None:
        assert pick_archetype(fan_type="zzz_unknown").id == DEFAULT_ARCHETYPE_ID

    def test_no_args_returns_default(self) -> None:
        assert pick_archetype().id == DEFAULT_ARCHETYPE_ID

    def test_fan_type_case_insensitive(self) -> None:
        assert pick_archetype(fan_type="WHALE").id == "B1"


class TestPickFewShot:
    def test_returns_some_templates_with_no_filters(self) -> None:
        bundle = pick_few_shot()
        assert bundle.good
        assert all(t.good for t in bundle.good)

    def test_situation_filter_prefers_matching(self) -> None:
        bundle = pick_few_shot(situation="welcome", max_good=5)
        # Top results should all be welcome-situation templates.
        assert any(t.situation == "welcome" for t in bundle.good[:3])

    def test_stage_filter_prefers_matching(self) -> None:
        bundle = pick_few_shot(stage_id="S1_WELCOME", max_good=5)
        assert any(t.stage == "S1_WELCOME" for t in bundle.good[:3])

    def test_grain_filter_used(self) -> None:
        bundle = pick_few_shot(grain_id="G1", max_good=5)
        assert any(t.grain == "G1" for t in bundle.good[:3])

    def test_max_good_respected(self) -> None:
        bundle = pick_few_shot(max_good=2)
        assert len(bundle.good) <= 2

    def test_max_bad_respected(self) -> None:
        bundle = pick_few_shot(max_bad=1)
        assert len(bundle.bad) <= 1

    def test_zero_caps_return_empty(self) -> None:
        # Regression: previously the cap check ran AFTER append, so
        # `max_good=0` still produced 1 template.
        bundle = pick_few_shot(max_good=0, max_bad=0)
        assert bundle.good == ()
        assert bundle.bad == ()

    def test_universal_any_templates_score_with_fan_filter(self) -> None:
        """Regression: templates with `fan_types=("any",)` must rank with the
        +1 fan-type bonus when a fan filter is supplied; otherwise universal
        safety/aftercare foils get pushed off the bottom of the list."""
        # Without the `"any"` shortcut, scoring `fan_norm in tpl.fan_types` is
        # False for these templates. Pick a situation that we know is mostly
        # universal so the result is dominated by `any` templates.
        bundle = pick_few_shot(situation="aftercare", fan_type_id="A1", max_good=5, max_bad=0)
        assert any("any" in t.fan_types for t in bundle.good)

    def test_hard_filter_excludes_fan_type_mismatch(self) -> None:
        """Templates with explicit fan_types that don't include the requested
        fan should be excluded entirely (hard-filter), not just scored lower."""
        bundle = pick_few_shot(fan_type_id="B1", max_good=20, max_bad=20)
        for tpl in bundle.good + bundle.bad:
            assert not tpl.fan_types or "any" in tpl.fan_types or "B1" in tpl.fan_types

    def test_no_filters_still_returns_templates(self) -> None:
        """With zero filters the hard-filter is disabled; all templates are candidates."""
        bundle = pick_few_shot(max_good=10)
        assert len(bundle.good) > 0


class TestLibraryImmutability:
    def test_grains_by_id_is_immutable(self) -> None:
        import pytest

        with pytest.raises(TypeError):
            LIBRARY.grains_by_id["G99"] = LIBRARY.grains_by_id["G1"]  # type: ignore[index]

    def test_archetypes_by_id_is_immutable(self) -> None:
        import pytest

        with pytest.raises(TypeError):
            LIBRARY.archetypes_by_id["Z99"] = LIBRARY.archetypes_by_id["A1"]  # type: ignore[index]

    def test_stages_by_id_is_immutable(self) -> None:
        import pytest

        with pytest.raises(TypeError):
            LIBRARY.stages_by_id["X99"] = LIBRARY.stages_by_id["S1_WELCOME"]  # type: ignore[index]

    def test_templates_by_id_is_immutable(self) -> None:
        import pytest

        with pytest.raises(TypeError):
            first_key = next(iter(LIBRARY.templates_by_id))
            LIBRARY.templates_by_id["Z99"] = LIBRARY.templates_by_id[first_key]  # type: ignore[index]


class TestRenderPersonaBlock:
    def test_includes_grain_id_and_tone(self) -> None:
        g = LIBRARY.grains_by_id["G1"]
        rendered = render_persona_block(grain=g)
        assert "G1" in rendered
        assert g.tone in rendered

    def test_includes_archetype_when_provided(self) -> None:
        g = LIBRARY.grains_by_id["G6"]
        a = LIBRARY.archetypes_by_id["B1"]
        rendered = render_persona_block(grain=g, archetype=a)
        assert "B1" in rendered
        assert "Whale" in rendered

    def test_includes_stage_action_when_provided(self) -> None:
        g = LIBRARY.grains_by_id["G7"]
        rendered = render_persona_block(grain=g, stage_id="S1_WELCOME")
        assert "S1_WELCOME" in rendered

    def test_unknown_stage_id_silently_dropped(self) -> None:
        g = LIBRARY.grains_by_id["G7"]
        rendered = render_persona_block(grain=g, stage_id="DOES_NOT_EXIST")
        assert "DOES_NOT_EXIST" not in rendered


class TestRenderFewShotBlock:
    def test_renders_good_section_with_check_marks(self) -> None:
        bundle = pick_few_shot(situation="welcome", max_good=2, max_bad=0)
        block = render_few_shot_block(bundle)
        assert "FEW_SHOT good" in block
        assert "✓" in block

    def test_renders_bad_section_with_warnings(self) -> None:
        bundle = pick_few_shot(situation="welcome", max_good=0, max_bad=2)
        block = render_few_shot_block(bundle)
        assert "do NOT mimic" in block
        assert "✗" in block


class TestStarterPhrasesForGrain:
    @pytest.mark.parametrize("grain_id", ["G1", "G3", "G7", "G10"])
    def test_returns_non_empty_for_well_known_grains(self, grain_id: str) -> None:
        phrases = starter_phrases_for_grain(grain_id)
        assert len(phrases) > 0

    def test_returns_empty_for_unknown_grain(self) -> None:
        assert starter_phrases_for_grain("G99") == ()

    def test_custom_library_argument_is_honored(self) -> None:
        """Regression: previously read the global LIBRARY even when a `library=`
        kwarg was supplied. A custom fixture must shadow the global."""
        from dataclasses import replace

        from sonya.library.models import StopLists

        custom_stop_lists = replace(
            LIBRARY.stop_lists,
            approved_starter_phrases_by_grain={"G1": ("custom-fixture-phrase",)},
        )
        assert isinstance(custom_stop_lists, StopLists)
        custom = replace(LIBRARY, stop_lists=custom_stop_lists)
        assert starter_phrases_for_grain("G1", library=custom) == ("custom-fixture-phrase",)


class TestCrmStageMapping:
    @pytest.mark.parametrize(
        "crm_stage,expected",
        [
            ("welcome", "S1_WELCOME"),
            ("warmup", "S3_WARMUP_Q"),
            ("aftercare", "S7a_AFTERCARE_BOUGHT"),
            ("ghost", "S9_GHOST_NEW"),
            ("WELCOME", "S1_WELCOME"),  # case-insensitive
        ],
    )
    def test_known_stages_map(self, crm_stage: str, expected: str) -> None:
        assert crm_stage_to_rail_id(crm_stage) == expected

    def test_unknown_stage_returns_none(self) -> None:
        assert crm_stage_to_rail_id("not_a_stage") is None

    def test_none_returns_none(self) -> None:
        assert crm_stage_to_rail_id(None) is None

    def test_mapped_ids_exist_in_library(self) -> None:
        # Every mapped rail id must point at a real stage in the library.
        from sonya.library.selectors import _CRM_STAGE_TO_RAIL

        for rail_id in _CRM_STAGE_TO_RAIL.values():
            assert rail_id in LIBRARY.stages_by_id, rail_id
