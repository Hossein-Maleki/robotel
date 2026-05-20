 # Tele2Rub — Telegram ⇄ Rubika File Bridge Bot

پلی بین تلگرام و روبیکا: کاربر فایل را به ربات تلگرام می‌فرستد، ربات آن را روی
حساب روبیکای سرور آپلود می‌کند و یک **کد یکتا (UUID)** برمی‌گرداند. در آینده با
همان کد می‌تواند فایل را مستقیماً از روبیکا به تلگرام بازگرداند، **بدون ذخیره
محلی روی سرور**.

> Built with `Pyrogram` (Telegram) + `rubpy` (Rubika) + `aiosqlite` (storage).

---

## ویژگی‌ها

- 🔐 **حساب کاربری شخصی** برای هر کاربر تلگرام در SQLite (شناسه، یوزرنیم، اشتراک، حجم مصرفی).
- 📦 **آپلود مستقیم** فایل‌های تلگرام به روبیکا (Saved Messages یا یک کانال خصوصی).
- 🆔 **کد یکتا UUID** برای هر فایل — ذخیره فقط روی روبیکا، نه روی سرور.
- 🔁 **دریافت فایل** با دستور `/get <code>` — استریم RAM-only از روبیکا به تلگرام.
- 🧾 **تاریخچه** آخرین فایل‌ها با `/history`.
- 🪪 **پروفایل** و حجم باقی‌مانده با `/profile`.
- 🧱 **سیستم اشتراک**: free (۱۰۰MB/۵۰۰MB) و premium (۱GB/۱۰GB) — قابل تنظیم.
- 🛡 **کنترل دسترسی**: هر کد فقط برای صاحب آن قابل بازیابی است.
- ⚙️ **بدون فایل موقت روی دیسک**: استریم end-to-end در حافظه.

---

## ساختار پروژه

```
tele2rub/
├── bot.py              # نقطه ورود اصلی (Pyrogram)
├── rubika_client.py    # کلاینت بلندمدت rubpy + آپلود/دانلود
├── db.py               # لایه داده‌ای SQLite (aiosqlite)
├── utils.py            # کدساز UUID، فرمت‌بندی، اعمال سقف‌های اشتراک
├── config.py           # بارگذاری env و تنظیمات
├── requirements.txt
├── .env.example
└── README.md
```

---

## پیش‌نیازها

- Python **3.12+**
- یک حساب تلگرام (برای دریافت `API_ID`/`API_HASH`) — [my.telegram.org](https://my.telegram.org)
- یک ربات تلگرام از [@BotFather](https://t.me/BotFather) برای `BOT_TOKEN`
- یک حساب روبیکا که در بار اول به‌صورت تعاملی (شماره + کد) لاگین می‌شود

---

## نصب در سرور لینوکس

```bash
# 1) پیش‌نیازهای سیستم
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip git

# 2) دریافت پروژه
git clone <your-repo-url> tele2rub
cd tele2rub

# 3) محیط مجازی
python3.12 -m venv venv
source venv/bin/activate

# 4) نصب وابستگی‌ها
pip install --upgrade pip
pip install -r requirements.txt

# 5) فایل تنظیمات
cp .env.example .env
nano .env   # مقادیر را پر کنید
```

سپس اولین اجرا — این بار **در حالت تعاملی** اجرا کنید تا rubpy از شما شماره و
کد یک‌بار-مصرف روبیکا را بپرسد:

```bash
python bot.py
```

پس از موفقیت‌آمیز بودن لاگین، فایل سشن (`rubpy.rbs` یا مشابه) کنار پروژه ساخته
می‌شود. از این به بعد می‌توانید ربات را به‌صورت سرویس اجرا کنید.

---

## اجرای دائمی (systemd)

`/etc/systemd/system/tele2rub.service`:

```ini
[Unit]
Description=Tele2Rub Telegram <-> Rubika bridge bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/tele2rub
ExecStart=/opt/tele2rub/venv/bin/python /opt/tele2rub/bot.py
Restart=always
RestartSec=5
User=tele2rub
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tele2rub
sudo systemctl status tele2rub
journalctl -u tele2rub -f
```

---

## دستورات ربات

| دستور | توضیح |
|---|---|
| `/start` یا `/help` | معرفی و راهنما |
| `/profile` | اطلاعات اشتراک، حجم استفاده‌شده و باقی‌مانده |
| `/history` | ۲۰ فایل آخر شما با کدهایشان |
| `/get <code>` | دریافت فایل با کد یکتا (مالک-محور) |
| `/upgrade <id> <free\|premium>` | فقط ادمین — تغییر اشتراک یک کاربر |

ارسال هر **document / video / audio / voice / animation / photo** به PV ربات
به‌طور خودکار به‌عنوان آپلود تلقی می‌شود.

---

## نکات امنیتی و معماری

- **بدون ذخیره محلی**: فایل از تلگرام به `BytesIO` می‌آید، به rubpy داده می‌شود و
  RAM آزاد می‌گردد. مسیر دانلود هم همین است.
- **عایق‌سازی دسترسی**: در `/get`، اگر `owner_id` رکورد با `from_user.id` یکی
  نباشد، همان پیام «یافت نشد» برگردانده می‌شود تا اطلاعات افشا نشود.
- **محدودیت اشتراک**: قبل از هر آپلود `utils.check_upload_allowed` اجرا می‌شود
  (هم سقف هر فایل و هم سقف تجمعی).
- **سشن‌ها**: فایل‌های سشن (`*.session`, `*.rbs`) را محرمانه نگه دارید — معادل
  دسترسی کامل به حساب هستند.

---

## نسخه

`v1.0.0` — اولین انتشار: آپلود/دانلود تلگرام↔روبیکا با کد یکتا، SQLite و سیستم
اشتراک رایگان/premium.
دستورات اجرا برای دانلود همه فایل‌ها به‌صورت یک‌جا
اگر می‌خواهید همه‌چیز را به‌صورت یک آرشیو در سرور خود داشته باشید:

# روی این محیط ساخته‌ام:
cd /app
tar czf tele2rub.tar.gz tele2rub/
# سپس دانلودش کنید
تمام فایل‌ها در پوشهٔ /app/tele2rub/ آماده‌اند، lint و py_compile هر دو پاس می‌شوند. فقط کافیست:

cp .env.example .env و مقادیر را پر کنید
pip install -r requirements.txt
python bot.py (اولین اجرا تعاملی، برای ورود به روبیکا)
اگر چیز دیگری لازم دارید (مثلاً اضافه‌کردن لایه پرداخت، Docker, یا تست واحد با mock)، بگویید تا پیاده‌سازی کنم.

