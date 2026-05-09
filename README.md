# MTProto Panel

نصب مستقیم از ریپو:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

آپدیت بدون نصب مجدد:

```bash
mtp-update
```

یا:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
```

## قابلیت‌ها

- پنل وب با لاگین
- Overview سرور: CPU، RAM، Disk، کاربران، آنلاین‌های لحظه‌ای
- ساخت پروکسی اختصاصی برای هر کاربر
- تعیین انقضا با تعداد روز مثل `30`
- نمایش مصرف واقعی با KB/MB/GB
- ویرایش حجم، تاریخ، وضعیت و Secret بعد از ساخت
- Secret دستی یا ساخت خودکار
- ساب‌لینک اختصاصی برای هر کاربر با صفحه وضعیت شبیه کارت مصرف
- پورت جدا برای ساب‌لینک‌ها
- تم Dark/Light حرفه‌ای
- Settings برای تغییر یوزرنیم/پسورد پنل
- تنظیم دامنه/IP سرور برای لینک‌ها
- Backup/Import کامل تنظیمات و کاربران
- API مخصوص اتصال Telegram Bot

## API تلگرام بات

در Settings مقدار `API Token` ساخته یا ویرایش می‌شود. نمونه‌ها:

```bash
curl "http://SERVER:PORT/api/users?token=API_TOKEN"
curl "http://SERVER:PORT/api/user/USERNAME?token=API_TOKEN"
```

خروجی شامل مصرف، حجم باقی‌مانده، آنلاین لحظه‌ای، لینک پروکسی و ساب‌لینک است.
