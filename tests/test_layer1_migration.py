"""Smoke test for the Layer 1 Alembic migration.

Verifies:
- `alembic upgrade head` succeeds on a fresh SQLite DB.
- `alembic downgrade -1` succeeds (round-trip safe).
- `alembic upgrade head` succeeds again after downgrade.
- New `clients` columns exist after upgrade and are gone after downgrade.

Run as a normal pytest test; uses a tempfile DB so it doesn't pollute
the dev environment.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

NEW_COLUMNS = {
    "current_stage",
    "risk_level",
    "last_inbound_at",
    "last_outbound_at",
    "consecutive_outbound_without_reply",
    "last_offer_at",
    "last_purchase_at",
    "suppression_until",
    "handoff_required",
}


def _alembic(args: list[str], db_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        ["alembic", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _client_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("PRAGMA table_info(clients)").fetchall()
    return {row[1] for row in rows}


def test_layer1_migration_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_layer1.db"

        up = _alembic(["upgrade", "head"], db_path)
        assert up.returncode == 0, f"upgrade head failed: {up.stderr}"
        cols_after_up = _client_columns(db_path)
        missing = NEW_COLUMNS - cols_after_up
        assert not missing, f"missing columns after upgrade: {missing}"

        # Downgrade past Layer 1 specifically (its revision id) rather than
        # relying on "-1" — that only rewinds the most recent migration and
        # breaks as soon as a later, unrelated revision is added.
        down = _alembic(["downgrade", "285d2e983578"], db_path)
        assert down.returncode == 0, f"downgrade failed: {down.stderr}"
        cols_after_down = _client_columns(db_path)
        leftover = NEW_COLUMNS & cols_after_down
        assert not leftover, f"columns still present after downgrade: {leftover}"

        up2 = _alembic(["upgrade", "head"], db_path)
        assert up2.returncode == 0, f"second upgrade failed: {up2.stderr}"


@pytest.mark.skipif(
    os.environ.get("SKIP_ALEMBIC_TESTS") == "1",
    reason="alembic CLI not available in this environment",
)
def test_layer1_migration_idempotent_at_head() -> None:
    """Running `upgrade head` twice in a row is a no-op (alembic's own
    behaviour, but worth pinning so we notice if a future migration
    accidentally regresses it)."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_layer1_idem.db"
        first = _alembic(["upgrade", "head"], db_path)
        assert first.returncode == 0
        second = _alembic(["upgrade", "head"], db_path)
        assert second.returncode == 0
