"""Migration smoke test for combine sprint 2 (warming jobs / actions).

Mirrors ``test_combine_sprint0_migration.py``: upgrade → downgrade → upgrade
round trip on an isolated SQLite file.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NEW_TABLES = {"combine_warming_jobs", "combine_warming_actions"}
SPRINT2_REVISION = "c2f9a8b6d4e7"
PARENT_REVISION = "b7e1c4f8a2d3"


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


def test_combine_sprint2_migration_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_combine_sprint2.db"

        up = _alembic(["upgrade", SPRINT2_REVISION], db_path)
        assert up.returncode == 0, f"upgrade to {SPRINT2_REVISION} failed: {up.stderr}"
        tables = _table_names(db_path)
        missing = NEW_TABLES - tables
        assert not missing, f"missing tables after upgrade: {missing}"

        down = _alembic(["downgrade", PARENT_REVISION], db_path)
        assert down.returncode == 0, f"downgrade failed: {down.stderr}"
        tables_after_down = _table_names(db_path)
        leftover = NEW_TABLES & tables_after_down
        assert not leftover, f"tables still present after downgrade: {leftover}"
        # Sprint 0 tables must still be there.
        assert "combine_accounts" in tables_after_down

        up2 = _alembic(["upgrade", SPRINT2_REVISION], db_path)
        assert up2.returncode == 0, f"second upgrade failed: {up2.stderr}"
