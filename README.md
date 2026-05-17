 
Action: file_editor create /app/bot/README.md --file-text "# 🚀 Tele2Rub Pro

پلتفرم انتقال فایل از تلگرام به روبیکا با **پنل کاربری شخصی‌سازی شده**، **سیستم اشتراک**، **مدیریت حجم مصرفی**، **پنل ادمین کامل** و **سیستم کد یونیک برای دانلود مجدد در روبیکا**.

این پروژه نسخه‌ی توسعه‌یافته‌ی ربات [Tele2Rub](https://github.com/Hossein-Maleki/TTR) است و کاملاً بازنویسی شده تا به‌صورت چندکاربره و حرفه‌ای روی سرور لینوکس اجرا شود.

---

## 🌟 فیچرهای جدید

- 👤 **پروفایل شخصی برای هر کاربر تلگرام** (نام، شناسه، مصرف ماهانه، تعداد آپلود)
- 💎 **سیستم اشتراک ۴ سطحی** (رایگان / برنزی / نقره‌ای / طلایی) با مدت زمان دلخواه
- 📊 **مدیریت حجم مصرفی ماهانه** و حد حداکثر حجم برای هر فایل
- 🔐 **کد یونیک ۸ کاراکتری** برای هر آپلود (مثل `ABC12345`)
- 🤖 **اکانت روبیکا روی سرور به‌عنوان self-bot**: وقتی کسی کد را به آن پیام می‌دهد، فایل را به‌صورت اتوماتیک از چنل خصوصی **forward** می‌کند
- 🛠 **پنل ادمین داخل ربات تلگرام** (با دکمه‌های شیشه‌ای):
  - فعال‌سازی/تمدید اشتراک
  - مسدودسازی و آزادسازی کاربر
  - مشاهده آمار کلی
  - لیست کاربران
  - پیام همگانی
  - تنظیم چنل ذخیره‌سازی روبیکا
- 📥 **پشتیبانی از فایل + لینک مستقیم**
- 🔄 **صف توزیع‌شده روی MongoDB** (Atomic، بدون race condition)
- 🛡 **محدودیت سایز فایل و حجم ماهانه** قبل و بعد دانلود از URL
- 📈 **آمار کامل کاربر و سیستم**
- ♻️ **Restart خودکار** پروسس‌ها در صورت کرش (داخل launcher)
- 🐧 فایل **systemd service** آماده برای سرور لینوکس

---

## 🏗 معماری

```
┌─────────────┐    file/URL     ┌──────────────┐    Mongo Queue    ┌──────────────┐
│  Telegram   │ ─────────────▶  │ Telegram Bot │ ────────────────▶ │ Rubika Worker│
│   User      │                 │  (telebot)   │                   │ (rub_worker) │
└─────────────┘                 └──────────────┘                   └──────┬───────┘
                                       ▲                                  │
                                       │  status                          │ upload
                                       └────────── MongoDB ◀──────────────┤
                                                                          ▼
                                                              ┌────────────────────┐
                                                              │ Rubika Private     │
                                                              │ Storage Channel    │
                                                              └────────────────────┘
                                                                          ▲
                                                                          │ forward by code
                                                              ┌────────────────────┐
                                                              │ Rubika User sends  │
                                                              │ code in PV         │
                                                              └────────────────────┘
```

دو پروسس مجزا که با MongoDB با هم در ارتباط هستند و توسط `main.py` ساپروایز می‌شوند.

---

## 📋 پیش‌نیازها

| نرم‌افزار | حداقل نسخه |
|----------|-----------|
| Ubuntu / Debian (یا هر توزیع لینوکس) | 20.04+ |
| Python | 3.10+ |
| MongoDB | 4.4+ |
| دسترسی root یا sudo | - |

---

## 🚀 نصب سریع روی سرور لینوکس (Ubuntu 22.04)

### مرحله ۱: نصب پیش‌نیازها

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl gnupg
```

### مرحله ۲: نصب MongoDB

```bash
# افزودن مخزن رسمی MongoDB
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo \"deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse\" | \
   sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

sudo apt update
sudo apt install -y mongodb-org
sudo systemctl enable --now mongod
sudo systemctl status mongod   # بررسی وضعیت
```

> اگر از Debian یا توزیع دیگری استفاده می‌کنید، [راهنمای رسمی نصب MongoDB](https://www.mongodb.com/docs/manual/administration/install-on-linux/) را ببینید.

### مرحله ۳: دریافت پروژه

```bash
sudo mkdir -p /opt/tele2rub-pro
sudo chown $USER:$USER /opt/tele2rub-pro
cd /opt/tele2rub-pro

# اگر کد را در گیت‌هاب دارید:
# git clone <your-repo> .

# یا فایل‌های پروژه را از این پوشه (/app/bot) کپی کنید.
```

### مرحله ۴: ساخت محیط مجازی و نصب وابستگی‌ها

```bash
cd /opt/tele2rub-pro
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### مرحله ۵: ساخت فایل تنظیمات

```bash
cp .env.example .env
nano .env
```

سپس مقادیر زیر را وارد کنید:

```env
API_ID=12345678
API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BOT_TOKEN=123456:ABCDEF...
RUBIKA_SESSION=rubika_main
RUBIKA_STORAGE_CHANNEL_GUID=    # اختیاری، بعداً با /setchannel ست می‌شود
RUBIKA_ACCOUNT_USERNAME=my_rubika_username   # بدون @
MONGO_URL=mongodb://localhost:27017
DB_NAME=tele2rub_pro
ADMIN_IDS=11111111,22222222  # شناسه عددی تلگرامِ ادمین‌ها
```

#### 🔑 از کجا این مقادیر را بگیریم؟
- **`API_ID` و `API_HASH`**: از [my.telegram.org](https://my.telegram.org) → API development tools
- **`BOT_TOKEN`**: از [@BotFather](https://t.me/BotFather) با `/newbot`
- **`ADMIN_IDS`**: از [@userinfobot](https://t.me/userinfobot) شناسه عددی خودتان
- **`RUBIKA_ACCOUNT_USERNAME`**: یوزرنیم پابلیک اکانتی که در روبیکا داخل سرور لاگین می‌کنید

### مرحله ۶: لاگین اولیه اکانت روبیکا (تعاملی)

اولین اجرا برای دریافت کد ورود روبیکا تعاملی است، پس مرحله اول را در ترمینال زنده انجام دهید:

```bash
cd /opt/tele2rub-pro
source venv/bin/activate
python rub_worker.py
```

- ربات از شما شماره موبایل و سپس کد تأیید روبیکا را می‌پرسد.
- بعد از لاگین موفق، فایل سشن در `sessions/` ذخیره می‌شود.
- با `Ctrl+C` خارج شوید — کافی است یک‌بار سشن ساخته شود.

### مرحله ۷: ساخت چنل خصوصی روبیکا

1. در اپلیکیشن روبیکا با همان شماره‌ای که در سرور لاگین کرده‌اید وارد شوید.
2. یک **چنل خصوصی جدید** بسازید (مثلاً `Tele2Rub Storage`).
3. **`object_guid` چنل** را بگیرید (شناسه‌ای که با `c0` شروع می‌شود).
   راه‌های گرفتن GUID:
   - وارد چنل شوید، روی نام چنل بزنید، لینک اشتراک‌گذاری بگیرید. در داخل URL یا API response مقدار GUID مشخص است.
   - یا یک‌بار از داخل ترمینال در همان ENV ربات:
     ```python
     >>> from rubpy import Client
     >>> import asyncio
     >>> async def f():
     ...     c = Client('sessions/rubika_main')
     ...     await c.start()
     ...     async for chat in c.get_chats():
     ...         print(chat.title, chat.object_guid)
     ...     await c.disconnect()
     >>> asyncio.run(f())
     ```
4. مقدار GUID را در `.env` مقدار `RUBIKA_STORAGE_CHANNEL_GUID` بگذارید، یا بعد از اجرا، در تلگرام به ربات `/setchannel c0XXXX...` بدهید.

### مرحله ۸: اجرا

#### روش الف) اجرای دستی (تست)

```bash
cd /opt/tele2rub-pro
source venv/bin/activate
python main.py
```

#### روش ب) اجرای دائمی با systemd (پیشنهادی)

```bash
sudo cp /opt/tele2rub-pro/tele2rub-pro.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tele2rub-pro
sudo systemctl status tele2rub-pro
# مشاهده لاگ زنده:
sudo journalctl -u tele2rub-pro -f
```

#### روش ج) اجرا با screen (ساده اما کم‌قدرت‌تر)

```bash
screen -S tele2rub
cd /opt/tele2rub-pro
source venv/bin/activate
python main.py
# برای جدا شدن از screen: Ctrl+A سپس d
# بازگشت: screen -r tele2rub
```

---

## 🎯 طرز استفاده

### کاربر عادی
1. وارد ربات تلگرام شوید و `/start` بزنید.
2. فایل را برای ربات بفرستید (تا حداکثر ۲ گیگابایت برای پلن طلایی).
3. ربات فایل را در چنل خصوصی روبیکا آپلود می‌کند.
4. یک **کد یونیک ۸ کاراکتری** به همراه آی‌دی اکانت روبیکا دریافت می‌کنید.
5. هرکس آن کد را به اکانت روبیکا بفرستد، فایل به‌صورت اتوماتیک forward می‌شود.

### ادمین
دستورات یا دکمه‌های پنل ادمین:

| دستور | کاربرد |
|-------|--------|
| `/admin` | باز کردن پنل ادمین |
| `/grant <user_id> <plan> [days]` | فعال‌سازی یا تمدید اشتراک |
| `/block <user_id>` | مسدودسازی کاربر |
| `/unblock <user_id>` | آزادسازی کاربر |
| `/stats` | آمار کلی |
| `/setchannel <guid>` | تنظیم چنل ذخیره‌سازی روبیکا |

پلن‌ها: `free` / `bronze` / `silver` / `gold`

مثال: `/grant 123456789 silver 30` → ۳۰ روز اشتراک نقره‌ای

### دستورات کاربر در ربات

| دستور | کاربرد |
|-------|--------|
| `/start` | شروع و منو |
| `/profile` | پروفایل و وضعیت اشتراک |
| `/plans` | لیست پلن‌ها |
| `/myfiles` | فهرست فایل‌های اخیر شما |
| `/del <job_id>` | حذف یک مورد از صف |
| `/delall` | پاکسازی صف خودِ شما |
| `/help` | راهنما |

---

## 🔧 پیکربندی پلن‌ها

پلن‌ها در `config.py` تعریف شده‌اند. می‌توانید سقف‌ها را تغییر دهید:

```python
PLANS = {
    \"free\":   {\"monthly_quota_mb\": 500,    \"max_file_mb\": 200,  ...},
    \"bronze\": {\"monthly_quota_mb\": 5120,   \"max_file_mb\": 1024, ...},
    \"silver\": {\"monthly_quota_mb\": 20480,  \"max_file_mb\": 2048, ...},
    \"gold\":   {\"monthly_quota_mb\": 102400, \"max_file_mb\": 2048, ...},
}
```

---

## 🗃 ساختار پروژه

```
tele2rub-pro/
├── main.py                  # Launcher: هر دو پروسه را اجرا و ساپروایز می‌کند
├── telebot.py               # ربات تلگرام (UI و پنل ادمین)
├── rub_worker.py            # Worker روبیکا (آپلود + گوش دادن به کدها)
├── db.py                    # لایه MongoDB
├── config.py                # تنظیمات و تعریف پلن‌ها
├── utils.py                 # توابع کمکی
├── requirements.txt
├── .env.example
├── tele2rub-pro.service     # یونیت systemd
└── README.md
```

---

## 🛠 عیب‌یابی

#### ربات تلگرام بالا نمی‌آید
- مطمئن شوید `API_ID` و `API_HASH` و `BOT_TOKEN` در `.env` پر شده‌اند.
- لاگ را ببینید: `journalctl -u tele2rub-pro -f`

#### Worker روبیکا کد نمی‌خواهد یا قطع می‌شود
- اولین بار حتماً `python rub_worker.py` را به‌صورت دستی (نه از داخل systemd) اجرا کنید تا کد را تعاملی بزنید.
- اگر سشن قطع شد، فایل `sessions/rubika_main.session` را پاک کنید و دوباره لاگین کنید.

#### کد یونیک ارسال می‌شود ولی Forward انجام نمی‌شود
- مطمئن شوید اکانت روبیکا داخل **همان چنلی** که فایل آنجا آپلود می‌شود، عضو باشد و دسترسی forward داشته باشد.
- یعنی چنل را خودِ همان اکانت ساخته باشد یا ادمین باشد.

#### حجم فایل از حد مجاز عبور می‌کند
- در `config.py` مقدار `max_file_mb` پلن مربوطه را افزایش دهید.
- پلن کاربر را به سطح بالاتری ارتقا دهید (`/grant`).

#### MongoDB در دسترس نیست
- وضعیت سرویس: `sudo systemctl status mongod`
- لاگ MongoDB: `tail -f /var/log/mongodb/mongod.log`

---

## 🔒 امنیت

- فایل `.env` و `sessions/*` حاوی اطلاعات حساس هستند. مطمئن شوید مجوزهای فایلی محدود باشد:
  ```bash
  chmod 600 .env
  chmod 700 sessions
  ```
- پشتیبان‌گیری منظم از MongoDB:
  ```bash
  mongodump --db tele2rub_pro --out /backups/$(date +%F)
  ```

---

## 📜 مجوز

این پروژه بر پایه‌ی [Tele2Rub](https://github.com/Hossein-Maleki/TTR) ساخته شده است.

---

## 🤝 پشتیبانی

اگر سؤالی داشتید یا مشکلی پیش آمد، یک Issue باز کنید.
