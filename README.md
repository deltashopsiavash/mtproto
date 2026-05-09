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
