const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
let allUsers = [];

function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2200); }
function fmtBytes(bytes){ if(!bytes) return '0 B'; const u=['B','KB','MB','GB','TB']; let i=0,n=Number(bytes); while(n>=1024&&i<u.length-1){n/=1024;i++;} return `${n.toFixed(i?1:0)} ${u[i]}`; }
function fmtGB(n){ n=Number(n||0); return `${n.toLocaleString('fa-IR',{maximumFractionDigits:2})} GB`; }
function fmtUptime(sec){ const d=Math.floor(sec/86400); sec%=86400; const h=Math.floor(sec/3600); sec%=3600; const m=Math.floor(sec/60); return `${d}d ${h}h ${m}m`; }
function escapeHtml(s=''){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c])); }
function isoDate(s){ if(!s) return 'بدون انقضا'; try{return new Date(s).toLocaleString('fa-IR')}catch{return s} }
function calcDaysLeft(u){ return u.expire_at ? (u.days_left ?? 0) : ''; }

function show(page){ $$('.page').forEach(x=>x.classList.toggle('active',x.id===page)); $$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===page)); if(page==='users') loadUsers(); if(page==='settings') loadSettings(); if(page==='logs') loadLogs(); }
$$('.nav').forEach(btn=>btn.addEventListener('click',()=>show(btn.dataset.page)));

function card(title,value,sub,bar){ return `<div class="stat-card"><span>${title}</span><strong>${value}</strong><small>${sub}</small>${bar!==undefined?`<div class="progress"><i style="width:${Math.min(100,bar)}%"></i></div>`:''}</div>`; }
async function loadOverview(){ const o=await fetch('/api/overview').then(r=>r.json()); $('#cards').innerHTML = [
  card('CPU',`${o.cpu}%`,`${o.cores} cores / load ${o.load.map(x=>x.toFixed(2)).join('، ')}`,o.cpu),
  card('RAM',`${o.ram_percent}%`,`${fmtBytes(o.ram_used)} از ${fmtBytes(o.ram_total)}`,o.ram_percent),
  card('Disk',`${o.disk_percent}%`,`${fmtBytes(o.disk_used)} از ${fmtBytes(o.disk_total)}`,o.disk_percent),
  card('Traffic',`↓ ${fmtBytes(o.rx)}`,`↑ ${fmtBytes(o.tx)}`),
  card('Proxy',escapeHtml(o.proxy_status),`${escapeHtml(o.public_host)}:${o.proxy_port}`),
  card('Users',`${o.users_enabled}/${o.users_total}`,'فعال / کل'),
  card('Quota',fmtGB(o.used_total),`از ${fmtGB(o.quota_total)} مصرف ثبت‌شده`, o.quota_total>0 ? (o.used_total/o.quota_total)*100 : 0),
  card('Uptime',fmtUptime(o.uptime_seconds),'مدت روشن بودن سرور')
].join(''); }

async function loadUsers(){ allUsers=await fetch('/api/users').then(r=>r.json()); renderUsers(); }
function renderUsers(){ const q=($('#searchUser')?.value||'').toLowerCase(); const users=allUsers.filter(u=>(u.name+u.secret+(u.note||'')).toLowerCase().includes(q)); $('#userList').innerHTML = users.map(u=>userCard(u)).join('') || '<p class="empty">هنوز کاربری ساخته نشده.</p>'; }
function userCard(u){ const pct=u.usage_percent||0; return `<article class="user-card ${u.enabled?'':'off'} ${u.expired?'expired':''}">
  <div class="user-top"><div><h3>${escapeHtml(u.name)}</h3><p>${u.enabled?'فعال':'غیرفعال'} ${u.expired?'· منقضی شده':''}</p></div><button class="mini" onclick="toggleUser(${u.id})">${u.enabled?'غیرفعال':'فعال'}</button></div>
  <input class="link" readonly value="${u.link}" onclick="this.select()" />
  <div class="usage"><div><b>${fmtGB(u.used_gb)}</b><small>مصرف از ${fmtGB(u.quota_gb)}</small></div><span>${pct}%</span></div><div class="progress"><i style="width:${pct}%"></i></div>
  <details><summary>ویرایش کاربر</summary><form class="edit-form" onsubmit="updateUser(event,${u.id})"><label>نام</label><input name="name" value="${escapeHtml(u.name)}" required /><div class="row"><div><label>اعتبار جدید / روز</label><input name="expire_days" type="number" min="0" step="1" placeholder="${calcDaysLeft(u)}" /></div><div><label>حجم GB</label><input name="quota_gb" type="number" min="0" step="0.1" value="${u.quota_gb||0}" /></div></div><label>مصرف ثبت‌شده GB</label><input name="used_gb" type="number" min="0" step="0.1" value="${u.used_gb||0}" /><label>وضعیت</label><select name="enabled"><option value="1" ${u.enabled?'selected':''}>فعال</option><option value="0" ${!u.enabled?'selected':''}>غیرفعال</option></select><label>یادداشت</label><textarea name="note" rows="2">${escapeHtml(u.note||'')}</textarea><button class="primary">ذخیره تغییرات</button></form></details>
  <div class="meta"><span>انقضا: ${isoDate(u.expire_at)}</span><span>Secret: <code>${u.secret}</code></span></div>
  <div class="actions"><button onclick="copyText('${u.link}')">کپی لینک</button><button class="danger" onclick="deleteUser(${u.id})">حذف</button></div>
</article>`; }
$('#searchUser')?.addEventListener('input',renderUsers);

$('#userForm')?.addEventListener('submit',async e=>{ e.preventDefault(); await fetch('/api/users',{method:'POST',body:new FormData(e.target)}); e.target.reset(); toast('کاربر ساخته شد'); await loadUsers(); await loadOverview(); });
async function updateUser(e,id){ e.preventDefault(); await fetch(`/api/users/${id}/update`,{method:'POST',body:new FormData(e.target)}); toast('کاربر آپدیت شد'); await loadUsers(); await loadOverview(); }
async function toggleUser(id){ await fetch(`/api/users/${id}/toggle`,{method:'POST'}); await loadUsers(); await loadOverview(); }
async function deleteUser(id){ if(confirm('کاربر حذف شود؟')){ await fetch(`/api/users/${id}/delete`,{method:'POST'}); toast('حذف شد'); await loadUsers(); await loadOverview(); } }
async function restartProxy(){ await fetch('/api/proxy/restart',{method:'POST'}); toast('سرویس ری‌استارت شد'); await loadOverview(); }
async function loadLogs(){ const l=await fetch('/api/proxy/logs').then(r=>r.json()); $('#logBox').textContent=l.logs||'لاگی موجود نیست.'; }
function copyText(t){ navigator.clipboard.writeText(t); toast('لینک کپی شد'); }

async function loadSettings(){ const s=await fetch('/api/settings').then(r=>r.json()); $('#serverForm [name=public_host]').value=s.public_host||''; $('#serverForm [name=proxy_port_value]').value=s.proxy_port||443; $('#adminForm [name=username]').value=s.admin_username||'admin'; }
$('#serverForm')?.addEventListener('submit',async e=>{ e.preventDefault(); await fetch('/api/settings/server',{method:'POST',body:new FormData(e.target)}); toast('تنظیمات سرور ذخیره شد'); await loadOverview(); });
$('#adminForm')?.addEventListener('submit',async e=>{ e.preventDefault(); await fetch('/api/settings/admin',{method:'POST',body:new FormData(e.target)}); e.target.password.value=''; toast('ورود پنل ذخیره شد'); });
$('#importForm')?.addEventListener('submit',async e=>{ e.preventDefault(); if(!confirm('ایمپورت بکاپ کاربران فعلی را جایگزین می‌کند. ادامه می‌دهی؟')) return; const r=await fetch('/api/backup/import',{method:'POST',body:new FormData(e.target)}).then(r=>r.json()); toast(`بکاپ ایمپورت شد: ${r.imported||0} کاربر`); await loadSettings(); await loadUsers(); await loadOverview(); });

loadOverview();
setInterval(loadOverview,6000);
