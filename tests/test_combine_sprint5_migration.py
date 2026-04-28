"""Migration smoke test for combine sprint 5 (reactions)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NEW_TABLES = {
    "combine_reaction_campaigns",
    "combine_reaction_targets",
    "combine_reactions",
}
SPRINT5_REVISION = "f1c2d4e5b6a7"
PARENT_REVISION = "e9b3f7d2a1c8"


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


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_combine_sprint5_migration_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_combine_sprint5.db"

        up = _alembic(["upgrade", SPRINT5_REVISION], db_path)
        assert up.returncode == 0, f"upgrade failed: {up.stderr}"
        tables = _table_names(db_path)
        missing = NEW_TABLES - tables
        assert not missing, f"missing tables after upgrade: {missing}"

        down = _alembic(["downgrade", PARENT_REVISION], db_path)
        assert down.returncode == 0, f"downgrade failed: {down.stderr}"
        leftover = NEW_TABLES & _table_names(db_path)
        assert not leftover, f"tables still present after downgrade: {leftover}"
        # Sprint 4 tables must still be there.
        assert "combine_commenting_campaigns" in _table_names(db_path)

        up2 = _alembic(["upgrade", SPRINT5_REVISION], db_path)
        assert up2.returncode == 0, f"second upgrade failed: {up2.stderr}"
