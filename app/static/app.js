const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
let allUsers = [];
let modalMode = 'create';
let editingId = null;

function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2400); }
function clamp(n,min,max){ return Math.max(min, Math.min(max, n)); }
function escapeHtml(s=''){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c])); }
function fmtNum(n, d=2){ return Number(n||0).toLocaleString('fa-IR',{maximumFractionDigits:d}); }
function fmtBytes(bytes){ if(!bytes) return '0 B'; const u=['B','KB','MB','GB','TB']; let i=0,n=Number(bytes); while(n>=1024&&i<u.length-1){n/=1024;i++;} return `${fmtNum(n,i?2:0)} ${u[i]}`; }
function gbToBest(gb, zeroUnlimited=true){ gb=Number(gb||0); if(gb<=0) return zeroUnlimited ? 'نامحدود' : '0 MB'; const mb=gb*1024; if(gb<1) return `${fmtNum(mb,0)} MB`; return `${fmtNum(gb,2)} GB`; }
function gbToInput(gb){ gb=Number(gb||0); if(gb>0 && gb<1) return {value: +(gb*1024).toFixed(2), unit:'MB'}; return {value: +gb.toFixed(2), unit:'GB'}; }
function toGB(value, unit){ value=Number(value||0); return unit==='MB' ? value/1024 : value; }
function fmtUptime(sec){ const d=Math.floor(sec/86400); sec%=86400; const h=Math.floor(sec/3600); sec%=3600; const m=Math.floor(sec/60); return `${d}d ${h}h ${m}m`; }
function isoDate(s){ if(!s) return 'بدون انقضا'; try{return new Date(s).toLocaleString('fa-IR')}catch{return s} }
function calcDaysLeft(u){ return u.expire_at ? (u.days_left ?? 0) : ''; }

function show(page){ $$('.page').forEach(x=>x.classList.toggle('active',x.id===page)); $$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===page)); if(page==='users') loadUsers(); if(page==='settings') loadSettings(); if(page==='logs') loadLogs(); }
$$('.nav').forEach(btn=>btn.addEventListener('click',()=>show(btn.dataset.page)));
function applyTheme(t){ document.body.dataset.theme = t || 'dark'; }
function card(title,value,sub,bar){ return `<div class="stat-card"><span>${title}</span><strong>${value}</strong><small>${sub}</small>${bar!==undefined?`<div class="progress"><i style="width:${clamp(bar,0,100)}%"></i></div>`:''}</div>`; }
async function loadOverview(){ const o=await fetch('/api/overview').then(r=>r.json()); applyTheme(o.theme); $('#cards').innerHTML = [
  card('CPU',`${o.cpu}%`,`${o.cores} cores / load ${o.load.map(x=>x.toFixed(2)).join('، ')}`,o.cpu),
  card('RAM',`${o.ram_percent}%`,`${fmtBytes(o.ram_used)} از ${fmtBytes(o.ram_total)}`,o.ram_percent),
  card('Disk',`${o.disk_percent}%`,`${fmtBytes(o.disk_used)} از ${fmtBytes(o.disk_total)}`,o.disk_percent),
  card('Traffic',`↓ ${fmtBytes(o.rx)}`,`↑ ${fmtBytes(o.tx)} کل سرور`),
  card('Shared Port',`${o.proxy_port}`,`${escapeHtml(o.public_host)} · ${escapeHtml(o.proxy_status)}`),
  card('Sub Port',`${o.sub_port||2096}`,`لینک وضعیت کاربران`),
  card('Online',`${o.online_total}`,`اتصال لحظه‌ای روی پورت مشترک`),
  card('Users',`${o.users_enabled}/${o.users_total}`,'فعال / کل'),
  card('Quota',gbToBest(o.used_total,false),`از ${gbToBest(o.quota_total)} مصرف ثبت‌شده`, o.quota_total>0 ? (o.used_total/o.quota_total)*100 : 0),
  card('Shared Traffic',`↓ ${fmtBytes(o.shared_rx_bytes||0)}`,`↑ ${fmtBytes(o.shared_tx_bytes||0)} روی پورت مشترک`),
  card('Uptime',fmtUptime(o.uptime_seconds),'مدت روشن بودن سرور')
].join(''); }

async function loadUsers(){ allUsers=await fetch('/api/users').then(r=>r.json()); renderUsers(); }
function renderUsers(){ const q=($('#searchUser')?.value||'').toLowerCase(); const users=allUsers.filter(u=>(u.name+u.secret+(u.note||'')+(u.port||'')).toLowerCase().includes(q)); $('#userList').innerHTML = users.map(userCard).join('') || '<p class="empty">هنوز کاربری ساخته نشده. از دکمه «ساخت یوزر» استفاده کن.</p>'; }
function statusLabel(u){ if(!u.enabled) return 'غیرفعال'; if(u.expired) return 'منقضی'; if(u.disabled_reason==='quota') return 'اتمام حجم'; return 'فعال'; }
function userCard(u){ const pct=Number(u.usage_percent||0); const online=Number(u.online||0); const quota=Number(u.quota_gb||0); const used=Number(u.used_gb||0); return `<article class="user-card ${u.enabled?'':'off'} ${u.expired?'expired':''}">
  <div class="user-main">
    <div class="avatar">${escapeHtml((u.name||'U').slice(0,1).toUpperCase())}</div>
    <div class="user-info"><h3>${escapeHtml(u.name)}</h3><p><b class="dot ${online?'on':''}"></b>${online} آنلاین · ${statusLabel(u)} · پورت مشترک ${u.shared_port||u.port}</p></div>
    <div class="user-quota"><strong>${gbToBest(used,false)}</strong><small>از ${gbToBest(quota)}</small></div>
    <div class="user-expire"><strong>${u.expire_at ? `${fmtNum(calcDaysLeft(u),0)} روز` : 'نامحدود'}</strong><small>${isoDate(u.expire_at)}</small></div>
    <div class="user-actions"><button class="mini" onclick="openEditModal(${u.id})">ویرایش</button><button class="mini" onclick="toggleUser(${u.id})">${u.enabled?'غیرفعال':'فعال'}</button><button class="mini danger" onclick="deleteUser(${u.id})">حذف</button></div>
  </div>
  <div class="usage-row"><div class="progress"><i style="width:${clamp(pct,0,100)}%"></i></div><span>${fmtNum(pct,1)}%</span></div>
  <div class="link-row"><input class="link" readonly value="${u.link}" onclick="this.select()" /><button onclick="copyText('${u.link}')">کپی پروکسی</button></div>
  <div class="link-row"><input class="link" readonly value="${u.sub_link||''}" onclick="this.select()" /><button onclick="copyText('${u.sub_link||''}')">کپی ساب</button></div>
  <div class="meta"><span>Secret: <code>${u.secret}</code></span><span>آخرین اتصال: ${isoDate(u.last_seen)}</span>${u.note?`<span>یادداشت: ${escapeHtml(u.note)}</span>`:''}</div>
</article>`; }
$('#searchUser')?.addEventListener('input',renderUsers);

function openCreateModal(){ modalMode='create'; editingId=null; const f=$('#userForm'); const el=f.elements; f.reset(); el.uid.value=''; $('#modalKicker').textContent='CREATE'; $('#modalTitle').textContent='ساخت یوزر'; $('#modalSubmit').textContent='ساخت یوزر'; $('#keepExpireLabel').classList.add('hidden'); $('#usedBox').classList.add('hidden'); $('#enabledBox').classList.add('hidden'); el.enabled.classList.add('hidden'); el.quota_value.value=30; el.quota_unit.value='GB'; openUserModal(); }
function openEditModal(id){ const u=allUsers.find(x=>x.id===id); if(!u) return; modalMode='edit'; editingId=id; const f=$('#userForm'); const el=f.elements; f.reset(); el.uid.value=id; el.name.value=u.name||''; el.expire_days.placeholder=calcDaysLeft(u)||'خالی = حفظ تاریخ فعلی'; el.expire_days.value=''; const q=gbToInput(u.quota_gb); el.quota_value.value=q.value; el.quota_unit.value=q.unit; const used=gbToInput(u.used_gb); el.used_value.value=used.value; el.used_unit.value=used.unit; el.note.value=u.note||''; el.enabled.value=u.enabled?'1':'0'; $('#modalKicker').textContent='EDIT'; $('#modalTitle').textContent='ویرایش یوزر'; $('#modalSubmit').textContent='ذخیره تغییرات'; $('#keepExpireLabel').classList.remove('hidden'); $('#usedBox').classList.remove('hidden'); $('#enabledBox').classList.remove('hidden'); el.enabled.classList.remove('hidden'); openUserModal(); }
function openUserModal(){ $('#userModal').classList.add('show'); $('#userModal').setAttribute('aria-hidden','false'); setTimeout(()=>$('#userForm [name=name]').focus(),80); }
function closeUserModal(){ $('#userModal').classList.remove('show'); $('#userModal').setAttribute('aria-hidden','true'); }

$('#userForm')?.addEventListener('submit',async e=>{
  e.preventDefault(); const f=e.target; const el=f.elements; const fd=new FormData(); fd.set('name', el.name.value); fd.set('expire_days', el.expire_days.value); fd.set('quota_gb', String(toGB(el.quota_value.value, el.quota_unit.value))); fd.set('note', el.note.value||'');
  let url='/api/users';
  if(modalMode==='edit') { url=`/api/users/${editingId}/update`; fd.set('keep_expire', el.keep_expire.checked?'1':'0'); fd.set('used_gb', String(toGB(el.used_value.value, el.used_unit.value))); fd.set('enabled', el.enabled.value); }
  const r=await fetch(url,{method:'POST',body:fd}); if(!r.ok){ toast(modalMode==='edit'?'خطا در ویرایش':'خطا در ساخت کاربر'); return; }
  closeUserModal(); toast(modalMode==='edit'?'کاربر آپدیت شد':'کاربر ساخته شد'); await loadUsers(); await loadOverview();
});
async function toggleUser(id){ await fetch(`/api/users/${id}/toggle`,{method:'POST'}); await loadUsers(); await loadOverview(); }
async function deleteUser(id){ if(confirm('کاربر حذف شود؟')){ await fetch(`/api/users/${id}/delete`,{method:'POST'}); toast('حذف شد'); await loadUsers(); await loadOverview(); } }
async function restartProxy(){ await fetch('/api/proxy/restart',{method:'POST'}); toast('سرویس‌ها ری‌استارت شدند'); await loadOverview(); }
async function loadLogs(){ const l=await fetch('/api/proxy/logs').then(r=>r.json()); $('#logBox').textContent=l.logs||'لاگی موجود نیست.'; }

function copyText(t){
  if(!t){ toast('لینک خالی است'); return; }
  const done=()=>toast('لینک کپی شد');
  const fail=()=>{
    const ta=document.createElement('textarea');
    ta.value=t; ta.setAttribute('readonly',''); ta.style.position='fixed'; ta.style.left='-9999px';
    document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, ta.value.length);
    try{ document.execCommand('copy'); done(); }catch(e){ toast('کپی نشد؛ لینک را دستی کپی کن'); }
    ta.remove();
  };
  if(navigator.clipboard && window.isSecureContext){ navigator.clipboard.writeText(t).then(done).catch(fail); }
  else fail();
}


async function loadSettings(){ const s=await fetch('/api/settings').then(r=>r.json()); applyTheme(s.theme); $('#serverForm [name=public_host]').value=s.public_host||''; $('#serverForm [name=proxy_port_value]').value=s.proxy_port||443; $('#serverForm [name=sub_port_value]').value=s.sub_port||2096; $('#serverForm [name=theme]').value=s.theme||'dark'; $('#adminForm [name=username]').value=s.admin_username||'admin'; $('#telegramForm [name=telegram_bot_token]').value=s.telegram_bot_token||''; $('#telegramForm [name=telegram_chat_id]').value=s.telegram_chat_id||''; }
$('#serverForm')?.addEventListener('submit',async e=>{ e.preventDefault(); await fetch('/api/settings/server',{method:'POST',body:new FormData(e.target)}); toast('تنظیمات ذخیره شد'); await loadSettings(); await loadOverview(); });
$('#adminForm')?.addEventListener('submit',async e=>{ e.preventDefault(); await fetch('/api/settings/admin',{method:'POST',body:new FormData(e.target)}); e.target.password.value=''; toast('ورود پنل ذخیره شد'); });
$('#telegramForm')?.addEventListener('submit',async e=>{ e.preventDefault(); await fetch('/api/settings/telegram',{method:'POST',body:new FormData(e.target)}); toast('تنظیمات تلگرام ذخیره شد'); });
async function testTelegram(){ const r=await fetch('/api/telegram/test',{method:'POST'}).then(r=>r.json()); toast(r.ok?'پیام تست ارسال شد':'خطا در ارسال تست'); }
$('#importForm')?.addEventListener('submit',async e=>{ e.preventDefault(); if(!confirm('ایمپورت بکاپ کاربران فعلی را جایگزین می‌کند. ادامه می‌دهی؟')) return; const r=await fetch('/api/backup/import',{method:'POST',body:new FormData(e.target)}).then(r=>r.json()); toast(`بکاپ ایمپورت شد: ${r.imported||0} کاربر`); await loadSettings(); await loadUsers(); await loadOverview(); });
window.addEventListener('keydown',e=>{ if(e.key==='Escape') closeUserModal(); });

loadOverview();
setInterval(loadOverview,5000);
setInterval(()=>{ if($('#users').classList.contains('active')) loadUsers(); },7000);
