
# ساختار پوشه
# tele2rub/
# ├── bot.py
# ├── rubika_client.py
# ├── db.py
# ├── utils.py
# ├── config.py
# ├── requirements.txt
# ├── .env.example
# └── README.md
# requirements.txt
# pyrogram>=2.0.106
# tgcrypto>=1.2.5
# rubpy>=7.0.0
# aiosqlite>=0.20.0
# python-dotenv>=1.0.1
# .env.example
# # -------- Telegram --------
# # Obtain API_ID / API_HASH from https://my.telegram.org -> API development tools
# TELEGRAM_API_ID=
# TELEGRAM_API_HASH=
# # Obtain BOT_TOKEN from @BotFather
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_SESSION_NAME=tele2rub_bot

# # -------- Rubika --------
# # rubpy session file name (created on first run, after interactive phone+OTP login)
# RUBIKA_SESSION=rubpy
# # Where uploads land on Rubika.
# #   "me"  -> Saved Messages of the logged-in account (recommended)
# #   "c0..." -> a private channel guid
# RUBIKA_TARGET_PEER=me

# # -------- Storage / Database --------
# DB_PATH=tele2rub.db

# # -------- Subscription limits (bytes) --------
# FREE_SINGLE_FILE_BYTES=104857600       # 100 MB
# FREE_TOTAL_QUOTA_BYTES=524288000       # 500 MB
# PREMIUM_SINGLE_FILE_BYTES=1073741824   # 1 GB
# PREMIUM_TOTAL_QUOTA_BYTES=10737418240  # 10 GB

# # -------- Admin / misc --------
# # Comma-separated Telegram numeric user IDs that can run /upgrade
# ADMIN_IDS=
# LOG_LEVEL=INFO
# config.py
# """
# config.py
# ---------
# Centralized configuration loader.

# All credentials, API keys, paths and subscription limits are loaded from
# environment variables (with sane defaults). A `.env` file in the project
# root is auto-loaded via python-dotenv if present.

# This module is intentionally side-effect free except for reading env vars,
# so it can be imported safely anywhere in the project.
# """

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (file beside this config.py)
BASE_DIR: Path = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_int(key: str, default: int) -> int:
    """Read an int env var safely."""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram-related credentials (obtained at https://my.telegram.org)."""
    api_id: int = _get_int("TELEGRAM_API_ID", 0)
    api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    # Pyrogram session name (stored as <session>.session next to bot.py)
    session_name: str = os.getenv("TELEGRAM_SESSION_NAME", "tele2rub_bot")


@dataclass(frozen=True)
class RubikaConfig:
    """Rubika account configuration.

    `session_name` -> rubpy will create `<session_name>.rbs` (or similar) on
    first login (interactive: phone + OTP).
    `target_peer`  -> where files are uploaded on Rubika. Use "me" to upload
                      into the logged-in account's Saved Messages, or a
                      private channel guid like 'c0xxxxxxxxxxxxxxxxxxxxxxxx'.
    """
    session_name: str = os.getenv("RUBIKA_SESSION", "rubpy")
    target_peer: str = os.getenv("RUBIKA_TARGET_PEER", "me")


@dataclass(frozen=True)
class SubscriptionConfig:
    """Per-tier limits, in bytes."""
    # Free tier
    free_single_file_bytes: int = _get_int("FREE_SINGLE_FILE_BYTES", 100 * 1024 * 1024)        # 100 MB
    free_total_quota_bytes: int = _get_int("FREE_TOTAL_QUOTA_BYTES", 500 * 1024 * 1024)        # 500 MB

    # Premium tier
    premium_single_file_bytes: int = _get_int("PREMIUM_SINGLE_FILE_BYTES", 1024 * 1024 * 1024) # 1 GB
    premium_total_quota_bytes: int = _get_int("PREMIUM_TOTAL_QUOTA_BYTES", 10 * 1024 * 1024 * 1024)  # 10 GB


@dataclass(frozen=True)
class AppConfig:
    """Top-level immutable configuration."""
    telegram: TelegramConfig = TelegramConfig()
    rubika: RubikaConfig = RubikaConfig()
    subscription: SubscriptionConfig = SubscriptionConfig()

    # SQLite database file (lives next to source). Override via env if needed.
    db_path: str = os.getenv("DB_PATH", str(BASE_DIR / "tele2rub.db"))

    # Comma-separated Telegram user IDs that should be treated as admins.
    admin_ids: tuple[int, ...] = tuple(
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
    )

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()


# Single shared instance — import this everywhere.
config = AppConfig()


def assert_runtime_config() -> None:
    """
    Validate that the minimum required runtime credentials are present.

    Called from `bot.py` on startup so the operator sees a clear error
    instead of a deep stack trace.
    """
    missing: list[str] = []
    if not config.telegram.api_id:
        missing.append("TELEGRAM_API_ID")
    if not config.telegram.api_hash:
        missing.append("TELEGRAM_API_HASH")
    if not config.telegram.bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )
db.py
"""
db.py
-----
Async SQLite data layer (aiosqlite).

Schemas
=======
users
    telegram_id    INTEGER PRIMARY KEY  -- Telegram numeric user id
    username       TEXT                 -- Telegram @username (nullable)
    first_name     TEXT
    subscription   TEXT     NOT NULL    -- 'free' | 'premium'
    used_bytes     INTEGER  NOT NULL    -- cumulative uploaded volume
    created_at     TEXT     NOT NULL    -- ISO8601

files
    code           TEXT PRIMARY KEY     -- UUID4 hex returned to user
    owner_id       INTEGER  NOT NULL    -- FK -> users.telegram_id
    file_name      TEXT     NOT NULL
    mime_type      TEXT
    size_bytes     INTEGER  NOT NULL
    rubika_msg_id  TEXT     NOT NULL    -- message id inside Rubika target peer
    rubika_peer    TEXT     NOT NULL    -- peer guid / 'me'
    created_at     TEXT     NOT NULL    -- ISO8601
"""

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
utils.py
"""
utils.py
--------
Small, dependency-light helpers: code generation, formatters, subscription
enforcement.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from config import config


# ----------------------------------------------------------------------
# Unique codes
# ----------------------------------------------------------------------

_CODE_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def generate_code() -> str:
    """Return a 32-char hex UUID4 used as the public retrieval code."""
    return uuid.uuid4().hex


def is_valid_code(code: str) -> bool:
    """True if `code` matches the format generated by `generate_code`."""
    return bool(code) and bool(_CODE_RE.match(code.strip()))


# ----------------------------------------------------------------------
# Human-readable formatting
# ----------------------------------------------------------------------

def humanize_bytes(num: int) -> str:
    """Convert a byte count to a short human string, e.g. '12.3 MB'."""
    n = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


# ----------------------------------------------------------------------
# Subscription enforcement
# ----------------------------------------------------------------------

def tier_limits(tier: str) -> tuple[int, int]:
    """
    Return (single_file_limit_bytes, total_quota_bytes) for the given tier.
    Defaults to free if tier is unknown.
    """
    sub = config.subscription
    if tier == "premium":
        return sub.premium_single_file_bytes, sub.premium_total_quota_bytes
    return sub.free_single_file_bytes, sub.free_total_quota_bytes


def check_upload_allowed(user: dict[str, Any], incoming_size: int) -> tuple[bool, str]:
    """
    Decide whether a user is allowed to upload `incoming_size` bytes.

    Returns (ok, reason_if_not_ok).
    """
    tier = user.get("subscription", "free")
    used = int(user.get("used_bytes", 0))
    single_limit, total_limit = tier_limits(tier)

    if incoming_size <= 0:
        return False, "حجم فایل نامعتبر است."

    if incoming_size > single_limit:
        return False, (
            f"حجم این فایل ({humanize_bytes(incoming_size)}) از سقف مجاز "
            f"اشتراک {tier} ({humanize_bytes(single_limit)} برای هر فایل) بیشتر است."
        )

    if used + incoming_size > total_limit:
        remaining = max(total_limit - used, 0)
        return False, (
            f"حجم باقی‌مانده اشتراک شما کافی نیست. "
            f"باقی‌مانده: {humanize_bytes(remaining)} — "
            f"حجم این فایل: {humanize_bytes(incoming_size)}."
        )

    return True, ""


def remaining_quota(user: dict[str, Any]) -> int:
    """Return remaining bytes in the user's total quota (>=0)."""
    _, total_limit = tier_limits(user.get("subscription", "free"))
    used = int(user.get("used_bytes", 0))
    return max(total_limit - used, 0)
rubika_client.py
"""
rubika_client.py
----------------
Thin async wrapper around `rubpy` that:

* Maintains a single logged-in Rubika client for the whole bot lifetime.
* Uploads in-memory file bytes from Telegram into a Rubika peer
  (Saved Messages by default — `RUBIKA_TARGET_PEER=me`).
* Downloads files back from Rubika as bytes for streaming to Telegram.

Notes on `rubpy`
================
`rubpy.Client` is an async context manager. We keep one long-lived client
and reuse it across requests.

The first run is interactive: rubpy will prompt for phone number and OTP,
then persist a session file (e.g. `rubpy.rbs`) next to the project. After
that, startup is unattended.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Optional

from rubpy import Client as RubikaPyClient

from config import config

logger = logging.getLogger(__name__)


class RubikaService:
    """
    Long-lived Rubika client. Use `await service.start()` once at boot and
    `await service.stop()` on shutdown.

    All upload/download operations are serialized through a single asyncio
    lock — `rubpy` doesn't make hard guarantees about concurrent use of the
    same session, and serializing is fine for a moderate-traffic bot.
    """

    def __init__(self) -> None:
        self._client: Optional[RubikaPyClient] = None
        self._lock = asyncio.Lock()
        self._started = False
        self._target_peer = config.rubika.target_peer  # 'me' or channel guid

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Authenticate (interactively on first run) and keep client alive."""
        if self._started:
            return
        logger.info("Starting Rubika client (session=%s)", config.rubika.session_name)
        self._client = RubikaPyClient(name=config.rubika.session_name)
        # rubpy supports an explicit connect/start; using `start()` here so the
        # client stays open across many requests instead of using `async with`.
        await self._client.start()
        self._started = True
        logger.info("Rubika client started.")

    async def stop(self) -> None:
        """Cleanly disconnect the Rubika session."""
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as exc:  # best effort
                logger.warning("Error while disconnecting Rubika: %s", exc)
            self._client = None
        self._started = False

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload_bytes(
        self,
        *,
        data: bytes,
        file_name: str,
        caption: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Upload an in-memory file to the configured Rubika peer.

        Returns a dict containing at least:
            { 'message_id': str, 'peer': str }

        Raises RuntimeError if the underlying rubpy call fails.
        """
        if not self._started or self._client is None:
            raise RuntimeError("RubikaService is not started.")

        async with self._lock:
            # rubpy accepts a path or a file-like object. We use BytesIO so
            # nothing ever touches disk on this server.
            buf = io.BytesIO(data)
            buf.name = file_name  # rubpy/most uploaders inspect .name

            logger.info("Uploading %s (%d bytes) to Rubika peer=%s",
                        file_name, len(data), self._target_peer)
            try:
                result = await self._client.send_file(
                    self._target_peer,
                    buf,
                    caption=caption or "",
                    file_name=file_name,
                )
            except TypeError:
                # Older rubpy versions don't accept `file_name=`; retry without.
                buf.seek(0)
                result = await self._client.send_file(
                    self._target_peer,
                    buf,
                    caption=caption or "",
                )

            message_id = _extract_message_id(result)
            if message_id is None:
                raise RuntimeError(
                    f"Rubika upload returned no message_id. Raw: {result!r}"
                )
            return {"message_id": str(message_id), "peer": self._target_peer}

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download_bytes(self, *, peer: str, message_id: str) -> bytes:
        """
        Fetch a previously-uploaded file from Rubika and return its raw bytes.

        We deliberately avoid writing to disk: rubpy can download to a
        file-like object or return bytes directly depending on the version.
        """
        if not self._started or self._client is None:
            raise RuntimeError("RubikaService is not started.")

        async with self._lock:
            logger.info("Downloading message_id=%s from peer=%s", message_id, peer)

            # Try the most common rubpy APIs in order of preference.
            # 1) get_messages(...) + download(...)
            message = None
            try:
                message = await self._client.get_messages(peer, [int(message_id)])
            except Exception:
                try:
                    message = await self._client.get_messages_by_id(peer, [int(message_id)])
                except Exception:
                    message = None

            if message is not None:
                # Some versions return a list-like; pick the first message.
                msg_obj = message[0] if isinstance(message, (list, tuple)) else message
                try:
                    data = await msg_obj.download()
                    if isinstance(data, (bytes, bytearray)):
                        return bytes(data)
                except Exception:
                    pass

            # 2) Fallback: client.download(peer, message_id) -> bytes
            try:
                data = await self._client.download(peer, int(message_id))
                if isinstance(data, (bytes, bytearray)):
                    return bytes(data)
            except Exception as exc:
                logger.exception("Rubika download failed: %s", exc)

            raise RuntimeError(
                "Failed to download file from Rubika "
                f"(peer={peer}, message_id={message_id})."
            )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _extract_message_id(result: Any) -> Optional[Any]:
    """
    rubpy's `send_file` return shape varies between versions. Try several
    common locations to extract a numeric message id.
    """
    if result is None:
        return None

    # Plain dict
    if isinstance(result, dict):
        for key in ("message_id", "message_id_str", "id"):
            if key in result and result[key]:
                return result[key]
        # Nested under 'message_update' / 'data'
        for key in ("message_update", "data", "update"):
            if key in result and isinstance(result[key], dict):
                inner = result[key]
                for k in ("message_id", "id"):
                    if k in inner and inner[k]:
                        return inner[k]

    # Object-like
    for attr in ("message_id", "id"):
        val = getattr(result, attr, None)
        if val:
            return val

    return None


# Single shared instance — imported by bot.py
rubika_service = RubikaService()
bot.py
"""
bot.py
------
Pyrogram-based Telegram bot entrypoint.

Commands
========
/start    - Greeting + how-to.
/help     - Same as /start, kept for discoverability.
/profile  - Show subscription tier, used volume, remaining quota.
/history  - List the user's last 20 uploads with their codes.
/get CODE - Retrieve a previously-uploaded file by its UUID code.
            (Owner-only — other users see "not found".)
/upgrade  - Admin-only: `/upgrade <telegram_id> <free|premium>`.

Any document/photo/video/audio sent to the bot is uploaded to Rubika.
A unique UUID code is returned and persisted in SQLite. Files never
hit local disk.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message

import db
from config import assert_runtime_config, config
from rubika_client import rubika_service
from utils import (
    check_upload_allowed,
    generate_code,
    humanize_bytes,
    is_valid_code,
    remaining_quota,
    tier_limits,
)


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("tele2rub")


# ----------------------------------------------------------------------
# Pyrogram client
# ----------------------------------------------------------------------

app = Client(
    name=config.telegram.session_name,
    api_id=config.telegram.api_id,
    api_hash=config.telegram.api_hash,
    bot_token=config.telegram.bot_token,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _is_admin(telegram_id: int) -> bool:
    return telegram_id in config.admin_ids


async def _ensure_user(message: Message) -> dict:
    """Upsert the sender into the DB and return their row."""
    u = message.from_user
    return await db.get_or_create_user(
        telegram_id=u.id,
        username=u.username,
        first_name=u.first_name,
    )


def _pick_media(message: Message):
    """
    Return the (media_obj, kind) for the first supported media on the
    message, or (None, None). Pyrogram-style.
    """
    for kind in ("document", "video", "audio", "voice", "animation"):
        media = getattr(message, kind, None)
        if media is not None:
            return media, kind
    if message.photo:
        return message.photo, "photo"
    return None, None


# ----------------------------------------------------------------------
# Command handlers
# ----------------------------------------------------------------------

WELCOME_TEXT = (
    "**Tele2Rub** — انتقال فایل از تلگرام به روبیکا\n\n"
    "هر فایلی که برای من بفرستی، روی اکانت روبیکای سرور آپلود می‌شود "
    "و یک **کد یکتا** دریافت می‌کنی.\n"
    "هر زمان خواستی همان فایل را برگردانم، کافیست بفرستی:\n"
    "`/get <کد>`\n\n"
    "دستورات مفید:\n"
    "• /profile — مشخصات اشتراک و حجم باقی‌مانده\n"
    "• /history — لیست آخرین فایل‌های شما\n"
    "• /get `code` — دریافت فایل با کد\n"
)


@app.on_message(filters.command(["start", "help"]) & filters.private)
async def cmd_start(_: Client, message: Message) -> None:
    await _ensure_user(message)
    await message.reply_text(WELCOME_TEXT, disable_web_page_preview=True)


@app.on_message(filters.command("profile") & filters.private)
async def cmd_profile(_: Client, message: Message) -> None:
    user = await _ensure_user(message)
    single_limit, total_limit = tier_limits(user["subscription"])
    remaining = remaining_quota(user)
    text = (
        "**پروفایل شما**\n\n"
        f"• شناسه تلگرام: `{user['telegram_id']}`\n"
        f"• یوزرنیم: @{user.get('username') or '—'}\n"
        f"• اشتراک: **{user['subscription']}**\n"
        f"• حجم استفاده شده: {humanize_bytes(user['used_bytes'])} / "
        f"{humanize_bytes(total_limit)}\n"
        f"• حجم باقی‌مانده: **{humanize_bytes(remaining)}**\n"
        f"• حداکثر حجم هر فایل: {humanize_bytes(single_limit)}\n"
    )
    await message.reply_text(text)


@app.on_message(filters.command("history") & filters.private)
async def cmd_history(_: Client, message: Message) -> None:
    user = await _ensure_user(message)
    files = await db.list_user_files(user["telegram_id"], limit=20)
    if not files:
        await message.reply_text("هنوز فایلی آپلود نکرده‌اید.")
        return
    lines = ["**آخرین فایل‌های شما:**\n"]
    for f in files:
        lines.append(
            f"• `{f['code']}` — {f['file_name']} "
            f"({humanize_bytes(f['size_bytes'])})"
        )
    lines.append("\nبرای دریافت: `/get <کد>`")
    await message.reply_text("\n".join(lines))


@app.on_message(filters.command("get") & filters.private)
async def cmd_get(_: Client, message: Message) -> None:
    user = await _ensure_user(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("استفاده: `/get <کد>`")
        return

    code = parts[1].strip()
    if not is_valid_code(code):
        await message.reply_text("کد نامعتبر است.")
        return

    record = await db.get_file_by_code(code)
    # Owner-only access: respond with the same "not found" to leak nothing.
    if record is None or record["owner_id"] != user["telegram_id"]:
        await message.reply_text("فایلی با این کد یافت نشد.")
        return

    status = await message.reply_text("در حال دریافت فایل از روبیکا...")
    try:
        data = await rubika_service.download_bytes(
            peer=record["rubika_peer"],
            message_id=record["rubika_msg_id"],
        )
    except Exception as exc:
        logger.exception("Rubika download failed for code=%s: %s", code, exc)
        await status.edit_text("دریافت فایل از روبیکا با خطا مواجه شد.")
        return

    buf = io.BytesIO(data)
    buf.name = record["file_name"]
    try:
        await message.reply_document(
            document=buf,
            file_name=record["file_name"],
            caption=f"کد: `{code}`",
        )
        await status.delete()
    except Exception as exc:
        logger.exception("Failed to send file back to Telegram: %s", exc)
        await status.edit_text("ارسال فایل به تلگرام با خطا مواجه شد.")


@app.on_message(filters.command("upgrade") & filters.private)
async def cmd_upgrade(_: Client, message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.reply_text("این دستور فقط برای ادمین در دسترس است.")
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or parts[2] not in ("free", "premium"):
        await message.reply_text("استفاده: `/upgrade <telegram_id> <free|premium>`")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.reply_text("شناسه تلگرام نامعتبر است.")
        return
    await db.set_subscription(target_id, parts[2])
    await message.reply_text(f"اشتراک کاربر `{target_id}` به **{parts[2]}** تغییر کرد.")


# ----------------------------------------------------------------------
# File upload handler
# ----------------------------------------------------------------------

@app.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.voice
        | filters.animation
        | filters.photo
    )
)
async def on_file(_: Client, message: Message) -> None:
    user = await _ensure_user(message)
    media, kind = _pick_media(message)
    if media is None:
        return

    # Resolve file_name + size; photos don't have file_name.
    if kind == "photo":
        file_name = f"photo_{message.id}.jpg"
        size_bytes = getattr(media, "file_size", 0) or 0
        mime_type = "image/jpeg"
    else:
        file_name = getattr(media, "file_name", None) or f"{kind}_{message.id}"
        size_bytes = getattr(media, "file_size", 0) or 0
        mime_type = getattr(media, "mime_type", None)

    allowed, reason = check_upload_allowed(user, size_bytes)
    if not allowed:
        await message.reply_text(reason)
        return

    status = await message.reply_text(
        f"در حال دریافت فایل ({humanize_bytes(size_bytes)})..."
    )

    # Stream from Telegram straight into RAM (no disk).
    try:
        data = await message.download(in_memory=True)
        # Pyrogram returns a BinaryIO when in_memory=True
        if hasattr(data, "getvalue"):
            payload = data.getvalue()
        else:
            payload = bytes(data)
    except Exception as exc:
        logger.exception("Telegram download failed: %s", exc)
        await status.edit_text("دانلود فایل از تلگرام با خطا مواجه شد.")
        return

    await status.edit_text("در حال آپلود به روبیکا...")

    try:
        up = await rubika_service.upload_bytes(
            data=payload,
            file_name=file_name,
            caption=f"uploader={user['telegram_id']}",
        )
    except Exception as exc:
        logger.exception("Rubika upload failed: %s", exc)
        await status.edit_text("آپلود به روبیکا با خطا مواجه شد. لطفاً بعداً تلاش کنید.")
        return

    code = generate_code()
    await db.save_file_record(
        code=code,
        owner_id=user["telegram_id"],
        file_name=file_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        rubika_msg_id=up["message_id"],
        rubika_peer=up["peer"],
    )
    await db.add_usage(user["telegram_id"], size_bytes)

    await status.edit_text(
        "✅ فایل با موفقیت روی روبیکا ذخیره شد.\n\n"
        f"**کد یکتا:** `{code}`\n"
        f"حجم: {humanize_bytes(size_bytes)}\n\n"
        f"برای دریافت: `/get {code}`"
    )


# ----------------------------------------------------------------------
# Lifecycle wiring
# ----------------------------------------------------------------------

async def _on_startup() -> None:
    assert_runtime_config()
    await db.init_db()
    await rubika_service.start()
    logger.info("Bot is up.")


async def _on_shutdown() -> None:
    await rubika_service.stop()
    logger.info("Bot is shutting down.")


def main() -> None:
    """
    Start the bot. We use pyrogram's `app.start()` and run our own start/stop
    coroutines around it.
    """
    import asyncio

    async def runner() -> None:
        await _on_startup()
        try:
            await app.start()
            # Keep the process alive forever; pyrogram dispatches events
            # in its own background tasks.
            await _idle()
        finally:
            try:
                await app.stop()
            except Exception:
                pass
            await _on_shutdown()

    asyncio.run(runner())


async def _idle() -> None:
    """Sleep forever until cancelled (Ctrl+C / SIGTERM)."""
    import asyncio
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == "__main__":
    main()