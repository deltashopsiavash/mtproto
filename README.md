# DELTA MTProto Panel v4 - Shared Port

این نسخه همه کاربران را روی یک پورت مشترک اجرا می‌کند. هر کاربر secret اختصاصی خودش را دارد و لینک‌ها با همان secret جدا می‌شوند.

## قابلیت‌ها
- Shared Port برای همه کاربران
- ساخت لینک اختصاصی با secret جدا
- ویرایش حجم، تاریخ، نام، وضعیت و یادداشت بعد از ساخت
- تم دارک/لایت
- آنلاین‌های لحظه‌ای روی پورت مشترک
- ترافیک کل پورت مشترک با iptables
- API بات تلگرام و تست پیام
- بکاپ و ایمپورت بکاپ
- تنظیم دامنه/IP نمایشی لینک‌ها

## نکته مهم درباره حجم
وقتی همه کاربران روی یک پورت هستند، iptables نمی‌تواند مصرف را به تفکیک secret تشخیص بدهد. بنابراین v4 ترافیک کل پورت مشترک را نشان می‌دهد و مصرف هر کاربر را به‌صورت فیلد قابل مدیریت/ویرایش نگه می‌دارد. برای حجم کاملاً واقعی به تفکیک کاربر باید MTProxy لاگ‌دار/پچ‌شده یا لایه accounting اختصاصی اضافه شود.

## نصب
```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

## آپدیت دستی
```bash
systemctl stop delta-panel || true
cp -r /opt/delta-proxy-panel /opt/delta-proxy-panel-backup
unzip mtproto_panel_v4.zip
rm -rf /opt/delta-proxy-panel/app /opt/delta-proxy-panel/requirements.txt
cp -r mtproto_panel_v4/app /opt/delta-proxy-panel/app
cp mtproto_panel_v4/requirements.txt /opt/delta-proxy-panel/requirements.txt
cd /opt/delta-proxy-panel
source venv/bin/activate
pip install -r requirements.txt
systemctl daemon-reload
systemctl restart delta-panel
```
