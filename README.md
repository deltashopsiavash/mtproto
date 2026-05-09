# MTProto Panel

پنل ساده برای ساخت چند پروکسی MTProto با کاربر اختصاصی، محدودیت حجم، تاریخ انقضا، بکاپ و آپدیت خودکار از GitHub.

## نصب

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

در زمان نصب این موارد پرسیده می‌شود:

- پورت ورود به پنل
- یوزرنیم پنل
- پسورد پنل
- پورت‌های مجاز پروکسی‌ها، مثل `443,8443,9443`

## قابلیت‌ها

- Overview برای دیدن CPU، RAM، Disk، Uptime، تعداد کاربران و آدرس سرور
- ساخت کاربر جدید با پروکسی اختصاصی
- تاریخ انقضا به صورت تعداد روز؛ مثلا `30` یعنی ۳۰ روز از امروز
- نمایش مصرف حجم به صورت خوانا مثل MB/GB
- ویرایش کاربر بعد از ساخت: تغییر حجم، تمدید/تنظیم اعتبار، فعال/غیرفعال‌سازی و یادداشت
- Settings برای تغییر نام کاربری و رمز پنل
- Settings > Server برای تنظیم دامنه یا IP دلخواه؛ لینک‌های پروکسی با همین مقدار ساخته می‌شوند
- Settings > Backup برای خروجی گرفتن از همه تنظیمات و کاربران و Import بکاپ

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
