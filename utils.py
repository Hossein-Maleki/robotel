import os
import random
import string
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ---------- utils ----------
def generate_code(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def mb_to_bytes(mb: float | int) -> int:
    return int(mb * 1024 * 1024)


# ---------- helpers ----------
def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _ids_list(name: str) -> list[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    out = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


# ---------- Telegram ----------
API_ID = _int("API_ID", 0)
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# ---------- Rubika ----------
RUBIKA_SESSION = os.getenv("RUBIKA_SESSION", "rubika_session").strip()
RUBIKA_STORAGE_CHANNEL_GUID = os.getenv("RUBIKA_STORAGE_CHANNEL_GUID", "").strip()
RUBIKA_ACCOUNT_USERNAME = os.getenv("RUBIKA_ACCOUNT_USERNAME", "").strip().lstrip("@")

# ---------- MongoDB ----------
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017").strip()
DB_NAME = os.getenv("DB_NAME", "tele2rub_pro").strip()

# ---------- Admins ----------
ADMIN_IDS = _ids_list("ADMIN_IDS")

# ---------- Plans ----------
PLANS = {
    "free": {
        "monthly_quota_mb": 500,
        "max_file_mb": 200,
        "duration_days": 36500,
        "label": "رایگان",
        "file_expiry_days": 7,
    },
    "bronze": {
        "monthly_quota_mb": 5 * 1024,
        "max_file_mb": 1024,
        "duration_days": 30,
        "label": "برنزی",
        "file_expiry_days": 30,
    },
    "silver": {
        "monthly_quota_mb": 20 * 1024,
        "max_file_mb": 2048,
        "duration_days": 30,
        "label": "نقره‌ای",
        "file_expiry_days": 90,
    },
    "gold": {
        "monthly_quota_mb": 100 * 1024,
        "max_file_mb": 2048,
        "duration_days": 30,
        "label": "طلایی",
        "file_expiry_days": 365,
    },
}

DEFAULT_PLAN = "free"