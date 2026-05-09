# Delta MTProto Panel - Clean Build

پنل مدیریت MTProto با یک پورت مشترک، کاربر/secret جدا، ربات تلگرام، ساب‌لینک، بکاپ و آپدیت.

## نصب اولیه

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

## آپدیت

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
```

## نکته مهم درباره حجم در حالت یک پورت

MTProxy رسمی وقتی همه کاربران روی یک پورت مشترک هستند، مصرف را به‌صورت دقیق به تفکیک secret گزارش نمی‌دهد. این سورس جلوی کم شدن حجم از کاربران دیگر را می‌گیرد و وقتی حجم/تاریخ یک کاربر تمام شود secret همان کاربر را از کانفیگ حذف می‌کند. برای accounting صددرصد دقیق به تفکیک secret باید MTProxy پچ‌شده یا لاگ‌دار استفاده شود.

## مسیرها

- App: `/opt/delta-proxy-panel`
- Database: `/opt/delta-proxy-panel/data/panel.db`
- Backups: `/opt/delta-proxy-panel/backups`
- Env: `/opt/delta-proxy-panel/.env`

## امکانات

- پنل وب
- ساخت/حذف/فعال‌غیرفعال کاربر
- secret اختصاصی برای هر کاربر روی یک پورت مشترک
- ساب‌لینک اختصاصی موبایل‌پسند
- بکاپ دانلودی ZIP
- ایمپورت بکاپ
- ربات تلگرام دکمه‌ای
- نصب و آپدیت پایدار
