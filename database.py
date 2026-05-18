import sqlite3
import string
import random
from datetime import datetime, timedelta
from pathlib import Path
from config import DB_PATH, PLANS


def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            rubika_guid TEXT,
            username TEXT,
            first_name TEXT,
            link_code TEXT UNIQUE,
            is_linked INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            volume_limit INTEGER NOT NULL,
            volume_used INTEGER DEFAULT 0,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unique_code TEXT UNIQUE NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT,
            file_size INTEGER DEFAULT 0,
            file_type TEXT,
            caption TEXT,
            chat_id INTEGER,
            message_id INTEGER,
            uploaded_by INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            upload_id INTEGER NOT NULL,
            file_size INTEGER DEFAULT 0,
            downloaded_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (upload_id) REFERENCES uploads(id)
        );

        CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_users_rubika_guid ON users(rubika_guid);
        CREATE INDEX IF NOT EXISTS idx_users_link_code ON users(link_code);
        CREATE INDEX IF NOT EXISTS idx_uploads_unique_code ON uploads(unique_code);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
    """)

    conn.commit()
    conn.close()


def generate_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_link_code():
    return "LNK" + generate_code(5)


# ─── User Operations ───

def get_or_create_user(telegram_id, username=None, first_name=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cur.fetchone()

    if user:
        if username or first_name:
            cur.execute(
                "UPDATE users SET username = COALESCE(?, username), first_name = COALESCE(?, first_name) WHERE telegram_id = ?",
                (username, first_name, telegram_id)
            )
            conn.commit()
        conn.close()
        return dict(user), False

    link_code = generate_link_code()
    while True:
        cur.execute("SELECT id FROM users WHERE link_code = ?", (link_code,))
        if not cur.fetchone():
            break
        link_code = generate_link_code()

    cur.execute(
        "INSERT INTO users (telegram_id, username, first_name, link_code) VALUES (?, ?, ?, ?)",
        (telegram_id, username, first_name, link_code)
    )
    conn.commit()
    user_id = cur.lastrowid
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = dict(cur.fetchone())
    conn.close()
    return user, True


def get_user_by_telegram_id(telegram_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_rubika_guid(rubika_guid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE rubika_guid = ?", (rubika_guid,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_link_code(link_code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE link_code = ?", (link_code.upper(),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def link_rubika_account(link_code, rubika_guid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE link_code = ?", (link_code.upper(),))
    user = cur.fetchone()
    if not user:
        conn.close()
        return None, "کد لینک نامعتبر است."

    if user['is_linked'] and user['rubika_guid']:
        conn.close()
        return None, "این حساب قبلا لینک شده است."

    # Check if rubika_guid already linked to another user
    cur.execute("SELECT * FROM users WHERE rubika_guid = ? AND id != ?", (rubika_guid, user['id']))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return None, "این حساب روبیکا قبلا به کاربر دیگری لینک شده."

    cur.execute(
        "UPDATE users SET rubika_guid = ?, is_linked = 1 WHERE id = ?",
        (rubika_guid, user['id'])
    )
    conn.commit()
    conn.close()
    return dict(user), None


def set_admin(telegram_id, is_admin=True):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_admin = ? WHERE telegram_id = ?", (1 if is_admin else 0, telegram_id))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_all_users_count():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    row = cur.fetchone()
    conn.close()
    return row['cnt'] if row else 0


def get_active_subscriptions_count():
    conn = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "SELECT COUNT(*) as cnt FROM subscriptions WHERE is_active = 1 AND end_date > ?",
        (now,)
    )
    row = cur.fetchone()
    conn.close()
    return row['cnt'] if row else 0


# ─── Subscription Operations ───

def get_active_subscription(user_id):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 AND end_date > ? ORDER BY end_date DESC LIMIT 1",
        (user_id, now)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def create_subscription(user_id, plan_id):
    plan = PLANS.get(plan_id)
    if not plan:
        return None, "پلن نامعتبر است."

    conn = get_db()
    cur = conn.cursor()

    # Deactivate old subscriptions
    cur.execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ? AND is_active = 1", (user_id,))

    now = datetime.utcnow()
    end = now + timedelta(days=plan['duration_days'])
    volume_limit = plan['volume_gb'] * 1024 * 1024 * 1024  # Convert to bytes

    cur.execute(
        "INSERT INTO subscriptions (user_id, plan_id, volume_limit, start_date, end_date) VALUES (?, ?, ?, ?, ?)",
        (user_id, plan_id, volume_limit, now.isoformat(), end.isoformat())
    )
    conn.commit()
    sub_id = cur.lastrowid
    cur.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,))
    sub = dict(cur.fetchone())
    conn.close()
    return sub, None


def update_volume_used(subscription_id, additional_bytes):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE subscriptions SET volume_used = volume_used + ? WHERE id = ?",
        (additional_bytes, subscription_id)
    )
    conn.commit()
    conn.close()


# ─── Upload Operations ───

def create_upload(file_path, file_name, file_size, file_type, caption, chat_id, message_id, uploaded_by):
    code = generate_code(8)
    conn = get_db()
    cur = conn.cursor()

    # Ensure unique code
    while True:
        cur.execute("SELECT id FROM uploads WHERE unique_code = ?", (code,))
        if not cur.fetchone():
            break
        code = generate_code(8)

    cur.execute(
        """INSERT INTO uploads (unique_code, file_path, file_name, file_size, file_type, caption, chat_id, message_id, uploaded_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (code, file_path, file_name, file_size, file_type, caption, chat_id, message_id, uploaded_by)
    )
    conn.commit()
    upload_id = cur.lastrowid
    cur.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,))
    upload = dict(cur.fetchone())
    conn.close()
    return upload


def get_upload_by_code(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads WHERE unique_code = ?", (code.upper(),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_uploads_count():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM uploads")
    row = cur.fetchone()
    conn.close()
    return row['cnt'] if row else 0


def get_total_download_volume():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(file_size), 0) as total FROM downloads")
    row = cur.fetchone()
    conn.close()
    return row['total'] if row else 0


# ─── Download Operations ───

def record_download(user_id, upload_id, file_size):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO downloads (user_id, upload_id, file_size) VALUES (?, ?, ?)",
        (user_id, upload_id, file_size)
    )
    conn.commit()
    conn.close()


def get_user_downloads(user_id, limit=20):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """SELECT d.*, u.unique_code, u.file_name
           FROM downloads d JOIN uploads u ON d.upload_id = u.id
           WHERE d.user_id = ? ORDER BY d.downloaded_at DESC LIMIT ?""",
        (user_id, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_downloads_count():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM downloads")
    row = cur.fetchone()
    conn.close()
    return row['cnt'] if row else 0


# Initialize database on import
init_db()


