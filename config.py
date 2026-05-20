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