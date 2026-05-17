
# Action: file_editor create /app/bot/db.py --file-text """"
# MongoDB layer for Tele2Rub Pro.
# Collections:
# - users     : per-user profile, plan & usage tracking
# - files     : uploaded file records (unique codes + rubika message ids)
# - queue     : upload queue shared between the telegram bot and the rubika worker
# - status    : push-status messages for the telegram bot to render in chat
# - settings  : key/value runtime settings (e.g. storage channel guid)
# """
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_URL, DB_NAME, PLANS, DEFAULT_PLAN, RUBIKA_STORAGE_CHANNEL_GUID
from utils import generate_code, mb_to_bytes


# Lazy singletons; created on first use so both processes can share the module.
_client: Optional[AsyncIOMotorClient] = None
_db = None


def db():
    """Return the shared motor database instance."""
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(MONGO_URL)
        _db = _client[DB_NAME]
    return _db


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- index bootstrap ----------
async def ensure_indexes():
    d = db()
    await d.users.create_index("tg_user_id", unique=True)
    await d.files.create_index("code", unique=True)
    await d.files.create_index("tg_user_id")
    await d.files.create_index("created_at")
    await d.queue.create_index([("status", 1), ("created_at", 1)])
    await d.settings.create_index("key", unique=True)


# ---------- settings ----------
async def get_setting(key: str, default: Any = None) -> Any:
    d = db()
    doc = await d.settings.find_one({"key": key}, {"_id": 0})
    return doc["value"] if doc else default


async def set_setting(key: str, value: Any) -> None:
    d = db()
    await d.settings.update_one(
        {"key": key},
        {"$set": {"key": key, "value": value, "updated_at": now()}},
        upsert=True,
    )


async def get_storage_channel_guid() -> str:
    """Return the configured Rubika storage channel guid.
    Priority: DB setting > .env value.
    """
    val = await get_setting("storage_channel_guid")
    if val:
        return str(val).strip()
    return RUBIKA_STORAGE_CHANNEL_GUID


# ---------- users ----------
def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


async def get_or_create_user(tg_user_id: int, first_name: str = "", username: str = "") -> dict:
    d = db()
    user = await d.users.find_one({"tg_user_id": tg_user_id}, {"_id": 0})
    if user:
        # keep profile fresh
        if user.get("first_name") != first_name or user.get("username") != username:
            await d.users.update_one(
                {"tg_user_id": tg_user_id},
                {"$set": {"first_name": first_name, "username": username}},
            )
            user["first_name"] = first_name
            user["username"] = username
        return user

    plan = PLANS[DEFAULT_PLAN]
    user = {
        "tg_user_id": tg_user_id,
        "first_name": first_name,
        "username": username,
        "plan": DEFAULT_PLAN,
        "plan_started_at": now(),
        "plan_expires_at": now() + timedelta(days=plan["duration_days"]),
        "used_bytes_total": 0,
        "used_bytes_month": 0,
        "month_key": _month_key(now()),
        "uploads_total": 0,
        "blocked": False,
        "created_at": now(),
    }
    await d.users.insert_one(user.copy())  # copy so motor's _id doesn't leak
    user.pop("_id", None)
    return user


async def reset_month_if_needed(user: dict) -> dict:
    """Roll the monthly counter at the start of a new calendar month."""
    cur_month = _month_key(now())
    if user.get("month_key") != cur_month:
        d = db()
        await d.users.update_one(
            {"tg_user_id": user["tg_user_id"]},
            {"$set": {"used_bytes_month": 0, "month_key": cur_month}},
        )
        user["used_bytes_month"] = 0
        user["month_key"] = cur_month
    return user


async def add_usage(tg_user_id: int, size_bytes: int) -> None:
    d = db()
    await d.users.update_one(
        {"tg_user_id": tg_user_id},
        {
            "$inc": {
                "used_bytes_total": int(size_bytes),
                "used_bytes_month": int(size_bytes),
                "uploads_total": 1,
            }
        },
    )


async def can_upload(user: dict, size_bytes: int) -> tuple[bool, str]:
    """Return (ok, reason_if_not_ok)."""
    if user.get("blocked"):
        return False, "حساب شما توسط مدیر مسدود شده است."

    expires_at = user.get("plan_expires_at")
    if isinstance(expires_at, datetime) and expires_at < now():
        return False, "اشتراک شما به پایان رسیده است. لطفاً برای تمدید با ادمین تماس بگیرید."

    plan_key = user.get("plan", DEFAULT_PLAN)
    plan = PLANS.get(plan_key, PLANS[DEFAULT_PLAN])

    max_file = mb_to_bytes(plan["max_file_mb"])
    if size_bytes > max_file:
        return False, f"حجم فایل بیشتر از حد مجاز پلن «{plan['label']}» است (حداکثر {plan['max_file_mb']} مگابایت)."

    monthly_quota = mb_to_bytes(plan["monthly_quota_mb"])
    used = int(user.get("used_bytes_month") or 0)
    if used + size_bytes > monthly_quota:
        remaining = max(0, monthly_quota - used)
        return False, f"حجم مصرفی این ماه شما تمام شده است.\nباقی‌مانده: {remaining // (1024*1024)} مگابایت"

    return True, ""


async def set_plan(tg_user_id: int, plan_key: str, duration_days: Optional[int] = None) -> dict:
    """Activate / extend a subscription for a user."""
    plan = PLANS[plan_key]
    days = duration_days if duration_days is not None else plan["duration_days"]
    d = db()
    existing = await d.users.find_one({"tg_user_id": tg_user_id}, {"_id": 0})
    base = now()
    if existing and existing.get("plan") == plan_key:
        cur_exp = existing.get("plan_expires_at")
        if isinstance(cur_exp, datetime) and cur_exp > base:
            base = cur_exp
    new_expires = base + timedelta(days=int(days))
    await d.users.update_one(
        {"tg_user_id": tg_user_id},
        {
            "$set": {
                "plan": plan_key,
                "plan_started_at": now(),
                "plan_expires_at": new_expires,
            }
        },
        upsert=True,
    )
    return await d.users.find_one({"tg_user_id": tg_user_id}, {"_id": 0})


async def set_blocked(tg_user_id: int, blocked: bool) -> None:
    await db().users.update_one(
        {"tg_user_id": tg_user_id},
        {"$set": {"blocked": bool(blocked)}},
    )


async def list_users(limit: int = 50, skip: int = 0) -> list[dict]:
    cur = db().users.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    return [u async for u in cur]


async def count_users() -> int:
    return await db().users.count_documents({})


# ---------- queue ----------
async def push_task(task: dict) -> str:
    d = db()
    task = dict(task)
    task.setdefault("status", "pending")
    task["created_at"] = now()
    task["job_id"] = task.get("job_id") or generate_code(10)
    await d.queue.insert_one(task.copy())
    task.pop("_id", None)
    return task["job_id"]


async def pop_next_task() -> Optional[dict]:
    """Atomically pick the next pending task and mark it as processing."""
    d = db()
    doc = await d.queue.find_one_and_update(
        {"status": "pending"},
        {"$set": {"status": "processing", "started_at": now()}},
        sort=[("created_at", 1)],
        projection={"_id": 0},
    )
    return doc


async def finish_task(job_id: str, ok: bool, error: str = "") -> None:
    d = db()
    await d.queue.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": "done" if ok else "failed",
                "finished_at": now(),
                "error": error,
            }
        },
    )


async def cancel_task(job_id: str) -> bool:
    """Mark a pending task as cancelled (won't affect tasks already uploading).
    Returns True if a pending task was cancelled."""
    d = db()
    res = await d.queue.update_one(
        {"job_id": job_id, "status": "pending"},
        {"$set": {"status": "cancelled", "finished_at": now()}},
    )
    if res.modified_count:
        return True
    # Mark intent for in-flight cancellation
    await d.queue.update_one(
        {"job_id": job_id, "status": "processing"},
        {"$set": {"cancel_requested": True}},
    )
    return False


async def is_cancel_requested(job_id: str) -> bool:
    d = db()
    doc = await d.queue.find_one({"job_id": job_id}, {"cancel_requested": 1, "_id": 0})
    return bool(doc and doc.get("cancel_requested"))


async def clear_user_pending(tg_user_id: int) -> int:
    d = db()
    res = await d.queue.update_many(
        {"tg_user_id": tg_user_id, "status": "pending"},
        {"$set": {"status": "cancelled", "finished_at": now()}},
    )
    return res.modified_count


# ---------- status push (worker -> bot) ----------
async def push_status(chat_id: int, message_id: int, text: str, percent: Optional[float] = None,
                      status: str = "working") -> None:
    await db().status.insert_one({
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "percent": percent,
        "status": status,
        "created_at": now(),
        "delivered": False,
    })


async def pop_pending_status_batch(limit: int = 20) -> list[dict]:
    d = db()
    docs = []
    async for doc in d.status.find({"delivered": False}).sort("created_at", 1).limit(limit):
        docs.append(doc)
    if docs:
        ids = [doc["_id"] for doc in docs]
        await d.status.update_many({"_id": {"$in": ids}}, {"$set": {"delivered": True}})
    for doc in docs:
        doc.pop("_id", None)
    return docs


# ---------- files / unique codes ----------
async def create_file_record(*, tg_user_id: int, file_name: str, file_size: int,
                             rubika_message_id: str, channel_guid: str, caption: str,
                             expiry_days: int) -> dict:
    """Generate a unique code and persist the file record."""
    d = db()
    for _ in range(20):
        code = generate_code(8)
        try:
            doc = {
                "code": code,
                "tg_user_id": tg_user_id,
                "file_name": file_name,
                "file_size": int(file_size),
                "rubika_message_id": str(rubika_message_id),
                "channel_guid": channel_guid,
                "caption": caption or "",
                "created_at": now(),
                "expires_at": now() + timedelta(days=int(expiry_days)) if expiry_days else None,
                "delivered_count": 0,
                "deleted": False,
            }
            await d.files.insert_one(doc.copy())
            doc.pop("_id", None)
            return doc
        except Exception:
            continue
    raise RuntimeError("Could not generate a unique code.")


async def get_file_by_code(code: str) -> Optional[dict]:
    if not code:
        return None
    doc = await db().files.find_one({"code": code.upper(), "deleted": False}, {"_id": 0})
    return doc


async def bump_delivered(code: str) -> None:
    await db().files.update_one({"code": code.upper()}, {"$inc": {"delivered_count": 1}})


async def list_user_files(tg_user_id: int, limit: int = 10) -> list[dict]:
    cur = db().files.find({"tg_user_id": tg_user_id, "deleted": False}, {"_id": 0})\
        .sort("created_at", -1).limit(limit)
    return [d async for d in cur]


async def count_files() -> int:
    return await db().files.count_documents({"deleted": False})


async def total_storage_bytes() -> int:
    pipe = [
        {"$match": {"deleted": False}},
        {"$group": {"_id": None, "total": {"$sum": "$file_size"}}},
    ]
    async for row in db().files.aggregate(pipe):
        return int(row.get("total") or 0)
    return 0
