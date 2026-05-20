from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

import aiosqlite

from config import config


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id   INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    subscription  TEXT NOT NULL DEFAULT 'free',
    used_bytes    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    code          TEXT PRIMARY KEY,
    owner_id      INTEGER NOT NULL,
    file_name     TEXT NOT NULL,
    mime_type     TEXT,
    size_bytes    INTEGER NOT NULL,
    rubika_msg_id TEXT NOT NULL,
    rubika_peer   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES users (telegram_id)
);

CREATE INDEX IF NOT EXISTS idx_files_owner ON files (owner_id);
"""


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ----------------------------------------------------------------------
# Initialization
# ----------------------------------------------------------------------

async def init_db() -> None:
    """Create schema if it does not already exist. Idempotent."""
    async with aiosqlite.connect(config.db_path) as conn:
        await conn.executescript(_SCHEMA)
        await conn.commit()


# ----------------------------------------------------------------------
# Users
# ----------------------------------------------------------------------

async def get_or_create_user(
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> dict[str, Any]:
    """Return user row as dict; insert with defaults if missing."""
    async with aiosqlite.connect(config.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cur.fetchone()
        if row is None:
            await conn.execute(
                """
                INSERT INTO users (telegram_id, username, first_name,
                                   subscription, used_bytes, created_at)
                VALUES (?, ?, ?, 'free', 0, ?)
                """,
                (telegram_id, username, first_name, _utcnow_iso()),
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            row = await cur.fetchone()
        else:
            # Keep username / first_name fresh.
            await conn.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE telegram_id = ?",
                (username, first_name, telegram_id),
            )
            await conn.commit()
        return dict(row)


async def add_usage(telegram_id: int, delta_bytes: int) -> None:
    """Increment cumulative used_bytes for a user."""
    async with aiosqlite.connect(config.db_path) as conn:
        await conn.execute(
            "UPDATE users SET used_bytes = used_bytes + ? WHERE telegram_id = ?",
            (delta_bytes, telegram_id),
        )
        await conn.commit()


async def set_subscription(telegram_id: int, tier: str) -> None:
    """Set subscription tier ('free' or 'premium'). Resets nothing else."""
    if tier not in ("free", "premium"):
        raise ValueError("tier must be 'free' or 'premium'")
    async with aiosqlite.connect(config.db_path) as conn:
        await conn.execute(
            "UPDATE users SET subscription = ? WHERE telegram_id = ?",
            (tier, telegram_id),
        )
        await conn.commit()


# ----------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------

async def save_file_record(
    *,
    code: str,
    owner_id: int,
    file_name: str,
    mime_type: Optional[str],
    size_bytes: int,
    rubika_msg_id: str,
    rubika_peer: str,
) -> None:
    """Persist a file record after a successful Rubika upload."""
    async with aiosqlite.connect(config.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO files (code, owner_id, file_name, mime_type,
                               size_bytes, rubika_msg_id, rubika_peer, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                owner_id,
                file_name,
                mime_type,
                size_bytes,
                rubika_msg_id,
                rubika_peer,
                _utcnow_iso(),
            ),
        )
        await conn.commit()


async def get_file_by_code(code: str) -> Optional[dict[str, Any]]:
    """Return file row by UUID code, or None."""
    async with aiosqlite.connect(config.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM files WHERE code = ?", (code,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_user_files(telegram_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Return last N files uploaded by this user (most recent first)."""
    async with aiosqlite.connect(config.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            """
            SELECT code, file_name, size_bytes, created_at
            FROM files
            WHERE owner_id = ?
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
