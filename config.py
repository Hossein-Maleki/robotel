import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DB_PATH = BASE_DIR / "bot.db"

# Telegram Settings
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Rubika Settings
RUBIKA_SESSION = os.getenv("RUBIKA_SESSION", "rubika_session").strip()

# Admin Telegram IDs (comma-separated in .env)
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# Channel ID for storing files (optional, bot must be admin)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0")) if os.getenv("CHANNEL_ID", "").strip().lstrip("-").isdigit() else 0

# Subscription Plans - 25,000 Toman per GB
PLANS = {
    1: {"name": "پلن ۲ گیگابایت", "volume_gb": 2, "price_toman": 50000, "duration_days": 30},
    2: {"name": "پلن ۴ گیگابایت", "volume_gb": 4, "price_toman": 100000, "duration_days": 30},
    3: {"name": "پلن ۶ گیگابایت", "volume_gb": 6, "price_toman": 150000, "duration_days": 30},
    4: {"name": "پلن ۱۰ گیگابایت", "volume_gb": 10, "price_toman": 250000, "duration_days": 30},
}

# Max file size (2 GB)
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


