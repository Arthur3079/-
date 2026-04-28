"""Sonya template library — runtime context for LLM prompting.

The library is a 123 KB JSON file (`data/template_library.json`) shipped
inside the repo. Loaded once at import time and exposed as immutable typed
models so callers can:

- pick the active **grain** (voice/tone bucket G1-G12) for the current
  fan + time of day,
- look up an **archetype** (A1-A37) by `fan_type` and detection signals,
- retrieve **few-shot templates** filtered by stage / situation / fan type /
  grain, ready to drop into the system prompt,
- read the **stop_lists** + **meta_rules** as a compact persona-prompt block.

This module deliberately exposes ONLY read APIs. The library itself is
versioned content that changes via PR, never at runtime.
"""

from sonya.library.loader import (
    LIBRARY,
    TemplateLibrary,
    load_library,
)
from sonya.library.models import (
    Archetype,
    Grain,
    Stage,
    Template,
)
from sonya.library.selectors import (
    pick_archetype,
    pick_few_shot,
    pick_grain,
    render_persona_block,
)

__all__ = [
    "Archetype",
    "Grain",
    "LIBRARY",
    "Stage",
    "Template",
    "TemplateLibrary",
    "load_library",
    "pick_archetype",
    "pick_few_shot",
    "pick_grain",
    "render_persona_block",
]
