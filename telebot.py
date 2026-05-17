
# Action: file_editor create /app/bot/telebot.py --file-text """"
# Telegram bot front-end for Tele2Rub Pro.

# Responsibilities:
# - Multi-user profile (per Telegram user_id)
# - Subscription state (free / bronze / silver / gold) with quota enforcement
# - Accept files / direct URLs, queue them for the Rubika worker
# - Admin panel (in-bot) for activating/extending plans, blocking users, broadcast, stats
# - Pulls status updates from the worker and edits the user's status message
# """
import asyncio
import time
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone, timedelta

from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)

import config
import db as data
from utils import (
    safe_filename, split_name, pretty_size, eta_text, progress_bar,
    extract_first_url, unique_path, mb_to_bytes,
)


# ----------------------------- bootstrap -----------------------------

app = Client(
    "tele2rub_pro",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workdir=str(config.SESSIONS_DIR),
)


def is_admin(user_id: int) -> bool:
    return int(user_id) in config.ADMIN_IDS


# Track pending admin/user prompts (e.g. waiting for a value)
PENDING_STATE: dict[int, dict] = {}


# ----------------------------- helpers -----------------------------

def get_media(message: Message):
    types = [
        ("document", message.document),
        ("video", message.video),
        ("audio", message.audio),
        ("voice", message.voice),
        ("photo", message.photo),
        ("animation", message.animation),
        ("video_note", message.video_note),
        ("sticker", message.sticker),
    ]
    for t, m in types:
        if m:
            return t, m
    return None, None


def build_download_filename(message: Message, media_type: str, media) -> str:
    name = getattr(media, "file_name", None)
    if not name:
        uid = getattr(media, "file_unique_id", None) or "file"
        defaults = {
            "document": ".bin", "video": ".mp4", "audio": ".mp3", "voice": ".ogg",
            "photo": ".jpg", "animation": ".mp4", "video_note": ".mp4", "sticker": ".webp",
        }
        name = f"{uid}{defaults.get(media_type, '.bin')}"
    name = safe_filename(name)
    stem, suffix = split_name(name)
    return safe_filename(f"{stem}_{message.id}{suffix or '.bin'}")


def fmt_datetime(dt) -> str:
    if not isinstance(dt, datetime):
        return "—"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def user_keyboard(is_admin_user: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("👤 پروفایل من", callback_data="me:profile"),
            InlineKeyboardButton("📂 فایل‌های اخیر", callback_data="me:files"),
        ],
        [
            InlineKeyboardButton("💎 پلن‌ها / تمدید اشتراک", callback_data="me:plans"),
            InlineKeyboardButton("ℹ️ راهنما", callback_data="me:help"),
        ],
    ]
    if is_admin_user:
        rows.append([InlineKeyboardButton("🛠 پنل ادمین", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


async def render_profile_text(user: dict) -> str:
    user = await data.reset_month_if_needed(user)
    plan_key = user.get("plan", config.DEFAULT_PLAN)
    plan = config.PLANS.get(plan_key, config.PLANS[config.DEFAULT_PLAN])
    used = int(user.get("used_bytes_month") or 0)
    quota = mb_to_bytes(plan["monthly_quota_mb"])
    remaining = max(0, quota - used)
    percent = (used / quota * 100) if quota else 0
    return (
        "👤 **پروفایل شما**\n\n"
        f"• شناسه: `{user['tg_user_id']}`\n"
        f"• نام: {user.get('first_name') or '—'}\n"
        f"• یوزرنیم: @{user.get('username')}" if user.get('username') else
        "👤 **پروفایل شما**\n\n"
        f"• شناسه: `{user['tg_user_id']}`\n"
        f"• نام: {user.get('first_name') or '—'}\n"
        f"• یوزرنیم: —"
    ) + (
        f"\n\n💎 پلن فعلی: **{plan['label']}**"
        f"\n📅 انقضای اشتراک: `{fmt_datetime(user.get('plan_expires_at'))}`"
        f"\n\n📊 مصرف این ماه:"
        f"\n`{progress_bar(percent)}` `{percent:.1f}%`"
        f"\n• مصرف‌شده: `{pretty_size(used)}` از `{pretty_size(quota)}`"
        f"\n• باقی‌مانده: `{pretty_size(remaining)}`"
        f"\n• حداکثر حجم هر فایل: `{plan['max_file_mb']} MB`"
        f"\n• عمر فایل‌ها: `{plan['file_expiry_days']} روز`"
        f"\n\n📈 آمار کلی:"
        f"\n• مجموع آپلودها: `{int(user.get('uploads_total') or 0)}`"
        f"\n• مجموع حجم آپلود شده: `{pretty_size(user.get('used_bytes_total') or 0)}`"
    )


def plans_text() -> str:
    lines = ["💎 **لیست پلن‌های اشتراک**\n"]
    for key, plan in config.PLANS.items():
        lines.append(
            f"\n🔸 **{plan['label']}** (`{key}`)\n"
            f"  • حجم ماهانه: `{plan['monthly_quota_mb']} MB`\n"
            f"  • حداکثر هر فایل: `{plan['max_file_mb']} MB`\n"
            f"  • عمر فایل‌ها: `{plan['file_expiry_days']} روز`\n"
            f"  • مدت اشتراک: `{plan['duration_days']} روز`"
        )
    lines.append("\n\nبرای فعال‌سازی یا تمدید اشتراک، با ادمین تماس بگیرید.")
    return "\n".join(lines)


HELP_TEXT = (
    "ℹ️ **راهنمای ربات**\n\n"
    "این ربات فایل‌های شما را دریافت می‌کند، آن‌ها را در یک چنل خصوصی روبیکا آپلود کرده و یک "
    "**کد یونیک** به همراه آی‌دی اکانت روبیکا به شما تحویل می‌دهد. هرکس آن کد را به اکانت "
    "روبیکای ربات بفرستد، فایل به‌صورت خودکار برای آن شخص ارسال می‌شود.\n\n"
    "📥 **روش استفاده**\n"
    "1) فایل را برای ربات بفرستید (یا لینک مستقیم بدهید).\n"
    "2) منتظر آپلود در روبیکا بمانید.\n"
    "3) کد یونیک تحویل می‌گیرید.\n"
    "4) کد را در روبیکا برای اکانت ربات بفرستید تا فایل ارسال شود.\n\n"
    "📌 دستورات:\n"
    "/start - شروع\n"
    "/profile - پروفایل و وضعیت اشتراک\n"
    "/plans - لیست پلن‌ها\n"
    "/myfiles - فایل‌های اخیر شما\n"
    "/del `<job_id>` - حذف یک مورد از صف\n"
    "/delall - پاکسازی صف خودِ شما\n"
    "/help - این راهنما\n"
)


# ----------------------------- /start & basic commands -----------------------------

@app.on_message(filters.private & filters.command("start"))
async def start_handler(_, message: Message):
    user = await data.get_or_create_user(
        message.from_user.id,
        message.from_user.first_name or "",
        message.from_user.username or "",
    )
    rubika_username = f"@{config.RUBIKA_ACCOUNT_USERNAME}" if config.RUBIKA_ACCOUNT_USERNAME else "—"
    text = (
        f"سلام {user.get('first_name') or 'کاربر'} عزیز 👋\n\n"
        "به **Tele2Rub Pro** خوش آمدید 💙\n"
        "فایل‌هایتان را اینجا بفرستید تا در روبیکا ذخیره شود و یک کد یونیک دریافت کنید.\n\n"
        f"🆔 اکانت روبیکا برای دریافت فایل با کد: `{rubika_username}`\n\n"
        "از منوی زیر شروع کنید 👇"
    )
    await message.reply_text(text, reply_markup=user_keyboard(is_admin(message.from_user.id)))


@app.on_message(filters.private & filters.command("help"))
async def help_handler(_, message: Message):
    await message.reply_text(HELP_TEXT)


@app.on_message(filters.private & filters.command("profile"))
async def profile_handler(_, message: Message):
    user = await data.get_or_create_user(
        message.from_user.id,
        message.from_user.first_name or "",
        message.from_user.username or "",
    )
    await message.reply_text(await render_profile_text(user))


@app.on_message(filters.private & filters.command("plans"))
async def plans_handler(_, message: Message):
    await message.reply_text(plans_text())


@app.on_message(filters.private & filters.command("myfiles"))
async def myfiles_handler(_, message: Message):
    files = await data.list_user_files(message.from_user.id, limit=10)
    if not files:
        await message.reply_text("هنوز فایلی آپلود نکرده‌اید.")
        return
    lines = ["📂 **آخرین فایل‌های شما:**\n"]
    rubika_username = f"@{config.RUBIKA_ACCOUNT_USERNAME}" if config.RUBIKA_ACCOUNT_USERNAME else "اکانت روبیکا"
    for f in files:
        exp = fmt_datetime(f.get("expires_at")) if f.get("expires_at") else "بدون انقضا"
        lines.append(
            f"• `{f['code']}` — {f['file_name']} ({pretty_size(f['file_size'])})\n"
            f"   ساخته شده: {fmt_datetime(f['created_at'])} | انقضا: {exp}\n"
        )
    lines.append(f"\nبرای دریافت هر فایل، کد آن را در روبیکا برای **{rubika_username}** بفرستید.")
    await message.reply_text("\n".join(lines))


# ----------------------------- queue management commands -----------------------------

@app.on_message(filters.private & filters.command("delall"))
async def delall_handler(_, message: Message):
    n = await data.clear_user_pending(message.from_user.id)
    await message.reply_text(f"تعداد {n} مورد از صف شما حذف شد.")


@app.on_message(filters.private & filters.command("del"))
async def del_handler(_, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("استفاده: `/del <job_id>`")
        return
    job_id = parts[1].strip()
    cancelled = await data.cancel_task(job_id)
    if cancelled:
        await message.reply_text("از صف حذف شد.")
    else:
        await message.reply_text("دستور لغو ثبت شد. اگر در حال آپلود است، در اولین فرصت متوقف می‌شود.")


# ----------------------------- inline callbacks (menus) -----------------------------

@app.on_callback_query(filters.regex(r"^me:"))
async def me_callbacks(_, cb: CallbackQuery):
    action = cb.data.split(":", 1)[1]
    user = await data.get_or_create_user(
        cb.from_user.id, cb.from_user.first_name or "", cb.from_user.username or ""
    )
    if action == "profile":
        await cb.message.edit_text(
            await render_profile_text(user),
            reply_markup=user_keyboard(is_admin(cb.from_user.id)),
        )
    elif action == "files":
        files = await data.list_user_files(cb.from_user.id, limit=10)
        if not files:
            text = "هنوز فایلی آپلود نکرده‌اید."
        else:
            lines = ["📂 **آخرین فایل‌های شما:**\n"]
            rubika_username = f"@{config.RUBIKA_ACCOUNT_USERNAME}" if config.RUBIKA_ACCOUNT_USERNAME else "اکانت روبیکا"
            for f in files:
                exp = fmt_datetime(f.get("expires_at")) if f.get("expires_at") else "بدون انقضا"
                lines.append(
                    f"• `{f['code']}` — {f['file_name']} ({pretty_size(f['file_size'])})\n"
                    f"   ساخته شده: {fmt_datetime(f['created_at'])} | انقضا: {exp}\n"
                )
            lines.append(f"\nبرای دریافت، کد را در روبیکا برای **{rubika_username}** بفرستید.")
            text = "\n".join(lines)
        await cb.message.edit_text(text, reply_markup=user_keyboard(is_admin(cb.from_user.id)))
    elif action == "plans":
        await cb.message.edit_text(plans_text(), reply_markup=user_keyboard(is_admin(cb.from_user.id)))
    elif action == "help":
        await cb.message.edit_text(HELP_TEXT, reply_markup=user_keyboard(is_admin(cb.from_user.id)))
    await cb.answer()


# ----------------------------- file & URL handlers -----------------------------

async def download_progress(current, total, status_message, file_name, started_at, state):
    now_ts = time.time()
    if now_ts - state.get("last_update", 0) < 3 and current < total:
        return
    state["last_update"] = now_ts
    percent = current * 100 / total if total else 0
    elapsed = max(now_ts - started_at, 1)
    speed = current / elapsed
    eta = (total - current) / speed if speed else None
    text = (
        f"📥 در حال دریافت فایل از تلگرام\n\n"
        f"فایل: `{file_name}`\n"
        f"حجم: `{pretty_size(total)}`\n"
        f"پیشرفت: `{percent:.1f}%`\n"
        f"`{progress_bar(percent)}`\n"
        f"سرعت: `{pretty_size(speed)}/s`\n"
        f"زمان باقی‌مانده: `{eta_text(eta)}`"
    )
    try:
        await status_message.edit_text(text)
    except Exception:
        pass


async def _enqueue_file(message: Message, user: dict, local_path: Path,
                       file_name: str, file_size: int, status_msg: Message,
                       caption: str = "") -> None:
    plan = config.PLANS.get(user.get("plan", config.DEFAULT_PLAN), config.PLANS[config.DEFAULT_PLAN])
    task = {
        "type": "local_file",
        "path": str(local_path),
        "caption": caption,
        "chat_id": message.chat.id,
        "status_message_id": status_msg.id,
        "tg_user_id": user["tg_user_id"],
        "file_name": file_name,
        "file_size": int(file_size),
        "file_expiry_days": int(plan["file_expiry_days"]),
    }
    job_id = await data.push_task(task)
    await status_msg.edit_text(
        f"✅ در صف آپلود قرار گرفت.\n\n"
        f"📄 فایل: `{file_name}`\n"
        f"📦 حجم: `{pretty_size(file_size)}`\n"
        f"🆔 شناسه: `{job_id}`\n\n"
        f"برای لغو: `/del {job_id}`"
    )


@app.on_message(
    filters.private
    & (
        filters.document | filters.video | filters.audio | filters.voice
        | filters.photo | filters.animation | filters.video_note | filters.sticker
    )
)
async def media_handler(client: Client, message: Message):
    user = await data.get_or_create_user(
        message.from_user.id, message.from_user.first_name or "", message.from_user.username or ""
    )

    media_type, media = get_media(message)
    if not media:
        await message.reply_text("فایل قابل پردازش نیست.")
        return

    size = int(getattr(media, "file_size", 0) or 0)
    ok, reason = await data.can_upload(user, size)
    if not ok:
        await message.reply_text(f"⚠️ {reason}")
        return

    download_name = build_download_filename(message, media_type, media)
    download_path = unique_path(config.DOWNLOAD_DIR / download_name)

    status = await message.reply_text(
        f"📥 آماده‌سازی دریافت `{download_name}` از تلگرام..."
    )

    try:
        started_at = time.time()
        progress_state = {"last_update": 0}
        downloaded = await client.download_media(
            message,
            file_name=str(download_path),
            progress=download_progress,
            progress_args=(status, download_name, started_at, progress_state),
        )
        if not downloaded:
            raise RuntimeError("دانلود از تلگرام انجام نشد.")
        path = Path(downloaded)
        if not path.exists():
            raise RuntimeError("فایل دانلودشده یافت نشد.")
        actual_size = path.stat().st_size
        await _enqueue_file(
            message, user, path, download_name, actual_size, status,
            caption=message.caption or "",
        )
    except Exception as e:
        await status.edit_text(f"❌ خطا: {e}")


@app.on_message(filters.private & filters.text
                & ~filters.command(["start", "help", "profile", "plans", "myfiles",
                                    "del", "delall", "admin", "grant", "revoke",
                                    "block", "unblock", "broadcast", "users",
                                    "stats", "setchannel"]))
async def text_handler(_, message: Message):
    # Admins might be in the middle of supplying input for a flow
    state = PENDING_STATE.get(message.from_user.id)
    if state:
        await _handle_pending_state(message, state)
        return

    text = message.text or ""
    url = extract_first_url(text)
    if not url:
        await message.reply_text("لطفاً یک فایل ارسال کنید یا لینک مستقیم بدهید.\nبرای راهنما: /help")
        return

    user = await data.get_or_create_user(
        message.from_user.id, message.from_user.first_name or "", message.from_user.username or ""
    )
    # We don't know the size in advance; let the worker enforce limits after HEAD/GET start.
    plan = config.PLANS.get(user.get("plan", config.DEFAULT_PLAN), config.PLANS[config.DEFAULT_PLAN])

    status = await message.reply_text("🔗 لینک دریافت شد. در صف دانلود قرار گرفت...")
    task = {
        "type": "direct_url",
        "url": url,
        "chat_id": message.chat.id,
        "status_message_id": status.id,
        "tg_user_id": user["tg_user_id"],
        "file_expiry_days": int(plan["file_expiry_days"]),
        "max_file_bytes": mb_to_bytes(plan["max_file_mb"]),
    }
    job_id = await data.push_task(task)
    await status.edit_text(
        f"🔗 لینک در صف قرار گرفت.\n\n🆔 شناسه: `{job_id}`\n\nبرای لغو: `/del {job_id}`"
    )


# ----------------------------- Admin Panel -----------------------------

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 آمار کلی", callback_data="admin:stats"),
            InlineKeyboardButton("👥 کاربران", callback_data="admin:users"),
        ],
        [
            InlineKeyboardButton("💎 فعال‌سازی اشتراک", callback_data="admin:grant"),
            InlineKeyboardButton("⛔ مسدودسازی", callback_data="admin:block"),
        ],
        [
            InlineKeyboardButton("📢 پیام همگانی", callback_data="admin:broadcast"),
            InlineKeyboardButton("📺 تنظیم چنل روبیکا", callback_data="admin:setchannel"),
        ],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="me:profile")],
    ])


def plan_picker_keyboard(target_user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for key, plan in config.PLANS.items():
        rows.append([InlineKeyboardButton(
            f"{plan['label']} ({plan['duration_days']} روز)",
            callback_data=f"admin:grant_apply:{target_user_id}:{key}",
        )])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


async def _handle_pending_state(message: Message, state: dict) -> None:
    kind = state.get("kind")
    user_id = message.from_user.id

    if kind == "grant_pick_user":
        try:
            target = int(message.text.strip())
        except Exception:
            await message.reply_text("شناسه کاربری معتبر نیست.")
            return
        PENDING_STATE.pop(user_id, None)
        await message.reply_text(
            f"یک پلن برای کاربر `{target}` انتخاب کنید:",
            reply_markup=plan_picker_keyboard(target),
        )
        return

    if kind == "block":
        action = state.get("action")
        try:
            target = int(message.text.strip())
        except Exception:
            await message.reply_text("شناسه کاربری معتبر نیست.")
            return
        await data.set_blocked(target, action == "block")
        PENDING_STATE.pop(user_id, None)
        await message.reply_text(
            f"{'⛔ کاربر مسدود شد' if action == 'block' else '✅ کاربر آزاد شد'}: `{target}`"
        )
        return

    if kind == "broadcast":
        text = message.text or ""
        PENDING_STATE.pop(user_id, None)
        sent, failed = 0, 0
        users = await data.list_users(limit=100000)
        notice = await message.reply_text(f"🔄 در حال ارسال به {len(users)} کاربر...")
        for u in users:
            try:
                await app.send_message(u["tg_user_id"], text)
                sent += 1
            except Exception:
                failed += 1
            if sent % 25 == 0:
                try:
                    await notice.edit_text(f"🔄 ارسال: {sent} موفق / {failed} ناموفق")
                except Exception:
                    pass
            await asyncio.sleep(0.05)
        await notice.edit_text(f"✅ پیام همگانی ارسال شد.\nموفق: {sent} | ناموفق: {failed}")
        return

    if kind == "setchannel":
        guid = (message.text or "").strip()
        if not guid:
            await message.reply_text("شناسه نامعتبر است.")
            return
        await data.set_setting("storage_channel_guid", guid)
        PENDING_STATE.pop(user_id, None)
        await message.reply_text(f"✅ چنل ذخیره‌سازی تنظیم شد:\n`{guid}`")
        return


@app.on_callback_query(filters.regex(r"^admin:"))
async def admin_callbacks(_, cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("اجازه دسترسی ندارید.", show_alert=True)
        return

    parts = cb.data.split(":")
    action = parts[1]

    if action == "home":
        await cb.message.edit_text("🛠 **پنل ادمین**\nاز منوی زیر یکی را انتخاب کنید:",
                                   reply_markup=admin_keyboard())
        await cb.answer()
        return

    if action == "stats":
        users_cnt = await data.count_users()
        files_cnt = await data.count_files()
        total_size = await data.total_storage_bytes()
        storage = await data.get_storage_channel_guid()
        await cb.message.edit_text(
            "📊 **آمار کلی ربات**\n\n"
            f"• تعداد کاربران: `{users_cnt}`\n"
            f"• تعداد فایل‌های فعال: `{files_cnt}`\n"
            f"• مجموع حجم ذخیره‌شده: `{pretty_size(total_size)}`\n"
            f"• چنل ذخیره روبیکا: `{storage or '— تنظیم نشده —'}`",
            reply_markup=admin_keyboard(),
        )
        await cb.answer()
        return

    if action == "users":
        users = await data.list_users(limit=20)
        if not users:
            text = "هیچ کاربری ثبت نشده."
        else:
            lines = ["👥 **آخرین کاربران**\n"]
            for u in users:
                plan_lbl = config.PLANS.get(u.get("plan"), {}).get("label", u.get("plan"))
                lines.append(
                    f"• `{u['tg_user_id']}` — {u.get('first_name') or '—'} "
                    f"({'@'+u['username'] if u.get('username') else '—'}) | "
                    f"پلن: {plan_lbl} | حجم ماه: {pretty_size(u.get('used_bytes_month') or 0)}"
                    + (" | ⛔ مسدود" if u.get("blocked") else "")
                )
            text = "\n".join(lines)
        await cb.message.edit_text(text, reply_markup=admin_keyboard())
        await cb.answer()
        return

    if action == "grant":
        PENDING_STATE[cb.from_user.id] = {"kind": "grant_pick_user"}
        await cb.message.edit_text(
            "💎 **فعال‌سازی اشتراک**\n\nشناسه عددی تلگرام کاربر را ارسال کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin:home")]]),
        )
        await cb.answer()
        return

    if action == "grant_apply" and len(parts) >= 4:
        target = int(parts[2])
        plan_key = parts[3]
        if plan_key not in config.PLANS:
            await cb.answer("پلن نامعتبر", show_alert=True)
            return
        await data.set_plan(target, plan_key)
        plan = config.PLANS[plan_key]
        await cb.message.edit_text(
            f"✅ اشتراک **{plan['label']}** برای کاربر `{target}` فعال شد "
            f"(مدت {plan['duration_days']} روز).",
            reply_markup=admin_keyboard(),
        )
        try:
            await app.send_message(
                target,
                f"🎉 اشتراک **{plan['label']}** برای حساب شما فعال شد!\n"
                f"📅 اعتبار: {plan['duration_days']} روز\n"
                f"📦 حجم ماهانه: {plan['monthly_quota_mb']} مگابایت\n"
                f"📎 حداکثر حجم هر فایل: {plan['max_file_mb']} مگابایت",
            )
        except Exception:
            pass
        await cb.answer("فعال شد")
        return

    if action == "block":
        await cb.message.edit_text(
            "⛔ **مدیریت دسترسی**\nیکی را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⛔ مسدودسازی کاربر", callback_data="admin:block_ask:block")],
                [InlineKeyboardButton("✅ آزادسازی کاربر", callback_data="admin:block_ask:unblock")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")],
            ]),
        )
        await cb.answer()
        return

    if action == "block_ask" and len(parts) >= 3:
        PENDING_STATE[cb.from_user.id] = {"kind": "block", "action": parts[2]}
        await cb.message.edit_text(
            "شناسه عددی تلگرام کاربر را ارسال کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin:home")]]),
        )
        await cb.answer()
        return

    if action == "broadcast":
        PENDING_STATE[cb.from_user.id] = {"kind": "broadcast"}
        await cb.message.edit_text(
            "📢 **پیام همگانی**\n\nمتن پیام را ارسال کنید (مارک‌داون پشتیبانی می‌شود).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin:home")]]),
        )
        await cb.answer()
        return

    if action == "setchannel":
        PENDING_STATE[cb.from_user.id] = {"kind": "setchannel"}
        cur = await data.get_storage_channel_guid()
        await cb.message.edit_text(
            "📺 **تنظیم چنل ذخیره‌سازی روبیکا**\n\n"
            f"فعلی: `{cur or '— تنظیم نشده —'}`\n\n"
            "شناسه (object_guid) چنل خصوصی روبیکا را ارسال کنید (معمولاً با `c0` شروع می‌شود).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin:home")]]),
        )
        await cb.answer()
        return


# Admin shortcut commands (text-based) for convenience -------------

@app.on_message(filters.private & filters.command("admin"))
async def admin_home_cmd(_, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("اجازه دسترسی ندارید.")
        return
    await message.reply_text("🛠 **پنل ادمین**\nاز منوی زیر یکی را انتخاب کنید:",
                             reply_markup=admin_keyboard())


@app.on_message(filters.private & filters.command("grant"))
async def grant_cmd(_, message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.reply_text("استفاده: `/grant <tg_user_id> <plan> [days]`\n"
                                 f"پلن‌های مجاز: {', '.join(config.PLANS.keys())}")
        return
    try:
        target = int(parts[1])
    except Exception:
        await message.reply_text("شناسه نامعتبر.")
        return
    plan_key = parts[2]
    if plan_key not in config.PLANS:
        await message.reply_text("پلن نامعتبر.")
        return
    days = int(parts[3]) if len(parts) >= 4 else None
    user = await data.set_plan(target, plan_key, duration_days=days)
    plan = config.PLANS[plan_key]
    await message.reply_text(
        f"✅ اشتراک **{plan['label']}** برای `{target}` تا "
        f"`{fmt_datetime(user.get('plan_expires_at'))}` فعال شد."
    )
    try:
        await app.send_message(
            target,
            f"🎉 اشتراک **{plan['label']}** برای حساب شما فعال شد!",
        )
    except Exception:
        pass


@app.on_message(filters.private & filters.command("block"))
async def block_cmd(_, message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply_text("استفاده: `/block <tg_user_id>`")
        return
    await data.set_blocked(int(parts[1]), True)
    await message.reply_text(f"⛔ کاربر `{parts[1]}` مسدود شد.")


@app.on_message(filters.private & filters.command("unblock"))
async def unblock_cmd(_, message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply_text("استفاده: `/unblock <tg_user_id>`")
        return
    await data.set_blocked(int(parts[1]), False)
    await message.reply_text(f"✅ کاربر `{parts[1]}` آزاد شد.")


@app.on_message(filters.private & filters.command("setchannel"))
async def setchannel_cmd(_, message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        cur = await data.get_storage_channel_guid()
        await message.reply_text(f"چنل فعلی: `{cur or '— تنظیم نشده —'}`\nاستفاده: `/setchannel <guid>`")
        return
    await data.set_setting("storage_channel_guid", parts[1].strip())
    await message.reply_text(f"✅ چنل ذخیره‌سازی روبیکا تنظیم شد:\n`{parts[1].strip()}`")


@app.on_message(filters.private & filters.command("stats"))
async def stats_cmd(_, message: Message):
    if not is_admin(message.from_user.id):
        return
    users_cnt = await data.count_users()
    files_cnt = await data.count_files()
    total_size = await data.total_storage_bytes()
    storage = await data.get_storage_channel_guid()
    await message.reply_text(
        "📊 **آمار کلی ربات**\n\n"
        f"• کاربران: `{users_cnt}`\n"
        f"• فایل‌های فعال: `{files_cnt}`\n"
        f"• حجم کل: `{pretty_size(total_size)}`\n"
        f"• چنل ذخیره: `{storage or '— تنظیم نشده —'}`"
    )


# ----------------------------- Status watcher -----------------------------

async def status_watcher():
    """Poll the DB for status updates pushed by the rubika worker and edit chat messages."""
    while True:
        try:
            batch = await data.pop_pending_status_batch(limit=25)
            for s in batch:
                chat_id = s.get("chat_id")
                msg_id = s.get("message_id")
                text = s.get("text") or ""
                percent = s.get("percent")
                if not chat_id or not msg_id:
                    continue
                if percent is not None:
                    text += f"\n\n`{progress_bar(float(percent))}` `{float(percent):.1f}%`"
                try:
                    await app.edit_message_text(chat_id, msg_id, text)
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(1)


# ----------------------------- entry -----------------------------

async def main():
    await data.ensure_indexes()
    await app.start()
    print("[Telegram] bot started")
    app.loop.create_task(status_watcher())
    await idle()
    await app.stop()


if __name__ == "__main__":
    if not (config.API_ID and config.API_HASH and config.BOT_TOKEN):
        raise SystemExit("لطفاً API_ID, API_HASH و BOT_TOKEN را در .env تنظیم کنید.")
    asyncio.run(main())
