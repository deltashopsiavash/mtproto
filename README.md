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

## v4 changes
- Fixed real traffic usage counter: uses dedicated iptables accounting rules per proxy port and reads byte counters in KB/MB/GB.
- Added separate copy buttons for Proxy Link and Sub Link in the admin panel.
- Added copy button inside each user's subscription/status page.
- Added 5 animated subscription-page background themes: sunset, ocean, galaxy, forest, fire.
- Improved responsive mobile layout for admin panel and subscription page.

After pushing to GitHub, update the server with:

```bash
mtp-update
```

## v5 fixes
- Fixed proxy creation errors by validating duplicate ports and showing the real error in panel instead of Internal Server Error.
- Copy buttons now use HTTPS clipboard plus textarea fallback, so they work on HTTP panels too.
- Added auto/manual Secret selector.
- User action buttons are now emoji-only: edit ✏️, delete 🗑️, enable/disable ✅/🚫.
- Subscription page is smaller, more minimal, mobile friendly, and shows usage/date percentages.
- Added five animated subscription themes: rain, flower, bird, heart, desert.
- Improved traffic accounting rules for iptables, iptables-legacy, and iptables-nft, TCP and UDP.


## Telegram Bot
در پنل از مسیر Settings → API تلگرام بات، دو مقدار را وارد کنید:

- توکن ربات تلگرام از BotFather
- آیدی عددی ادمین

بعد از ذخیره، سرویس `mtproto-bot.service` ساخته/ریستارت می‌شود. فقط همان آیدی عددی اجازه استفاده دارد و بقیه کاربران با پیام «شما حق استفاده از این ربات را ندارید» رد می‌شوند.

دستورهای مفید:

```bash
systemctl status mtproto-bot
systemctl restart mtproto-bot
journalctl -u mtproto-bot -f
```
