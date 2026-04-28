"""Smoke test that the catalog parser handles the real `knowledge/content_catalog.md`."""

from __future__ import annotations

from pathlib import Path

import pytest

from sonya.sales.catalog_importer import parse_catalog


def test_real_catalog_parses_all_entries() -> None:
    path = Path(__file__).resolve().parent.parent / "knowledge" / "content_catalog.md"
    if not path.exists():
        pytest.skip("knowledge/content_catalog.md not present in this checkout")
    entries = parse_catalog(path.read_text(encoding="utf-8"))
    # The catalog ships with 47 sets at the time of writing.
    assert len(entries) >= 40
    assert all(e.code and e.name for e in entries)
    # Codes are unique.
    codes = [e.code for e in entries]
    assert len(set(codes)) == len(codes)
    # Most entries should have a usable price.
    priced = [e for e in entries if e.price_usd_low or e.price_usd_high]
    assert len(priced) >= len(entries) // 2
