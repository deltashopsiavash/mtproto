# DELTA PROXY PANEL

پنل مدیریت MTProto برای Ubuntu 22.04 با نصب یک‌دستوری، پنل وب، لاگین ادمین، ساخت کاربر، secret اختصاصی برای هر کاربر و یک پورت مشترک برای همه کاربران.

## امکانات

- نصب کامل با Docker Compose
- لاگین ادمین با username/password هنگام نصب
- داشبورد Overview: CPU، RAM، Disk، Network، تعداد کاربران، ترافیک کانتینر پروکسی
- یک پورت مشترک MTProto برای همه کاربران
- ساخت کاربر با secret اختصاصی
- تاریخ انقضا و فعال/غیرفعال کردن کاربر
- لینک آماده Telegram برای هر کاربر
- sponsor/adtag اختیاری؛ در MTProxy رسمی tag به‌صورت global روی سرویس اعمال می‌شود
- ری‌استارت پروکسی، حذف کاربر و auto-enforce برای تاریخ انقضا

## نکته مهم درباره حجم

در حالت «یک پورت مشترک + چند secret»، MTProxy رسمی چند secret را پشتیبانی می‌کند، اما آمار دقیق مصرف جداگانه برای هر secret را به‌صورت قابل اتکا ارائه نمی‌دهد. بنابراین تاریخ انقضا و قطع/وصل کاربر کار می‌کند، اما محدودیت حجم per-user در این معماری فقط به‌عنوان فیلد مدیریتی نمایش داده می‌شود. اگر محدودیت حجم دقیق برای هر کاربر می‌خواهی، باید معماری چندپورت/چندکانتینر یا یک MTProxy patch‌شده با accounting per-secret استفاده شود.

## نصب یک‌دستوری از GitHub

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
- پورت مشترک MTProto، مثلا 8443

بعد از نصب:

```text
http://YOUR_SERVER_IP:PANEL_PORT
```

## مدیریت

```bash
cd /opt/delta-proxy-panel
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
- حجم به گیگابایت، صفر یعنی نامحدود؛ در حالت تک‌پورت فقط نمایشی است
- تعداد روز اعتبار
- sponsor tag اختیاری

پنل لینک `tg://proxy?...` را می‌دهد. همه لینک‌ها یک port دارند و secret هر کاربر جداست.

## ساختار پروژه

```text
backend/      FastAPI API + SQLite + Docker control
frontend/     React/Vite UI
mtproxy/      Docker image builder for official Telegram MTProxy
nginx/        reverse proxy for frontend/api
install.sh    installer
uninstall.sh  cleanup script
```
