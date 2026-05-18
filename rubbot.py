import os
import sys
import time
import asyncio
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import RUBIKA_SESSION, BASE_DIR, DOWNLOAD_DIR
import database as db

try:
    from rubpy import Client, filters
    from rubpy.types import Update
except ImportError:
    print("rubpy not installed. Run: pip install rubpy")
    sys.exit(1)


bot = Client(name=str(BASE_DIR / RUBIKA_SESSION))


def pretty_size(size):
    size = float(size or 0)
    units = ["B", "KB", "MB", "GB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"


def get_text(update):
    """Extract text from rubpy Update object (defensive)"""
    for attr in ['text', 'raw_text']:
        val = getattr(update, attr, None)
        if val:
            return str(val).strip()
    msg = getattr(update, 'message', None)
    if msg:
        for attr in ['text', 'raw_text']:
            val = getattr(msg, attr, None)
            if val:
                return str(val).strip()
    return ""


def get_user_guid(update):
    """Extract user GUID from rubpy Update object (defensive)"""
    for attr in ['object_guid', 'author_object_guid', 'author_guid']:
        val = getattr(update, attr, None)
        if val:
            return str(val)
    msg = getattr(update, 'message', None)
    if msg:
        for attr in ['author_object_guid', 'object_guid']:
            val = getattr(msg, attr, None)
            if val:
                return str(val)
    return None


@bot.on_message_updates(filters.text)
async def message_handler(update: Update):
    try:
        text = get_text(update)
        user_guid = get_user_guid(update)

        if not text or not user_guid:
            return

        # Skip own messages
        if user_guid == "me":
            return

        text = text.strip()

        # ─── Link Account ───
        if text.upper().startswith("LNK"):
            await handle_link(update, user_guid, text.upper())
            return

        # ─── Help Command ───
        if text in ["/start", "start", "شروع", "سلام"]:
            await handle_start(update, user_guid)
            return

        if text in ["/help", "help", "راهنما"]:
            await handle_help(update)
            return

        if text in ["/profile", "profile", "پروفایل"]:
            await handle_profile(update, user_guid)
            return

        # ─── File Code ───
        if len(text) == 8 and text.isalnum():
            await handle_file_code(update, user_guid, text.upper())
            return

        # ─── Unknown Message ───
        await update.reply(
            "سلام! من ربات انتقال فایل هستم.\n\n"
            "برای لینک حساب: کد لینک خود را ارسال کنید (مثلا: LNKA3B7C)\n"
            "برای دریافت فایل: کد ۸ رقمی فایل را ارسال کنید\n\n"
            "دستورات:\n"
            "/start - شروع\n"
            "/profile - پروفایل\n"
            "/help - راهنما"
        )

    except Exception as e:
        print(f"Handler error: {e}")
        traceback.print_exc()
        try:
            await update.reply("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        except Exception:
            pass


async def handle_start(update, user_guid):
    user = db.get_user_by_rubika_guid(user_guid)

    if user:
        sub = db.get_active_subscription(user['id'])
        text = (
            f"خوش آمدید {user.get('first_name', '')}!\n\n"
            f"حساب شما لینک شده است.\n"
        )
        if sub:
            remaining = max(0, sub['volume_limit'] - sub['volume_used'])
            text += f"حجم باقیمانده: {pretty_size(remaining)}\n"
        text += "\nبرای دریافت فایل، کد ۸ رقمی را ارسال کنید."
    else:
        text = (
            "سلام! من ربات انتقال فایل از تلگرام به روبیکا هستم.\n\n"
            "مراحل:\n"
            "۱. ابتدا در ربات تلگرام ثبت‌نام کنید\n"
            "۲. کد لینک خود را از ربات تلگرام بگیرید (/link)\n"
            "۳. کد لینک را اینجا ارسال کنید تا حساب‌ها متصل شوند\n"
            "۴. کد فایل را ارسال کنید تا فایل دریافت کنید\n"
        )

    await update.reply(text)


async def handle_help(update):
    text = (
        "راهنمای ربات روبیکا:\n\n"
        "لینک حساب:\n"
        "کد لینک تلگرام خود را ارسال کنید (مثلا: LNKA3B7C)\n\n"
        "دریافت فایل:\n"
        "کد ۸ رقمی فایل را ارسال کنید\n\n"
        "مشاهده پروفایل:\n"
        "/profile یا پروفایل\n\n"
        "اگر هنوز ثبت‌نام نکردید، ابتدا در ربات تلگرام ثبت‌نام کنید."
    )
    await update.reply(text)


async def handle_profile(update, user_guid):
    user = db.get_user_by_rubika_guid(user_guid)
    if not user:
        await update.reply(
            "حساب شما لینک نشده.\n"
            "ابتدا در ربات تلگرام ثبت‌نام کنید و کد لینک بگیرید."
        )
        return

    sub = db.get_active_subscription(user['id'])

    text = (
        f"پروفایل:\n\n"
        f"نام: {user.get('first_name', '-')}\n"
        f"شناسه تلگرام: {user['telegram_id']}\n"
    )

    if sub:
        from config import PLANS
        plan = PLANS.get(sub['plan_id'], {})
        remaining = max(0, sub['volume_limit'] - sub['volume_used'])
        used_pct = (sub['volume_used'] / sub['volume_limit'] * 100) if sub['volume_limit'] > 0 else 0
        text += (
            f"\nاشتراک: {plan.get('name', 'نامشخص')}\n"
            f"حجم کل: {pretty_size(sub['volume_limit'])}\n"
            f"مصرف شده: {pretty_size(sub['volume_used'])} ({used_pct:.1f}%)\n"
            f"باقیمانده: {pretty_size(remaining)}\n"
            f"انقضا: {sub['end_date'][:10]}\n"
        )
    else:
        text += "\nاشتراک فعالی ندارید.\n"

    await update.reply(text)


async def handle_link(update, user_guid, code):
    user, error = db.link_rubika_account(code, user_guid)

    if error:
        await update.reply(f"خطا: {error}")
        return

    await update.reply(
        f"حساب با موفقیت لینک شد!\n\n"
        f"نام: {user.get('first_name', '-')}\n\n"
        f"حالا می‌توانید کد فایل‌ها را ارسال کنید تا فایل دریافت کنید."
    )


async def handle_file_code(update, user_guid, code):
    # Check if user is linked
    user = db.get_user_by_rubika_guid(user_guid)
    if not user:
        await update.reply(
            "ابتدا حساب خود را لینک کنید.\n"
            "کد لینک را از ربات تلگرام بگیرید و اینجا ارسال کنید."
        )
        return

    # Check subscription
    sub = db.get_active_subscription(user['id'])
    if not sub:
        await update.reply(
            "اشتراک فعالی ندارید.\n"
            "برای خرید اشتراک به ربات تلگرام مراجعه کنید."
        )
        return

    # Look up file
    upload = db.get_upload_by_code(code)
    if not upload:
        await update.reply("کد فایل نامعتبر است. لطفا کد را بررسی کنید.")
        return

    # Check volume
    remaining = sub['volume_limit'] - sub['volume_used']
    file_size = upload.get('file_size', 0)

    if file_size > remaining:
        await update.reply(
            f"حجم اشتراک شما کافی نیست.\n\n"
            f"حجم فایل: {pretty_size(file_size)}\n"
            f"حجم باقیمانده: {pretty_size(remaining)}\n\n"
            f"برای ارتقای اشتراک به ربات تلگرام مراجعه کنید."
        )
        return

    # Check file exists on disk
    file_path = Path(upload['file_path'])
    if not file_path.exists():
        await update.reply("فایل در سرور موجود نیست. لطفا با ادمین تماس بگیرید.")
        return

    # Send file
    await update.reply(
        f"در حال ارسال فایل...\n"
        f"فایل: {upload.get('file_name', '-')}\n"
        f"حجم: {pretty_size(file_size)}"
    )

    try:
        caption = upload.get('caption', '') or upload.get('file_name', '')
        await bot.send_document(
            user_guid,
            str(file_path),
            caption=caption
        )

        # Record download
        db.record_download(user['id'], upload['id'], file_size)
        db.update_volume_used(sub['id'], file_size)

        new_remaining = remaining - file_size
        await update.reply(
            f"فایل با موفقیت ارسال شد!\n\n"
            f"حجم باقیمانده: {pretty_size(new_remaining)}"
        )

    except Exception as e:
        print(f"Send error: {e}")
        traceback.print_exc()
        await update.reply(f"خطا در ارسال فایل: {str(e)}")


def ensure_session():
    """Check if Rubika session exists, if not prompt for login"""
    session_path = BASE_DIR / RUBIKA_SESSION
    candidates = [
        session_path,
        Path(f"{session_path}.session"),
        Path(f"{session_path}.sqlite"),
    ]

    if any(p.exists() for p in candidates):
        return True

    print("=" * 50)
    print("Session not found. First-time login required.")
    print("Please run this script directly for login:")
    print(f"  python {__file__}")
    print("=" * 50)
    return False


async def run_bot():
    """Start the Rubika bot"""
    print("Rubika bot starting...")
    try:
        await bot.start()
        print("Rubika bot connected and listening for messages.")
        # Keep running
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("Rubika bot stopping...")
    except Exception as e:
        print(f"Rubika bot error: {e}")
        traceback.print_exc()
    finally:
        try:
            await bot.disconnect()
        except Exception:
            pass

if __name__ == "__main__":

    if not ensure_session():
        print("Starting login process...")

        async def login():
            async with Client(name=str(BASE_DIR / RUBIKA_SESSION)) as c:
                me = await c.get_me()
                print(f"Logged in successfully.")
                print(me)

        asyncio.run(login())

        print("Session created successfully.")
        print("Restarting bot...\n")

    asyncio.run(run_bot())

