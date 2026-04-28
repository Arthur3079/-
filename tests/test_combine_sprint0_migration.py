"""Migration smoke test for combine sprint 0 (owners / accounts / proxies).

Mirrors ``test_layer1_migration.py``: upgrade → downgrade → upgrade round
trip on an isolated SQLite file, plus a check that the seed owner row is
inserted by the upgrade.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NEW_TABLES = {"owners", "combine_accounts", "combine_proxies"}


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


def test_combine_sprint0_migration_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_combine_sprint0.db"

        up = _alembic(["upgrade", "head"], db_path)
        assert up.returncode == 0, f"upgrade head failed: {up.stderr}"
        tables = _table_names(db_path)
        missing = NEW_TABLES - tables
        assert not missing, f"missing tables after upgrade: {missing}"

        # The migration seeds a single default owner.
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute("SELECT id, name FROM owners").fetchall()
        assert rows == [(1, "default")], f"expected one seeded owner, got {rows!r}"

        down = _alembic(["downgrade", "-1"], db_path)
        assert down.returncode == 0, f"downgrade -1 failed: {down.stderr}"
        tables_after_down = _table_names(db_path)
        leftover = NEW_TABLES & tables_after_down
        assert not leftover, f"tables still present after downgrade: {leftover}"

        up2 = _alembic(["upgrade", "head"], db_path)
        assert up2.returncode == 0, f"second upgrade failed: {up2.stderr}"
