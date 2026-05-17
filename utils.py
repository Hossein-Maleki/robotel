import os
import random
import string
import math
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ---------- core ----------
def generate_code(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def mb_to_bytes(mb: float | int) -> int:
    return int(mb * 1024 * 1024)


# ---------- file utils ----------
def pretty_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0B"

    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {units[i]}"


def safe_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "._- ").strip()


def eta_text(seconds: int) -> str:
    if seconds <= 0:
        return "0s"

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)

    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

def split_name(filename: str) -> tuple[str, str]:
    """
    جدا کردن اسم فایل از پسوند
    example: video.mp4 -> ("video", ".mp4")
    """
    if not filename:
        return "file", ""

    import os
    name, ext = os.path.splitext(filename)
    return name or "file", ext

def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path

    base, ext = os.path.splitext(path)
    counter = 1

    while True:
        new_path = f"{base}_{counter}{ext}"
        if not os.path.exists(new_path):
            return new_path
        counter += 1