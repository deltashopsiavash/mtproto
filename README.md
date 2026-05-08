# MTProto Full Panel

پنل مدیریت MTProto با نصب یک‌دستوری برای Ubuntu 22.04 root.

## امکانات

- نصب کامل با Docker Compose
- لاگین ادمین با username/password هنگام نصب
- داشبورد Overview: CPU، RAM، Disk، Network، تعداد کاربران
- ساخت کاربر MTProto با secret اختصاصی
- پورت اختصاصی برای هر کاربر
- حجم مصرفی و تاریخ انقضا
- لینک آماده Telegram برای هر کاربر
- sponsor/adtag اختیاری
- روشن/خاموش، ریست ترافیک، ری‌استارت و حذف کاربر
- Auto-enforce برای غیرفعال کردن کاربرهای منقضی یا پرمصرف

> نکته فنی: برای مدیریت حجم به‌صورت قابل اتکا، این پنل برای هر کاربر یک کانتینر/پورت جدا می‌سازد و مصرف را از Docker stats می‌خواند. این روش از یک MTProxy تک‌پورت با چند secret دقیق‌تر است.

## نصب یک‌دستوری از GitHub شما

بعد از اینکه فایل‌ها را در این ریپو گذاشتی:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

یا اگر روی سرور clone کردی:

```bash
git clone https://github.com/deltashopsiavash/mtproto.git
cd mtproto
chmod +x install.sh
./install.sh
```

نصب از شما می‌پرسد:

- پورت پنل
- یوزرنیم ادمین
- پسورد ادمین
- IP یا دامنه عمومی سرور
- بازه پورت کاربران پروکسی

بعد از نصب:

```text
http://YOUR_SERVER_IP:PANEL_PORT
```

## مدیریت

```bash
docker compose logs -f
```

```bash
docker compose restart
```

```bash
./uninstall.sh
```

## ساخت کاربر

داخل پنل به بخش Users بروید و این موارد را وارد کنید:

- نام کاربر
- حجم به گیگابایت، صفر یعنی نامحدود
- تعداد روز اعتبار
- sponsor tag اختیاری

پنل لینک `tg://proxy?...` را می‌دهد.

## نکات امنیتی مهم

- پنل برای مدیریت Docker به `/var/run/docker.sock` دسترسی دارد؛ فقط روی سرور خودتان نصب کنید.
- بهتر است پنل را پشت Cloudflare Tunnel، Nginx با SSL، یا فایروال IP-restricted قرار دهید.
- پورت‌های کاربران از بازه‌ای که هنگام نصب می‌دهید باز می‌شوند.

## ساختار پروژه

```text
backend/      FastAPI API + SQLite + Docker control
frontend/     React/Vite UI
nginx/        reverse proxy for frontend/api
install.sh    installer
uninstall.sh  cleanup script
```
