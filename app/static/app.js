const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];

function fmtGB(bytes) { return (bytes / 1024 / 1024 / 1024).toFixed(1) + ' GB'; }
function fmtUptime(sec) {
  const d = Math.floor(sec / 86400); sec %= 86400;
  const h = Math.floor(sec / 3600); sec %= 3600;
  const m = Math.floor(sec / 60);
  return `${d}d ${h}h ${m}m`;
}
function escapeHtml(s='') { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function show(page) {
  $$('.page').forEach(x => x.classList.toggle('active', x.id === page));
  $$('.nav').forEach(x => x.classList.toggle('active', x.dataset.page === page));
  if (page === 'users') loadUsers();
  if (page === 'logs') loadLogs();
}
$$('.nav').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.page)));

async function loadOverview() {
  const o = await fetch('/api/overview').then(r => r.json());
  $('#cards').innerHTML = `
    ${card('CPU', `${o.cpu}%`, `${o.cores} cores / load ${o.load.map(x=>x.toFixed(2)).join(', ')}`)}
    ${card('RAM', `${o.ram_percent}%`, `${fmtGB(o.ram_used)} / ${fmtGB(o.ram_total)}`)}
    ${card('Disk', `${o.disk_percent}%`, `${fmtGB(o.disk_used)} / ${fmtGB(o.disk_total)}`)}
    ${card('Network', `RX ${fmtGB(o.rx)}`, `TX ${fmtGB(o.tx)}`)}
    ${card('Proxy', o.proxy_status, `${o.public_host}:${o.proxy_port}`)}
    ${card('Users', `${o.users_enabled}/${o.users_total}`, 'active / total')}
    ${card('Uptime', fmtUptime(o.uptime_seconds), 'server uptime')}
  `;
}
function card(title, value, sub) { return `<div class="card"><span>${title}</span><strong>${value}</strong><small>${sub}</small></div>`; }

async function loadUsers() {
  const users = await fetch('/api/users').then(r => r.json());
  $('#userList').innerHTML = users.map(u => `
    <div class="user ${u.enabled ? '' : 'disabled'}">
      <div class="user-head">
        <strong>${escapeHtml(u.name)}</strong>
        <span>${u.enabled ? 'فعال' : 'غیرفعال'}${u.expired ? ' / منقضی' : ''}</span>
      </div>
      <div class="meta">Secret: <code>${u.secret}</code></div>
      <div class="meta">انقضا: ${u.expire_at || 'ندارد'} | حجم: ${u.quota_gb || 0} GB</div>
      <input readonly value="${u.link}" onclick="this.select()" />
      <div class="actions">
        <button onclick="copyText('${u.link}')">کپی لینک</button>
        <button onclick="toggleUser(${u.id})">فعال/غیرفعال</button>
        <button class="danger" onclick="deleteUser(${u.id})">حذف</button>
      </div>
      ${u.note ? `<p class="note">${escapeHtml(u.note)}</p>` : ''}
    </div>
  `).join('') || '<p class="empty">هنوز کاربری ساخته نشده.</p>';
}

$('#userForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  await fetch('/api/users', { method: 'POST', body: form });
  e.target.reset();
  await loadUsers();
  await loadOverview();
});

async function toggleUser(id) { await fetch(`/api/users/${id}/toggle`, { method: 'POST' }); await loadUsers(); await loadOverview(); }
async function deleteUser(id) { if (confirm('کاربر حذف شود؟')) { await fetch(`/api/users/${id}/delete`, { method: 'POST' }); await loadUsers(); await loadOverview(); } }
async function restartProxy() { await fetch('/api/proxy/restart', { method: 'POST' }); await loadOverview(); }
async function loadLogs() { const l = await fetch('/api/proxy/logs').then(r => r.json()); $('#logBox').textContent = l.logs || 'لاگی موجود نیست.'; }
function copyText(t) { navigator.clipboard.writeText(t); alert('کپی شد'); }

loadOverview();
setInterval(loadOverview, 5000);
