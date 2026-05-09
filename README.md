# MTProto Panel

## Install

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

## Update

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
```

- update.sh همه dependency ها را خودش نصب می‌کند
- اگر venv وجود نداشته باشد خودش می‌سازد
- تنظیمات قبلی حذف نمی‌شوند
- قبل آپدیت بکاپ می‌گیرد


## Backup

از داخل پنل روی Download Backup بزنید. بکاپ به‌صورت فایل ZIP ساخته می‌شود و شامل دیتابیس، تنظیمات، اپ و فایل‌های لازم است؛ پوشه‌های سنگین مثل `venv` و `backups` داخل بکاپ قرار نمی‌گیرند.

## Update

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
```


Backup API fixed in v22.


## Version

Current package version: `v23-backup-update-fixed`

## خیلی مهم درباره update.sh

دستور زیر همیشه سورس موجود روی GitHub branch `main` را نصب می‌کند:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
```

پس اگر فایل ZIP جدید گرفتی، اول باید محتویات ZIP را داخل ریپوی GitHub آپلود/Push کنی. بعد دستور update را روی سرور بزن.

برای چک کردن نسخه نصب‌شده روی سرور:

```bash
cat /opt/delta-proxy-panel/VERSION
```
