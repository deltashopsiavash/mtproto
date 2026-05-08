# DELTA MTProto Panel v7

نسخه v7 با ربات تلگرام کاملاً دکمه‌ای.

## امکانات تازه ربات

- منوی دکمه‌ای کامل
- ساخت کاربر مرحله‌به‌مرحله: روز، واحد حجم GB/MB، حجم، نام
- لیست تمام پروکسی‌ها با دکمه جدا برای هر کاربر
- نمایش جزئیات کامل پروکسی، لینک، حجم کل، مصرف، باقی‌مانده، تاریخ و وضعیت
- تغییر حجم، تاریخ، نام، ریست مصرف، فعال/غیرفعال و حذف از داخل ربات
- تنظیمات سرور، دامنه/IP، پورت مشترک، تم سایت، ادمین پنل، تنظیمات ربات
- بکاپ و ایمپورت بکاپ از ربات

## آپدیت از نسخه قبلی

```bash
systemctl stop mtproto-panel || true
cp -r /opt/mtproto-panel /opt/mtproto-panel-backup-$(date +%F-%H%M)
rm -rf /opt/mtproto-panel
unzip mtproto_panel_v7.zip
mv mtproto_panel_v7 /opt/mtproto-panel
cd /opt/mtproto-panel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
systemctl daemon-reload
systemctl restart mtproto-panel
```

بعد از تنظیم توکن و Chat ID در سایت، به ربات `/start` بفرستید.


## v9
- نمایش مصرف 0 به صورت 0 MB به جای نامحدود
- محاسبه مصرف واقعی پورت مشترک و تقسیم تقریبی delta بین کاربران فعال
- اصلاح نمایش مصرف در پنل و ربات
