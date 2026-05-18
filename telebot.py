import os
import re
import time
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message

load_dotenv()

from config import (
    API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS,
    DOWNLOAD_DIR, BASE_DIR, PLANS, MAX_FILE_SIZE
)
import database as db

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("API_ID, API_HASH, BOT_TOKEN must be set in .env")

app = Client(
    str(BASE_DIR / "tg_bot_session"),
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


def is_admin(telegram_id):
    if telegram_id in ADMIN_IDS:
        return True
    user = db.get_user_by_telegram_id(telegram_id)
    return user and user.get('is_admin')


def pretty_size(size):
    size = float(size or 0)
    units = ["B", "KB", "MB", "GB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"


def safe_filename(name):
    name = (name or "file.bin").strip()
    name = re.sub(r'[<>:"/\\|?*-\x1F]', "_", name)
    name = name.rstrip(". ")
    return name[:200] or "file.bin"


def progress_bar(percent, length=12):
    filled = int(length * percent / 100)
    return "\u2588" * filled + "\u2591" * (length - filled)


# ─── /start ───
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message: Message):
    user, is_new = db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )

    if is_new:
        text = (
            f"سلام {message.from_user.first_name} عزیز، خوش آمدید!\n\n"
            f"شما با موفقیت ثبت‌نام شدید.\n\n"
        )
    else:
        text = f"سلام {message.from_user.first_name}!\n\n"

    text += (
        "این ربات به شما امکان دریافت فایل از تلگرام در روبیکا را می‌دهد.\n\n"
        "دستورات:\n"
        "/profile - مشاهده پروفایل\n"
        "/plans - مشاهده پلن‌های اشتراک\n"
        "/link - دریافت کد لینک روبیکا\n"
        "/mydownloads - تاریخچه دانلودها\n"
        "/help - راهنما\n"
    )

    if is_admin(message.from_user.id):
        text += (
            "\n--- پنل ادمین ---\n"
            "فایل یا فوروارد ارسال کنید تا کد یونیک ساخته شود\n"
            "/stats - آمار سیستم\n"
            "/approve <user_id> <plan_id> - تایید اشتراک\n"
            "/addadmin <user_id> - افزودن ادمین\n"
        )

    await message.reply_text(text)


# ─── /profile ───
@app.on_message(filters.private & filters.command("profile"))
async def profile_handler(client, message: Message):
    user, _ = db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )
    sub = db.get_active_subscription(user['id'])

    text = (
        f"پروفایل شما:\n\n"
        f"نام: {user.get('first_name', '-')}\n"
        f"یوزرنیم: @{user.get('username', '-')}\n"
        f"شناسه تلگرام: `{user['telegram_id']}`\n"
        f"وضعیت لینک روبیکا: {'متصل' if user['is_linked'] else 'متصل نیست'}\n"
        f"کد لینک: `{user['link_code']}`\n"
    )

    if sub:
        plan = PLANS.get(sub['plan_id'], {})
        remaining = max(0, sub['volume_limit'] - sub['volume_used'])
        used_percent = (sub['volume_used'] / sub['volume_limit'] * 100) if sub['volume_limit'] > 0 else 0

        text += (
            f"\n--- اشتراک فعال ---\n"
            f"پلن: {plan.get('name', 'نامشخص')}\n"
            f"حجم کل: {pretty_size(sub['volume_limit'])}\n"
            f"مصرف شده: {pretty_size(sub['volume_used'])} ({used_percent:.1f}%)\n"
            f"باقیمانده: {pretty_size(remaining)}\n"
            f"`{progress_bar(used_percent)}`\n"
            f"تاریخ انقضا: {sub['end_date'][:10]}\n"
        )
    else:
        text += "\nاشتراک فعالی ندارید. برای خرید: /plans\n"

    await message.reply_text(text)


# ─── /plans ───
@app.on_message(filters.private & filters.command("plans"))
async def plans_handler(client, message: Message):
    text = "پلن‌های اشتراک:\n(قیمت هر گیگابایت: ۲۵,۰۰۰ تومان)\n\n"

    for pid, plan in PLANS.items():
        text += (
            f"پلن {pid}: {plan['name']}\n"
            f"   حجم: {plan['volume_gb']} گیگابایت\n"
            f"   قیمت: {plan['price_toman']:,} تومان\n"
            f"   مدت: {plan['duration_days']} روز\n\n"
        )

    text += (
        "برای خرید اشتراک:\n"
        "۱. مبلغ را واریز کنید\n"
        "۲. رسید را به ادمین ارسال کنید\n"
        "۳. ادمین اشتراک شما را فعال می‌کند\n\n"
        "یا مستقیم با دستور زیر درخواست دهید:\n"
        "/subscribe <شماره_پلن>\n"
        "مثال: `/subscribe 2`"
    )

    await message.reply_text(text)


# ─── /subscribe ───
@app.on_message(filters.private & filters.command("subscribe"))
async def subscribe_handler(client, message: Message):
    user, _ = db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply_text("فرمت صحیح: /subscribe <شماره_پلن>\nمثال: `/subscribe 2`")
        return

    plan_id = int(parts[1])
    plan = PLANS.get(plan_id)
    if not plan:
        await message.reply_text("شماره پلن نامعتبر است. برای مشاهده پلن‌ها: /plans")
        return

    await message.reply_text(
        f"درخواست خرید پلن {plan['name']} ثبت شد.\n\n"
        f"مبلغ: {plan['price_toman']:,} تومان\n\n"
        f"لطفا مبلغ را واریز کرده و رسید را به ادمین ارسال کنید.\n"
        f"شناسه شما: `{user['telegram_id']}`\n"
        f"شماره پلن: `{plan_id}`\n\n"
        f"ادمین با دستور زیر اشتراک شما را فعال می‌کند:\n"
        f"`/approve {user['telegram_id']} {plan_id}`"
    )


# ─── /link ───
@app.on_message(filters.private & filters.command("link"))
async def link_handler(client, message: Message):
    user, _ = db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )

    if user['is_linked']:
        await message.reply_text(
            "حساب روبیکای شما قبلا لینک شده است.\n"
            "اگر نیاز به تغییر دارید با ادمین تماس بگیرید."
        )
        return

    await message.reply_text(
        f"کد لینک روبیکای شما:\n\n"
        f"`{user['link_code']}`\n\n"
        f"این کد را به حساب روبیکای ربات ارسال کنید تا حساب‌های شما لینک شوند.\n\n"
        f"مراحل:\n"
        f"۱. وارد روبیکا شوید\n"
        f"۲. به حساب ربات پیام دهید\n"
        f"۳. کد بالا را ارسال کنید\n"
        f"۴. حساب‌ها لینک می‌شوند"
    )


# ─── /mydownloads ───
@app.on_message(filters.private & filters.command("mydownloads"))
async def mydownloads_handler(client, message: Message):
    user, _ = db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )

    downloads = db.get_user_downloads(user['id'])
    if not downloads:
        await message.reply_text("هنوز دانلودی نداشتید.")
        return

    text = "آخرین دانلودهای شما:\n\n"
    for dl in downloads:
        text += (
            f"کد: `{dl['unique_code']}`\n"
            f"فایل: {dl['file_name']}\n"
            f"حجم: {pretty_size(dl['file_size'])}\n"
            f"تاریخ: {dl['downloaded_at'][:16]}\n"
            f"---\n"
        )

    await message.reply_text(text)


# ─── /help ───
@app.on_message(filters.private & filters.command("help"))
async def help_handler(client, message: Message):
    text = (
        "راهنمای ربات:\n\n"
        "این ربات فایل‌ها را از تلگرام به روبیکا منتقل می‌کند.\n\n"
        "مراحل استفاده:\n"
        "۱. ثبت‌نام با /start\n"
        "۲. خرید اشتراک با /plans\n"
        "۳. لینک حساب روبیکا با /link\n"
        "۴. کد فایل را به ربات روبیکا ارسال کنید\n"
        "۵. فایل در روبیکا دریافت کنید\n\n"
        "دستورات:\n"
        "/start - شروع و ثبت‌نام\n"
        "/profile - پروفایل\n"
        "/plans - پلن‌های اشتراک\n"
        "/subscribe <پلن> - درخواست خرید\n"
        "/link - کد لینک روبیکا\n"
        "/mydownloads - تاریخچه دانلود\n"
        "/help - همین راهنما\n"
    )

    await message.reply_text(text)


# ─── Admin: /approve ───
@app.on_message(filters.private & filters.command("approve"))
async def approve_handler(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("شما دسترسی ادمین ندارید.")
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text("فرمت: /approve <telegram_id> <plan_id>")
        return

    try:
        target_tid = int(parts[1])
        plan_id = int(parts[2])
    except ValueError:
        await message.reply_text("شناسه و شماره پلن باید عدد باشند.")
        return

    target_user = db.get_user_by_telegram_id(target_tid)
    if not target_user:
        await message.reply_text("کاربر یافت نشد.")
        return

    plan = PLANS.get(plan_id)
    if not plan:
        await message.reply_text("پلن نامعتبر.")
        return

    sub, err = db.create_subscription(target_user['id'], plan_id)
    if err:
        await message.reply_text(f"خطا: {err}")
        return

    await message.reply_text(
        f"اشتراک فعال شد!\n\n"
        f"کاربر: {target_user.get('first_name', '-')} ({target_tid})\n"
        f"پلن: {plan['name']}\n"
        f"حجم: {plan['volume_gb']} گیگابایت\n"
        f"تا تاریخ: {sub['end_date'][:10]}"
    )

    # Notify user
    try:
        await client.send_message(
            target_tid,
            f"اشتراک شما فعال شد!\n\n"
            f"پلن: {plan['name']}\n"
            f"حجم: {plan['volume_gb']} گیگابایت\n"
            f"تا تاریخ: {sub['end_date'][:10]}\n\n"
            f"اگر هنوز روبیکا را لینک نکردید: /link"
        )
    except Exception:
        pass


# ─── Admin: /addadmin ───
@app.on_message(filters.private & filters.command("addadmin"))
async def addadmin_handler(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("شما دسترسی ادمین ندارید.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("فرمت: /addadmin <telegram_id>")
        return

    try:
        target_tid = int(parts[1])
    except ValueError:
        await message.reply_text("شناسه باید عدد باشد.")
        return

    target_user = db.get_user_by_telegram_id(target_tid)
    if not target_user:
        await message.reply_text("کاربر یافت نشد. ابتدا باید /start بزند.")
        return

    db.set_admin(target_tid, True)
    await message.reply_text(f"کاربر {target_user.get('first_name', '-')} ({target_tid}) ادمین شد.")


# ─── Admin: /stats ───
@app.on_message(filters.private & filters.command("stats"))
async def stats_handler(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("شما دسترسی ادمین ندارید.")
        return

    total_users = db.get_all_users_count()
    active_subs = db.get_active_subscriptions_count()
    total_uploads = db.get_uploads_count()
    total_downloads = db.get_downloads_count()
    total_volume = db.get_total_download_volume()

    text = (
        "آمار سیستم:\n\n"
        f"کل کاربران: {total_users}\n"
        f"اشتراک فعال: {active_subs}\n"
        f"تعداد آپلودها: {total_uploads}\n"
        f"تعداد دانلودها: {total_downloads}\n"
        f"حجم کل دانلود شده: {pretty_size(total_volume)}\n"
    )

    await message.reply_text(text)


# ─── Admin: File Upload Handler ───
@app.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.voice
        | filters.photo
        | filters.animation
        | filters.video_note
    )
)
async def file_upload_handler(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("فقط ادمین‌ها می‌توانند فایل آپلود کنند.")
        return

    # Detect media type and get file info
    media_type, media = get_media(message)
    if not media:
        await message.reply_text("فایل قابل پردازش نیست.")
        return

    file_size = getattr(media, 'file_size', 0) or 0
    file_name = getattr(media, 'file_name', None)

    if not file_name:
        file_unique_id = getattr(media, 'file_unique_id', None) or "file"
        ext_map = {
            "document": ".bin", "video": ".mp4", "audio": ".mp3",
            "voice": ".ogg", "photo": ".jpg", "animation": ".mp4",
            "video_note": ".mp4",
        }
        file_name = f"{file_unique_id}{ext_map.get(media_type, '.bin')}"

    file_name = safe_filename(file_name)

    if file_size > MAX_FILE_SIZE:
        await message.reply_text(f"حجم فایل بیشتر از حد مجاز ({pretty_size(MAX_FILE_SIZE)}) است.")
        return

    status = await message.reply_text("در حال دانلود فایل...")

    try:
        # Create unique download path
        unique_name = f"{int(time.time())}_{message.id}_{file_name}"
        download_path = DOWNLOAD_DIR / unique_name

        started_at = time.time()
        progress_state = {"last_update": 0}

        downloaded = await client.download_media(
            message,
            file_name=str(download_path),
            progress=download_progress_callback,
            progress_args=(status, file_name, started_at, progress_state),
        )

        if not downloaded:
            raise RuntimeError("دانلود ناموفق بود.")

        downloaded_path = Path(downloaded)
        actual_size = downloaded_path.stat().st_size

        # Register upload in database
        upload = db.create_upload(
            file_path=str(downloaded_path),
            file_name=file_name,
            file_size=actual_size,
            file_type=media_type,
            caption=message.caption or "",
            chat_id=message.chat.id,
            message_id=message.id,
            uploaded_by=message.from_user.id
        )

        await status.edit_text(
            f"فایل با موفقیت ثبت شد!\n\n"
            f"فایل: `{file_name}`\n"
            f"حجم: {pretty_size(actual_size)}\n"
            f"کد یونیک: `{upload['unique_code']}`\n\n"
            f"این کد را در اختیار کاربران قرار دهید.\n"
            f"کاربران با ارسال این کد به ربات روبیکا فایل را دریافت می‌کنند."
        )

    except Exception as e:
        await status.edit_text(f"خطا: {str(e)}")


def get_media(message: Message):
    media_types = [
        ("document", message.document),
        ("video", message.video),
        ("audio", message.audio),
        ("voice", message.voice),
        ("photo", message.photo),
        ("animation", message.animation),
        ("video_note", message.video_note),
    ]
    for mtype, media in media_types:
        if media:
            return mtype, media
    return None, None


async def download_progress_callback(current, total, status_message, file_name, started_at, state):
    now = time.time()
    if now - state.get("last_update", 0) < 3 and current < total:
        return
    state["last_update"] = now

    percent = current * 100 / total if total else 0
    elapsed = max(now - started_at, 1)
    speed = current / elapsed

    text = (
        f"در حال دانلود...\n\n"
        f"فایل: `{file_name}`\n"
        f"حجم: {pretty_size(total)}\n"
        f"پیشرفت: {percent:.1f}%\n"
        f"`{progress_bar(percent)}`\n"
        f"سرعت: {pretty_size(speed)}/s"
    )

    try:
        await status_message.edit_text(text)
    except Exception:
        pass


if __name__ == "__main__":
    print("Telegram bot starting...")
    app.run()


