# MTProto Panel

پنل ساده برای ساخت چند پروکسی MTProto با کاربر اختصاصی، محدودیت حجم و تاریخ انقضا.

## نصب

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

در زمان نصب این موارد پرسیده می‌شود:

- پورت ورود به پنل
- یوزرنیم پنل
- پسورد پنل
- پورت‌های مجاز پروکسی‌ها، مثل `443,8443,9443`

## آپدیت

```bash
mtp-update
```

یا:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
```

آپدیت، فایل‌های جدید را از سورس GitHub می‌گیرد ولی دیتابیس کاربران و تنظیمات پنل را حفظ می‌کند.

## مسیرها

- برنامه: `/opt/mtproto-panel`
- دیتابیس: `/etc/mtproto-panel/panel.db`
- تنظیمات: `/etc/mtproto-panel/config.json`
- فایل‌های MTProto: `/etc/mtproto-panel/mtproxy`
- سرویس پنل: `mtproto-panel.service`
- سرویس هر کاربر: `mtproxy-user-USERNAME.service`
