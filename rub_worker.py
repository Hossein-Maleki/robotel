# Now let me create the Rubika worker — most critical piece (uploads + listens for codes and forwards files):
# Action: file_editor create /app/bot/rub_worker.py --file-text """"
# Rubika worker for Tele2Rub Pro.

# Two coroutines run concurrently in the same rubpy Client:
# 1) `queue_consumer`: pulls pending tasks from MongoDB, downloads URLs (if needed),
#    uploads files to the private Rubika storage channel, generates a unique code,
#    notifies the Telegram bot.
# 2) `on_message_updates`: listens to private messages sent to the Rubika account,
#    parses an incoming code, looks it up, and forwards the original file message
#    from the storage channel back to the requester. The account acts as a self-bot.
# """
import asyncio
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from rubpy import Client as RubikaClient
from rubpy import filters as rub_filters

import config
import db as data
from utils import safe_filename, pretty_size, eta_text, unique_path


URL_DOWNLOAD_DIR = config.DOWNLOAD_DIR / "url"
URL_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------- utility -----------------------------

def get_per_attempt_timeout(file_path: str) -> int:
    size_mb = Path(file_path).stat().st_size / (1024 * 1024)
    if size_mb < 100:
        return 180
    if size_mb < 500:
        return 420
    if size_mb < 1000:
        return 720
    return 1200


async def _push(task: dict, text: str, percent: Optional[float] = None, status: str = "working"):
    chat_id = task.get("chat_id")
    msg_id = task.get("status_message_id")
    if chat_id and msg_id:
        await data.push_status(chat_id, msg_id, text, percent=percent, status=status)


# ----------------------------- URL download -----------------------------

async def _download_url(task: dict) -> Path:
    url = (task.get("url") or "").strip()
    if not url:
        raise RuntimeError("URL خالی است.")
    max_bytes = int(task.get("max_file_bytes") or 0)

    await _push(task, "📥 شروع دانلود از لینک ...", 0, "downloading")

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"دانلود انجام نشد. کد خطا: {resp.status}")
            cd = resp.headers.get("content-disposition", "") or ""
            m = re.findall(r'filename="?(.+?)"?(?:;|$)', cd)
            name = m[0] if m else Path(urlparse(url).path).name
            name = safe_filename(name or f"file_{int(time.time())}.bin")
            if "." not in name:
                name += ".bin"
            target = unique_path(URL_DOWNLOAD_DIR / name)

            total = int(resp.headers.get("content-length") or 0)
            if max_bytes and total and total > max_bytes:
                raise RuntimeError(
                    f"حجم فایل ({pretty_size(total)}) بیشتر از سقف مجاز پلن شماست."
                )

            downloaded, last_update, started = 0, 0.0, time.time()
            with open(target, "wb") as fh:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if max_bytes and downloaded > max_bytes:
                        try:
                            target.unlink()
                        except Exception:
                            pass
                        raise RuntimeError("حجم فایل از سقف مجاز پلن عبور کرد.")
                    now = time.time()
                    if now - last_update < 3 and (not total or downloaded < total):
                        continue
                    last_update = now
                    speed = downloaded / max(now - started, 1)
                    eta = (total - downloaded) / speed if total and speed else None
                    percent = downloaded * 100 / total if total else None
                    text = (
                        "📥 در حال دانلود از لینک ...\n"
                        f"`{pretty_size(downloaded)}`"
                        + (f" از `{pretty_size(total)}`" if total else "")
                        + f"\nسرعت: `{pretty_size(speed)}/s`"
                        + (f"\nزمان باقی‌مانده: `{eta_text(eta)}`" if eta else "")
                    )
                    await _push(task, text, percent, "downloading")
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("فایل دانلود نشد.")
    return target


# ----------------------------- Rubika upload -----------------------------

async def _send_with_retry(client: RubikaClient, channel_guid: str,
                           file_path: str, caption: str, task: dict):
    last_err = None
    started = time.time()
    for attempt in range(1, config.MAX_UPLOAD_RETRIES + 1):
        if await data.is_cancel_requested(task["job_id"]):
            raise RuntimeError("ارسال لغو شد.")
        if time.time() - started > config.UPLOAD_TOTAL_TIMEOUT:
            raise RuntimeError("آپلود بیشتر از حد مجاز طول کشید و لغو شد.")
        await _push(task, f"🔼 در حال آپلود در روبیکا (تلاش {attempt} از {config.MAX_UPLOAD_RETRIES})...",
                    None, "uploading")
        try:
            per_attempt = min(get_per_attempt_timeout(file_path), config.UPLOAD_TOTAL_TIMEOUT)
            return await asyncio.wait_for(
                client.send_document(channel_guid, file_path, caption=caption or ""),
                timeout=per_attempt,
            )
        except asyncio.TimeoutError as e:
            last_err = e
        except Exception as e:
            last_err = e
            text = str(e).lower()
            transient = any(k in text for k in [
                "502", "503", "bad gateway", "timeout", "cannot connect",
                "connection reset", "temporarily unavailable",
                "error uploading chunk", "unexpected mimetype",
            ])
            if not transient:
                # non-transient: still retry once more, then raise
                if attempt >= 2:
                    break
        await asyncio.sleep(3)
    raise last_err or RuntimeError("Upload failed.")


def _extract_message_id(result) -> Optional[str]:
    """rubpy's Update may expose message_id at different places. Try common ones."""
    for attr in ("message_id", "messageId"):
        v = getattr(result, attr, None)
        if v:
            return str(v)
    # update_message wrapper
    msg = getattr(result, "message", None)
    if msg is not None:
        v = getattr(msg, "message_id", None)
        if v:
            return str(v)
    # original_update dict access
    raw = getattr(result, "original_update", None) or {}
    if isinstance(raw, dict):
        for k in ("message_id", "messageId"):
            if raw.get(k):
                return str(raw[k])
        msg_update = raw.get("message_update") or {}
        if isinstance(msg_update, dict) and msg_update.get("message_id"):
            return str(msg_update["message_id"])
    # try __dict__ scan
    try:
        d = vars(result)
        for k, v in d.items():
            if "message_id" in k.lower() and v:
                return str(v)
    except Exception:
        pass
    return None


# ----------------------------- task processing -----------------------------

async def _process_task(client: RubikaClient, task: dict) -> None:
    job_id = task["job_id"]
    tg_user_id = int(task.get("tg_user_id") or 0)
    file_expiry_days = int(task.get("file_expiry_days") or 30)
    caption = task.get("caption", "")

    channel_guid = await data.get_storage_channel_guid()
    if not channel_guid:
        raise RuntimeError("ادمین هنوز چنل ذخیره‌سازی روبیکا را تنظیم نکرده است. لطفاً به ادمین اطلاع دهید.")

    local_path: Optional[Path] = None
    if task["type"] == "local_file":
        local_path = Path(task["path"])
        if not local_path.exists():
            raise RuntimeError("فایل محلی پیدا نشد.")
    elif task["type"] == "direct_url":
        local_path = await _download_url(task)
        # re-check the user's plan quota now that we know the size
        size = local_path.stat().st_size
        user = await data.get_or_create_user(tg_user_id)
        ok, reason = await data.can_upload(user, size)
        if not ok:
            try:
                local_path.unlink()
            except Exception:
                pass
            raise RuntimeError(reason)
        task["file_size"] = size
        task["file_name"] = local_path.name
    else:
        raise RuntimeError("نوع تسک ناشناخته است.")

    file_name = task.get("file_name") or local_path.name
    file_size = int(task.get("file_size") or local_path.stat().st_size)

    # Upload to Rubika storage channel
    upload_caption = f"📦 {file_name}\n👤 user: {tg_user_id}"
    if caption:
        upload_caption = caption + "\n\n" + upload_caption

    result = await _send_with_retry(client, channel_guid, str(local_path), upload_caption, task)
    message_id = _extract_message_id(result)
    if not message_id:
        raise RuntimeError("شناسه پیام روبیکا دریافت نشد. لطفاً دوباره تلاش کنید.")

    # Persist file record with unique code
    record = await data.create_file_record(
        tg_user_id=tg_user_id,
        file_name=file_name,
        file_size=file_size,
        rubika_message_id=message_id,
        channel_guid=channel_guid,
        caption=caption,
        expiry_days=file_expiry_days,
    )
    await data.add_usage(tg_user_id, file_size)

    rubika_acc = f"@{config.RUBIKA_ACCOUNT_USERNAME}" if config.RUBIKA_ACCOUNT_USERNAME else "اکانت روبیکای ربات"
    success_text = (
        "✅ فایل با موفقیت در روبیکا ذخیره شد!\n\n"
        f"📄 فایل: `{file_name}`\n"
        f"📦 حجم: `{pretty_size(file_size)}`\n\n"
        f"🔐 **کد یونیک شما:** `{record['code']}`\n\n"
        f"برای دریافت فایل، این کد را در روبیکا برای **{rubika_acc}** ارسال کنید.\n"
        "هرکس این کد را داشته باشد، می‌تواند فایل را دریافت کند."
    )
    await _push(task, success_text, None, "done")

    # cleanup local file
    try:
        if local_path and local_path.exists():
            local_path.unlink()
    except Exception:
        pass


# ----------------------------- code-listener handler -----------------------------

_CODE_RE = re.compile(r"\b([A-Z0-9]{6,12})\b")


async def _handle_incoming(client: RubikaClient, message) -> None:
    """Triggered for every private text message received by the Rubika account."""
    try:
        text = (getattr(message, "text", "") or "").strip()
        if not text:
            return
        author_guid = getattr(message, "author_guid", None) or getattr(message, "object_guid", None)
        if not author_guid:
            return

        # Built-in help/start
        normalized = text.lower().strip()
        if normalized in ("/start", "start", "شروع", "راهنما", "help", "/help"):
            await client.send_message(
                author_guid,
                "سلام! 👋\n"
                "این اکانت برای دریافت فایل با **کد یونیک** فعال است.\n"
                "کافی است کد یونیکی که از ربات تلگرام دریافت کرده‌اید را همین‌جا ارسال کنید "
                "تا فایل برای شما فرستاده شود.\n\n"
                "نمونه: `ABC12345`"
            )
            return

        # Look for a code anywhere in the message
        match = _CODE_RE.search(text.upper())
        if not match:
            await client.send_message(
                author_guid,
                "❌ کد معتبر یافت نشد.\nلطفاً فقط کد یونیک خود را ارسال کنید (۸ کاراکتر).",
            )
            return

        code = match.group(1)
        record = await data.get_file_by_code(code)
        if not record:
            await client.send_message(
                author_guid,
                f"❌ کد `{code}` پیدا نشد یا منقضی شده است.\n"
                "اگر مطمئن هستید کد درست است، با صاحب فایل تماس بگیرید.",
            )
            return

        # Check expiry
        exp = record.get("expires_at")
        if exp and exp.timestamp() < time.time():
            await client.send_message(
                author_guid,
                f"⌛ فایل با کد `{code}` منقضی شده است.",
            )
            return

        # Forward the message from storage channel to the requester
        try:
            await client.forward_messages(
                from_object_guid=record["channel_guid"],
                to_object_guid=author_guid,
                message_ids=[str(record["rubika_message_id"])],
            )
            await client.send_message(
                author_guid,
                f"✅ فایل `{record['file_name']}` برای شما ارسال شد.\n"
                f"📦 حجم: {pretty_size(record['file_size'])}",
            )
            await data.bump_delivered(code)
        except Exception as e:
            await client.send_message(
                author_guid,
                f"⚠️ مشکلی در ارسال فایل پیش آمد:\n`{e}`\nلطفاً چند لحظه دیگر دوباره کد را ارسال کنید.",
            )

    except Exception as e:
        # never crash the listener
        print(f"[Rubika listener error] {e}")


# ----------------------------- queue loop -----------------------------

async def _queue_consumer(client: RubikaClient) -> None:
    print("[Rubika] queue consumer started")
    while True:
        task = await data.pop_next_task()
        if not task:
            await asyncio.sleep(1)
            continue
        try:
            await _process_task(client, task)
            await data.finish_task(task["job_id"], ok=True)
        except Exception as e:
            err = str(e)
            print(f"[Rubika] task failed: {err}")
            await _push(task, f"❌ خطا: {err}", None, "failed")
            await data.finish_task(task["job_id"], ok=False, error=err)


# ----------------------------- main -----------------------------

async def main():
    await data.ensure_indexes()
    session_path = str(config.SESSIONS_DIR / config.RUBIKA_SESSION)
    # rubpy stores session relative to CWD by default; pass full path
    client = RubikaClient(name=session_path)

    @client.on_message_updates(rub_filters.is_private & rub_filters.is_text)
    async def _on_msg(message):
        await _handle_incoming(client, message)

    print("[Rubika] starting client (first run will prompt for phone + code)...")
    await client.start()
    print("[Rubika] client started.")
    asyncio.create_task(_queue_consumer(client))
    # Keep the client alive forever
    try:
        await client.run_until_disconnected()
    except AttributeError:
        # Older rubpy: just sleep
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
