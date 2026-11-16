const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const app = document.getElementById('app');

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------

const state = {
  tab: 'overview',
  sub: null,
  loading: true,
  fatal: '',
  meta: null,
  catalog: null,
  data: {},
  users: { page: 1, search: '' },
  market: { page: 1, item_type: '', min_price: '', max_price: '', search: '' },
  templates: { kind: 'fish', search: '', page: 1 },
  dialog: null,
  confirm: null,
  notice: '',
  error: '',
  noticeTimer: null,
};

const NAV = [
  ['overview', '总览', 'dashboard'],
  ['users', '玩家', 'users'],
  ['market', '玩家市场', 'tag'],
  ['exchange', '交易所', 'chart'],
  ['shops', '商店', 'store'],
  ['gacha', '抽卡池', 'gift'],
  ['zones', '钓鱼区域', 'waves'],
  ['templates', '物品模板', 'package'],
  ['titles', '称号', 'trophy'],
  ['ops', '全服操作', 'wrench'],
];

// Material Design Icons，与 AstrBot 面板使用同一套图标
const ICONS = {
  dashboard: 'M13,3V9H21V3M13,21H21V11H13M3,21H11V15H3M3,13H11V3H3V13Z',
  users: 'M12,5.5A3.5,3.5 0 0,1 15.5,9A3.5,3.5 0 0,1 12,12.5A3.5,3.5 0 0,1 8.5,9A3.5,3.5 0 0,1 12,5.5M5,8C5.56,8 6.08,8.15 6.53,8.42C6.38,9.85 6.8,11.27 7.66,12.38C7.16,13.34 6.16,14 5,14A3,3 0 0,1 2,11A3,3 0 0,1 5,8M19,8A3,3 0 0,1 22,11A3,3 0 0,1 19,14C17.84,14 16.84,13.34 16.34,12.38C17.2,11.27 17.62,9.85 17.47,8.42C17.92,8.15 18.44,8 19,8M5.5,18.25C5.5,16.18 8.41,14.5 12,14.5C15.59,14.5 18.5,16.18 18.5,18.25V20H5.5V18.25M0,20V18.5C0,17.11 1.89,15.94 4.45,15.6C3.86,16.28 3.5,17.22 3.5,18.25V20H0M24,20H20.5V18.25C20.5,17.22 20.14,16.28 19.55,15.6C22.11,15.94 24,17.11 24,18.5V20Z',
  tag: 'M5.5,7A1.5,1.5 0 0,1 4,5.5A1.5,1.5 0 0,1 5.5,4A1.5,1.5 0 0,1 7,5.5A1.5,1.5 0 0,1 5.5,7M21.41,11.58L12.41,2.58C12.05,2.22 11.55,2 11,2H4C2.89,2 2,2.89 2,4V11C2,11.55 2.22,12.05 2.59,12.41L11.58,21.41C11.95,21.77 12.45,22 13,22C13.55,22 14.05,21.77 14.41,21.41L21.41,14.41C21.78,14.05 22,13.55 22,13C22,12.44 21.77,11.94 21.41,11.58Z',
  chart: 'M16,11.78L20.24,4.45L21.97,5.45L16.74,14.5L10.23,10.75L5.46,19H22V21H2V3H4V17.54L9.5,8L16,11.78Z',
  store: 'M12,18H6V14H12M21,14V12L20,7H4L3,12V14H4V20H14V14H18V20H20V14M20,4H4V6H20V4Z',
  gift: 'M22,12V20A2,2 0 0,1 20,22H4A2,2 0 0,1 2,20V12A1,1 0 0,1 1,11V8A2,2 0 0,1 3,6H6.17C6.06,5.69 6,5.35 6,5A3,3 0 0,1 9,2C10,2 10.88,2.5 11.43,3.24V3.23L12,4L12.57,3.23V3.24C13.12,2.5 14,2 15,2A3,3 0 0,1 18,5C18,5.35 17.94,5.69 17.83,6H21A2,2 0 0,1 23,8V11A1,1 0 0,1 22,12M4,20H11V12H4V20M20,20V12H13V20H20M9,4A1,1 0 0,0 8,5A1,1 0 0,0 9,6A1,1 0 0,0 10,5A1,1 0 0,0 9,4M15,4A1,1 0 0,0 14,5A1,1 0 0,0 15,6A1,1 0 0,0 16,5A1,1 0 0,0 15,4M3,8V10H11V8H3M13,8V10H21V8H13Z',
  waves: 'M2,18C4.22,17 6.44,16 8.67,16C10.89,16 13.11,18 15.33,18C17.56,18 19.78,16 22,16V19C19.78,19 17.56,21 15.33,21C13.11,21 10.89,19 8.67,19C6.44,19 4.22,20 2,21V18M2,12C4.22,11 6.44,10 8.67,10C10.89,10 13.11,12 15.33,12C17.56,12 19.78,10 22,10V13C19.78,13 17.56,15 15.33,15C13.11,15 10.89,13 8.67,13C6.44,13 4.22,14 2,15V12M2,6C4.22,5 6.44,4 8.67,4C10.89,4 13.11,6 15.33,6C17.56,6 19.78,4 22,4V7C19.78,7 17.56,9 15.33,9C13.11,9 10.89,7 8.67,7C6.44,7 4.22,8 2,9V6Z',
  package: 'M2,10.96C1.5,10.68 1.35,10.07 1.63,9.59L3.13,7C3.24,6.8 3.41,6.66 3.6,6.58L11.43,2.18C11.59,2.06 11.79,2 12,2C12.21,2 12.41,2.06 12.57,2.18L20.47,6.62C20.66,6.72 20.82,6.88 20.91,7.08L22.36,9.6C22.64,10.08 22.47,10.69 22,10.96L21,11.54V16.5C21,16.88 20.79,17.21 20.47,17.38L12.57,21.82C12.41,21.94 12.21,22 12,22C11.79,22 11.59,21.94 11.43,21.82L3.53,17.38C3.21,17.21 3,16.88 3,16.5V10.96C2.7,11.13 2.32,11.14 2,10.96M12,4.15V4.15L12,10.85V10.85L17.96,7.5L12,4.15M5,15.91L11,19.29V12.58L5,9.21V15.91M19,15.91V12.69L14,15.59C13.67,15.77 13.3,15.76 13,15.6V19.29L19,15.91M13.85,13.36L20.13,9.73L19.55,8.72L13.27,12.35L13.85,13.36Z',
  trophy: 'M18 2C17.1 2 16 3 16 4H8C8 3 6.9 2 6 2H2V11C2 12 3 13 4 13H6.2C6.6 15 7.9 16.7 11 17V19.08C8 19.54 8 22 8 22H16C16 22 16 19.54 13 19.08V17C16.1 16.7 17.4 15 17.8 13H20C21 13 22 12 22 11V2H18M6 11H4V4H6V11M20 11H18V4H20V11Z',
  wrench: 'M22.7,19L13.6,9.9C14.5,7.6 14,4.9 12.1,3C10.1,1 7.1,0.6 4.7,1.7L9,6L6,9L1.6,4.7C0.4,7.1 0.9,10.1 2.9,12.1C4.8,14 7.5,14.5 9.8,13.6L18.9,22.7C19.3,23.1 19.9,23.1 20.3,22.7L22.6,20.4C23.1,20 23.1,19.3 22.7,19Z',
  refresh: 'M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z',
  plus: 'M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z',
  close: 'M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z',
  menuDown: 'M7,10L12,15L17,10H7Z',
  back: 'M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z',
  upload: 'M9,16V10H5L12,3L19,10H15V16H9M5,20V18H19V20H5Z',
  download: 'M5,20H19V18H5M19,9H15V3H9V9H5L12,16L19,9Z',
  delete: 'M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;

const TYPE_LABELS = { fish: '鱼类', rod: '鱼竿', bait: '鱼饵', accessory: '饰品', item: '道具', coins: '金币', premium: '高级货币', titles: '称号', commodity: '大宗商品' };
const SHOP_TYPES = { normal: '普通商店', premium: '高级商店', limited: '限时商店' };
const SYSTEM_USERS = new Set(['MARKET', 'SYSTEM']);
const SENTIMENT = { panic: '恐慌', pessimistic: '悲观', neutral: '中性', optimistic: '乐观', euphoric: '狂热' };
const TREND = { rising: '上涨', falling: '下跌', stable: '平稳', volatile: '震荡' };

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
const fmt = value => (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) ? '-' : Number(value).toLocaleString('zh-CN');
const pct = (value, digits = 2) => (value === null || value === undefined || value === '') ? '-' : `${(Number(value) * 100).toFixed(digits)}%`;
const time = value => value ? String(value).replace('T', ' ').slice(0, 16) : '-';
const stars = n => n ? `<span class="stars" title="${n} 星">${'★'.repeat(Math.min(Number(n), 10))}</span>` : '<span class="muted">-</span>';
const badge = (text, kind = '') => `<span class="badge ${kind}">${esc(text)}</span>`;
const yesNo = (value, on = '是', off = '否') => badge(value ? on : off, value ? 'good' : 'off');
const toLocalInput = value => value ? String(value).replace(' ', 'T').slice(0, 16) : '';
const opt = (value, label, selected) => `<option value="${esc(value)}" ${String(selected) === String(value) ? 'selected' : ''}>${esc(label)}</option>`;
const options = (pairs, selected) => pairs.map(([value, label]) => opt(value, label, selected)).join('');

function cleanParams(params = {}) {
  const out = {};
  Object.entries(params).forEach(([key, value]) => { if (value !== '' && value !== null && value !== undefined) out[key] = value; });
  return out;
}
const get = (endpoint, params = {}) => bridge.apiGet(endpoint, cleanParams(params));
const post = (endpoint, body = {}) => bridge.apiPost(endpoint, body);

function notify(message, error = false) {
  if (state.noticeTimer) clearTimeout(state.noticeTimer);
  state.notice = error ? '' : message;
  state.error = error ? message : '';
  renderNotices();
  state.noticeTimer = setTimeout(() => { state.notice = ''; state.error = ''; state.noticeTimer = null; renderNotices(); }, 4500);
}
const noticesHtml = () => `${state.error ? `<div class="notice error" role="alert">${esc(state.error)}</div>` : ''}${state.notice ? `<div class="notice success" role="status">${esc(state.notice)}</div>` : ''}`;
function renderNotices() { const box = document.getElementById('notices'); if (box) box.innerHTML = noticesHtml(); }
const errText = error => error?.message || String(error);

function download(filename, content, type = 'text/csv;charset=utf-8') {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.style.display = 'none';
  document.body.appendChild(link); link.click();
  setTimeout(() => { URL.revokeObjectURL(url); link.remove(); }, 0);
}

// ---------------------------------------------------------------------------
// 通用组件
// ---------------------------------------------------------------------------

function shell(title, subtitle, body, actions = '') {
  const tabs = NAV.map(([id, label, name]) => `<button type="button" class="tab ${state.tab === id ? 'active' : ''}" ${state.tab === id ? 'aria-current="page"' : ''} data-nav="${id}">${icon(name)}<span>${label}</span></button>`).join('');
  const version = state.meta?.version ? `<div class="sidebar-foot">版本 ${esc(state.meta.version)}</div>` : '';
  return `<div class="layout">
    <aside class="sidebar">
      <div class="brand"><img src="./logo.png" alt=""><div><strong>全能钓鱼</strong><span>管理面板</span></div></div>
      <nav class="nav" aria-label="管理分区">${tabs}</nav>
      ${version}
    </aside>
    <main class="content">
      <div class="page-head"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div><div class="page-actions">${actions}<button type="button" class="btn text" data-action="refresh">${icon('refresh')}刷新</button></div></div>
      ${body}
    </main>
  </div>
  <div id="notices">${noticesHtml()}</div>`;
}

const metric = (label, value, detail = '') => `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small></div>`;

function table(headers, rows, empty = '暂无数据。') {
  const head = headers.map(h => typeof h === 'string' ? `<th>${esc(h)}</th>` : `<th class="${h.cls || ''}">${esc(h.label)}</th>`).join('');
  const body = rows.length ? rows.join('') : `<tr><td colspan="${headers.length}" class="empty">${esc(empty)}</td></tr>`;
  return `<div class="table-wrap"><table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function pagination(p, scope) {
  if (!p) return '';
  const total = p.total_count ?? p.total_items ?? 0;
  const pages = Math.max(1, p.total_pages || 1);
  return `<div class="pagination"><span>共 ${fmt(total)} 条，第 ${p.current_page} / ${pages} 页</span><button type="button" class="btn text" data-action="page" data-scope="${scope}" data-page="${p.current_page - 1}" ${p.current_page <= 1 ? 'disabled' : ''}>上一页</button><button type="button" class="btn text" data-action="page" data-scope="${scope}" data-page="${p.current_page + 1}" ${p.current_page >= pages ? 'disabled' : ''}>下一页</button></div>`;
}

const rowActions = buttons => `<div class="row-actions">${buttons.join('')}</div>`;
const act = (label, action, data = {}, danger = false) => `<button type="button" ${danger ? 'class="danger-text"' : ''} data-action="${action}" ${Object.entries(data).map(([k, v]) => `data-${k}="${esc(v)}"`).join(' ')}>${esc(label)}</button>`;

// 表单字段
function field({ name, label, type = 'text', value = '', placeholder = '', hint = '', required = false, min, max, step, cls = '', attrs = '' }) {
  const id = `f_${name}`;
  const extra = [min !== undefined ? `min="${min}"` : '', max !== undefined ? `max="${max}"` : '', step !== undefined ? `step="${step}"` : '', required ? 'required' : '', attrs].join(' ');
  const input = type === 'textarea'
    ? `<textarea id="${id}" name="${name}" rows="3" placeholder="${esc(placeholder)}" ${extra}>${esc(value)}</textarea>`
    : `<input id="${id}" name="${name}" type="${type}" value="${esc(value ?? '')}" placeholder="${esc(placeholder)}" ${extra}>`;
  return `<div class="field ${cls}"><label for="${id}">${esc(label)}${required ? '' : ''}</label>${input}${hint ? `<span class="hint">${esc(hint)}</span>` : ''}</div>`;
}
function selectField({ name, label, choices, value = '', hint = '', cls = '', attrs = '' }) {
  const id = `f_${name}`;
  return `<div class="field ${cls}"><label for="${id}">${esc(label)}</label><select id="${id}" name="${name}" ${attrs}>${options(choices, value)}</select>${hint ? `<span class="hint">${esc(hint)}</span>` : ''}</div>`;
}
function switchField({ name, label, checked = false, cls = '', hint = '' }) {
  return `<div class="field switches ${cls}"><label class="check"><input name="${name}" type="checkbox" ${checked ? 'checked' : ''}> ${esc(label)}</label>${hint ? `<span class="hint">${esc(hint)}</span>` : ''}</div>`;
}

function itemChoices(type, { placeholder = '请选择物品' } = {}) {
  const list = state.catalog?.[type] || [];
  return [['', placeholder], ...list.map(x => [x.id, `${x.name}${x.rarity ? ` ${'★'.repeat(Math.min(x.rarity, 10))}` : ''} · #${x.id}`])];
}
const itemSelectOptions = (type, selected, placeholder) => options(itemChoices(type, { placeholder }), selected);

// ---------------------------------------------------------------------------
// 对话框
// ---------------------------------------------------------------------------

function openDialog(dialog) { state.dialog = { submit: '保存', size: '', ...dialog }; render(); requestAnimationFrame(() => document.querySelector('.modal input:not([type=hidden]):not([readonly]), .modal textarea')?.focus()); }
function closeDialog() { state.dialog = null; render(); }

function dialogView() {
  const d = state.dialog;
  if (!d) return '';
  return `<div class="modal-backdrop" data-backdrop="dialog"><section class="modal ${d.size}" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
    <div class="modal-head"><div><h3 id="dialog-title">${esc(d.title)}</h3>${d.subtitle ? `<p>${esc(d.subtitle)}</p>` : ''}</div><button class="modal-close" type="button" data-action="dialog-cancel" aria-label="关闭">${icon('close')}</button></div>
    <form data-form="${d.form}" novalidate>${d.body()}<div class="inline-error" role="alert" hidden></div>
      <div class="modal-actions"><button class="btn text" type="button" data-action="dialog-cancel">${d.cancel || '取消'}</button>${d.submit ? `<button class="btn ${d.danger ? 'tonal-danger' : 'primary'}" type="submit">${esc(d.submit)}</button>` : ''}</div>
    </form></section></div>`;
}

function showDialogError(message) {
  const box = document.querySelector('.modal .inline-error');
  if (box) { box.textContent = message; box.hidden = false; box.scrollIntoView({ block: 'nearest' }); }
  else notify(message, true);
}

function confirmAction({ title, message, label = '确认', danger = true, run }) {
  state.confirm = { title, message, label, danger, run };
  render();
}
function confirmView() {
  const c = state.confirm;
  if (!c) return '';
  return `<div class="modal-backdrop" data-backdrop="confirm"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><div class="modal-head"><div><h3 id="confirm-title">${esc(c.title)}</h3><p>${esc(c.message)}</p></div><button class="modal-close" type="button" data-action="confirm-cancel" aria-label="关闭">${icon('close')}</button></div><div class="modal-actions"><button class="btn text" type="button" data-action="confirm-cancel">取消</button><button class="btn ${c.danger ? 'tonal-danger' : 'primary'}" type="button" data-action="confirm-submit">${esc(c.label)}</button></div></section></div>`;
}

// 读取表单：复选框转布尔，data-multi 复选框收集成数组
function formValues(form) {
  const values = {};
  [...form.elements].forEach(el => {
    if (!el.name || el.disabled) return;
    if (el.type === 'checkbox') {
      if (el.dataset.multi !== undefined) { values[el.name] = values[el.name] || []; if (el.checked) values[el.name].push(el.value); }
      else values[el.name] = el.checked;
    } else if (el.type === 'radio') {
      if (el.checked) values[el.name] = el.value;
    } else values[el.name] = el.value;
  });
  return values;
}

// ---------------------------------------------------------------------------
// 数据加载
// ---------------------------------------------------------------------------

const LOADERS = {
  overview: async () => { state.data.overview = await get('overview'); },
  users: async () => {
    if (state.sub?.type === 'inventory') { state.data.inventory = await get('users/inventory', { user_id: state.sub.user_id }); return; }
    state.data.users = await get('users', { page: state.users.page, search: state.users.search });
  },
  market: async () => { state.data.market = await get('market', state.market); },
  exchange: async () => { state.data.exchange = await get('exchange'); },
  shops: async () => {
    if (state.sub?.type === 'shop') { state.data.shop = await get('shops/items', { shop_id: state.sub.shop_id }); return; }
    state.data.shops = await get('shops');
  },
  gacha: async () => {
    if (state.sub?.type === 'pool') { state.data.pool = await get('gacha/items', { pool_id: state.sub.pool_id }); return; }
    state.data.gacha = await get('gacha');
  },
  zones: async () => { state.data.zones = await get('zones'); },
  templates: async () => { state.data.templates = await get('templates', { kind: state.templates.kind }); },
  titles: async () => { state.data.titles = await get('titles'); },
  ops: async () => { state.data.impersonation = await get('ops/impersonation'); },
};

async function loadCatalog() { state.catalog = await get('catalog'); }

async function loadTab() {
  try { await LOADERS[state.tab](); }
  catch (error) {
    if (state.sub) { state.sub = null; await LOADERS[state.tab](); }
    notify(errText(error), true);
  }
}

async function switchTab(tab) {
  state.tab = tab; state.sub = null;
  await loadTab();
  render();
  document.querySelector('.content')?.scrollTo?.(0, 0);
  window.scrollTo(0, 0);
}

async function refresh() { await loadTab(); render(); }

// ---------------------------------------------------------------------------
// 总览
// ---------------------------------------------------------------------------

function overviewView() {
  const o = state.data.overview;
  if (!o) return shell('总览', '', '<div class="panel empty">正在加载…</div>');
  const c = o.counts || {};
  const avg = value => (o.users ? Math.round((value || 0) / o.users) : 0);
  const market = o.market || {};
  const contentRows = [
    ['鱼类模板', c.fish, 'templates', 'fish'], ['鱼竿模板', c.rods, 'templates', 'rods'], ['鱼饵模板', c.baits, 'templates', 'baits'],
    ['饰品模板', c.accessories, 'templates', 'accessories'], ['道具模板', c.items, 'templates', 'items'], ['称号', c.titles, 'titles', ''],
  ].map(([label, value, tab, kind]) => `<div class="row"><h4>${label}</h4><button type="button" class="btn text" data-action="goto" data-tab="${tab}" data-kind="${kind}">${fmt(value)} 条</button></div>`).join('');
  const runRows = [
    ['钓鱼区域', `${fmt(c.active_zones)} / ${fmt(c.zones)} 个开放`, 'zones'],
    ['商店 / 卡池', `${fmt(c.shops)} 个商店 · ${fmt(c.gacha_pools)} 个卡池`, 'shops'],
    ['市场挂单', `${fmt(market.total_listings)} 单`, 'market'],
    ['管理员代理', o.impersonations ? badge(`${o.impersonations} 个进行中`, 'warn') : badge('无', 'off'), 'ops'],
  ].map(([label, value, tab]) => `<div class="row"><h4>${label}</h4><button type="button" class="btn text" data-action="goto" data-tab="${tab}">${value}</button></div>`).join('');
  return shell('总览', '玩家、资产与游戏内容的实时概况。', `<div class="stack">
    <section class="grid metrics">
      ${metric('注册玩家', fmt(o.users), `${fmt(o.auto_fishing_users)} 人开启自动钓鱼`)}
      ${metric('金币总量', fmt(o.coins_total), `人均 ${fmt(avg(o.coins_total))}`)}
      ${metric('高级货币总量', fmt(o.premium_total), `人均 ${fmt(avg(o.premium_total))}`)}
      ${metric('市场挂单', fmt(market.total_listings), `鱼竿 ${fmt(market.rod_count)} · 饰品 ${fmt(market.accessory_count)} · 鱼 ${fmt(market.fish_count)}`)}
    </section>
    <section class="grid two">
      <div class="panel list-card"><h3>游戏内容</h3>${contentRows}</div>
      <div class="panel list-card"><h3>运行状态</h3>${runRows}</div>
    </section>
    <section class="panel"><div class="panel-head"><div><h3>常用操作</h3><p>原来的管理员指令都已移到面板，这里是最常用的几项。</p></div></div>
      <div class="toolbar">
        <button type="button" class="btn tonal" data-action="goto" data-tab="users">${icon('users')}管理玩家</button>
        <button type="button" class="btn tonal" data-action="broadcast-currency">全体发放金币</button>
        <button type="button" class="btn tonal" data-action="broadcast-item">全体发放物品</button>
        <button type="button" class="btn tonal" data-action="replenish">补充鱼池</button>
      </div>
    </section>
  </div>`);
}

// ---------------------------------------------------------------------------
// 玩家
// ---------------------------------------------------------------------------

function usersView() {
  if (state.sub?.type === 'inventory') return inventoryView();
  const d = state.data.users || { users: [], pagination: null };
  const rows = d.users.map(u => {
    const system = SYSTEM_USERS.has(u.user_id);
    return `<tr>
      <td><strong>${esc(u.nickname || '未设置昵称')}</strong>${system ? ` ${badge('系统', 'off')}` : ''}<span class="cell-sub">${esc(u.user_id)}</span></td>
      <td class="num">${fmt(u.coins)}</td>
      <td class="num">${fmt(u.premium_currency)}</td>
      <td class="num">${fmt(u.total_fishing_count)}</td>
      <td>${u.auto_fishing_enabled ? badge('自动钓鱼', 'good') : badge('手动', 'off')}</td>
      <td class="nowrap">${time(u.last_login_time)}<span class="cell-sub">注册 ${time(u.created_at)}</span></td>
      <td>${rowActions(system ? [act('详情', 'user-detail', { id: u.user_id }), act('库存', 'user-inventory', { id: u.user_id })] : [
        act('详情', 'user-detail', { id: u.user_id }), act('编辑', 'user-edit', { id: u.user_id }), act('货币', 'user-currency', { id: u.user_id }),
        act('库存', 'user-inventory', { id: u.user_id }), act('删除', 'user-delete', { id: u.user_id }, true),
      ])}</td></tr>`;
  });
  return shell('玩家', '搜索玩家、调整资产、管理库存与称号。', `<div class="panel">
    <form class="toolbar" data-filter="users">
      <input class="grow" name="search" value="${esc(state.users.search)}" placeholder="搜索用户 ID 或昵称" aria-label="搜索玩家">
      <button type="submit" class="btn tonal">查询</button>
      <button type="button" class="btn primary" data-action="user-create">${icon('plus')}新建玩家</button>
    </form>
    ${table(['玩家', { label: '金币', cls: 'num' }, { label: '高级货币', cls: 'num' }, { label: '钓鱼次数', cls: 'num' }, '状态', '最后签到', '操作'], rows, '没有匹配的玩家。')}
    ${pagination(d.pagination, 'users')}
  </div>`);
}

function userFormBody(u = {}) {
  const zones = (state.catalog?.zones || []).map(z => [z.id, `${z.name} · #${z.id}`]);
  return `<div class="form-grid">
    ${field({ name: 'user_id', label: '用户 ID', value: u.user_id || '', required: true, attrs: u.user_id ? 'readonly' : '', hint: u.user_id ? '' : '平台上的用户 ID，例如 QQ 号' })}
    ${field({ name: 'nickname', label: '昵称', value: u.nickname || '', attrs: 'maxlength="32"' })}
    ${field({ name: 'coins', label: '金币', type: 'number', value: u.coins ?? '', min: 0, placeholder: u.user_id ? '' : '留空使用初始金币' })}
    ${field({ name: 'premium_currency', label: '高级货币', type: 'number', value: u.premium_currency ?? 0, min: 0 })}
    ${field({ name: 'total_fishing_count', label: '钓鱼次数', type: 'number', value: u.total_fishing_count ?? 0, min: 0 })}
    ${field({ name: 'total_weight_caught', label: '总重量 (g)', type: 'number', value: u.total_weight_caught ?? 0, min: 0 })}
    ${field({ name: 'total_coins_earned', label: '累计赚取金币', type: 'number', value: u.total_coins_earned ?? 0, min: 0 })}
    ${field({ name: 'consecutive_login_days', label: '连续签到天数', type: 'number', value: u.consecutive_login_days ?? 0, min: 0 })}
    ${field({ name: 'fish_pond_capacity', label: '鱼塘容量', type: 'number', value: u.fish_pond_capacity ?? 480, min: 0 })}
    ${selectField({ name: 'fishing_zone_id', label: '钓鱼区域', choices: zones, value: u.fishing_zone_id ?? 1 })}
    ${switchField({ name: 'auto_fishing_enabled', label: '自动钓鱼', checked: !!u.auto_fishing_enabled, cls: 'full' })}
  </div>`;
}

async function openUserDetail(userId) {
  const d = await get('users/detail', { user_id: userId });
  const u = d.user;
  const titleRows = (d.titles || []).map(t => `<div class="row"><div><h4>${esc(t.name)} ${t.is_current ? badge('佩戴中', 'good') : ''}</h4><p>${esc(t.description || '')}</p></div><button type="button" class="btn text danger" data-action="title-revoke" data-user="${esc(u.user_id)}" data-name="${esc(t.name)}">移除</button></div>`).join('') || '<div class="empty">还没有称号。</div>';
  const titleChoices = [['', '选择要授予的称号'], ...(state.catalog?.titles || []).map(t => [t.name, t.name])];
  openDialog({
    form: 'title-grant', title: u.nickname || u.user_id, subtitle: `用户 ID：${u.user_id}`, size: 'wide', submit: '授予称号', userId: u.user_id,
    body: () => `<dl class="info-grid">
      ${[['金币', fmt(u.coins)], ['高级货币', fmt(u.premium_currency)], ['历史最高金币', fmt(u.max_coins)], ['累计赚取金币', fmt(u.total_coins_earned)],
        ['钓鱼次数', fmt(u.total_fishing_count)], ['总重量', `${fmt(u.total_weight_caught)} g`], ['鱼塘容量', fmt(u.fish_pond_capacity)],
        ['当前区域', `#${u.fishing_zone_id}`], ['自动钓鱼', u.auto_fishing_enabled ? '已开启' : '已关闭'],
        ['装备鱼竿', d.equipped_rod ? `${d.equipped_rod.name} +${d.equipped_rod.refine_level}` : '无'], ['装备饰品', d.equipped_accessory ? `${d.equipped_accessory.name} +${d.equipped_accessory.refine_level}` : '无'],
        ['当前称号', d.current_title || '无'], ['连续签到', `${fmt(u.consecutive_login_days)} 天`], ['注册时间', time(u.created_at)], ['最后签到', time(u.last_login_time)],
        ['被代理', d.impersonated_by?.length ? d.impersonated_by.join('、') : '无']].map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('')}
    </dl>
    <div class="modal-section">称号</div><div class="list-card">${titleRows}</div>
    <div class="form-grid" style="margin-top:12px">${selectField({ name: 'title_name', label: '授予称号', choices: titleChoices, cls: 'full' })}</div>`,
  });
}

function openCurrencyDialog(user) {
  openDialog({
    form: 'user-currency', title: '调整货币', subtitle: `${user.nickname || user.user_id}：金币 ${fmt(user.coins)}，高级货币 ${fmt(user.premium_currency)}`, userId: user.user_id, submit: '确认调整',
    body: () => `<div class="form-grid">
      ${selectField({ name: 'currency', label: '货币', choices: [['coins', '金币'], ['premium_currency', '高级货币']] })}
      ${selectField({ name: 'mode', label: '方式', choices: [['add', '增加'], ['subtract', '扣除'], ['set', '设置为']] })}
      ${field({ name: 'amount', label: '数量', type: 'number', min: 0, required: true, cls: 'full', hint: '扣除超过余额时扣到 0 为止。' })}
    </div>`,
  });
}

function inventoryView() {
  const inv = state.data.inventory;
  if (!inv) return shell('库存', '', '<div class="panel empty">正在加载…</div>');
  const s = inv.stats || {};
  const uid = inv.user_id;
  const removeBtn = (type, id, max) => act('移除', 'inv-remove', { user: uid, type, item: id, max }, true);
  const fishRows = inv.fish_inventory.map(f => `<tr><td><strong>${esc(f.name)}</strong><span class="cell-sub">#${f.fish_id}</span></td><td>${stars(f.rarity)}</td><td>${f.quality_level ? badge('高品质', 'warn') : '普通'}</td><td class="num">${fmt(f.quantity)}</td><td class="num">${fmt(f.actual_value)}</td><td class="num">${fmt(f.total_value)}</td><td>${rowActions([removeBtn('fish', f.fish_id, f.quantity)])}</td></tr>`);
  const rodRows = inv.rod_inventory.map(r => `<tr><td><strong>${esc(r.name)}</strong><span class="cell-sub">${esc(r.display_code)} · 实例 #${r.instance_id}</span></td><td>${stars(r.rarity)}</td><td class="num">+${r.refine_level}</td><td class="num">${r.durability === null || r.durability === undefined ? '无限' : fmt(r.durability)}</td><td>${r.is_equipped ? badge('装备中', 'good') : ''} ${r.is_locked ? badge('已锁定', 'warn') : ''}</td><td>${rowActions([act('编辑', 'rod-edit', { user: uid, id: r.instance_id, refine: r.refine_level, durability: r.durability ?? '' }), removeBtn('rod', r.rod_id, 1)])}</td></tr>`);
  const accRows = inv.accessory_inventory.map(a => `<tr><td><strong>${esc(a.name)}</strong><span class="cell-sub">${esc(a.display_code)} · 实例 #${a.instance_id}</span></td><td>${stars(a.rarity)}</td><td class="num">+${a.refine_level}</td><td>${a.is_equipped ? badge('装备中', 'good') : ''} ${a.is_locked ? badge('已锁定', 'warn') : ''}</td><td>${rowActions([act('编辑', 'acc-edit', { user: uid, id: a.instance_id, refine: a.refine_level }), removeBtn('accessory', a.accessory_id, 1)])}</td></tr>`);
  const baitRows = inv.bait_inventory.map(b => `<tr><td><strong>${esc(b.name)}</strong><span class="cell-sub">#${b.bait_id}</span></td><td>${stars(b.rarity)}</td><td class="num">${fmt(b.quantity)}</td><td class="num">${fmt(b.cost)}</td><td class="num">${fmt(b.total_value)}</td><td>${rowActions([removeBtn('bait', b.bait_id, b.quantity)])}</td></tr>`);
  const itemRows = inv.item_inventory.map(i => `<tr><td><strong>${esc(i.name)}</strong><span class="cell-sub">#${i.item_id}</span></td><td>${stars(i.rarity)}</td><td>${i.is_consumable ? '消耗品' : '永久'}</td><td class="num">${fmt(i.quantity)}</td><td class="num">${fmt(i.cost)}</td><td>${rowActions([removeBtn('item', i.item_id, i.quantity)])}</td></tr>`);
  const section = (title, html) => `<section class="panel"><h3>${title}</h3>${html}</section>`;
  return shell(`${inv.nickname || uid} 的库存`, `用户 ID：${uid}`, `<button type="button" class="back" data-action="back">${icon('back')}返回玩家列表</button><div class="stack">
    <section class="grid metrics">${metric('鱼类', fmt(s.fish_count), `价值 ${fmt(s.fish_total_value)}`)}${metric('鱼竿 / 饰品', `${fmt(s.rod_count)} / ${fmt(s.accessory_count)}`, '装备实例数')}${metric('鱼饵 / 道具', `${fmt(s.bait_count)} / ${fmt(s.item_count)}`, `价值 ${fmt((s.bait_total_value || 0) + (s.item_total_value || 0))}`)}${metric('库存总价值', fmt(s.total_inventory_value), '鱼、鱼饵与道具')}</section>
    ${section('鱼类', table(['名称', '稀有度', '品质', { label: '数量', cls: 'num' }, { label: '单价', cls: 'num' }, { label: '总价值', cls: 'num' }, '操作'], fishRows, '鱼塘是空的。'))}
    ${section('鱼竿', table(['名称', '稀有度', { label: '精炼', cls: 'num' }, { label: '耐久', cls: 'num' }, '状态', '操作'], rodRows, '没有鱼竿。'))}
    ${section('饰品', table(['名称', '稀有度', { label: '精炼', cls: 'num' }, '状态', '操作'], accRows, '没有饰品。'))}
    ${section('鱼饵', table(['名称', '稀有度', { label: '数量', cls: 'num' }, { label: '单价', cls: 'num' }, { label: '总价值', cls: 'num' }, '操作'], baitRows, '没有鱼饵。'))}
    ${section('道具', table(['名称', '稀有度', '类型', { label: '数量', cls: 'num' }, { label: '单价', cls: 'num' }, '操作'], itemRows, '没有道具。'))}
  </div>`, `<button type="button" class="btn primary" data-action="inv-add" data-user="${esc(uid)}">${icon('plus')}添加物品</button>`);
}

function itemPickerFields({ types = ['fish', 'rod', 'accessory', 'bait', 'item'], type = 'fish', item = '', quantity = 1, quality = true } = {}) {
  return `<div class="form-grid" data-scope>
    ${selectField({ name: 'item_type', label: '物品类型', choices: types.map(t => [t, TYPE_LABELS[t]]), value: type, attrs: 'data-item-target="[data-role=item]"' })}
    <div class="field"><label for="f_item_id">物品</label><select id="f_item_id" name="item_id" data-role="item">${itemSelectOptions(type, item)}</select></div>
    ${field({ name: 'quantity', label: '数量', type: 'number', value: quantity, min: 1 })}
    ${quality ? `<div class="field" data-show-for="fish"><label for="f_quality_level">品质</label><select id="f_quality_level" name="quality_level">${options([[0, '普通'], [1, '高品质']], 0)}</select></div>` : ''}
  </div>`;
}

// ---------------------------------------------------------------------------
// 玩家市场
// ---------------------------------------------------------------------------

function marketView() {
  const d = state.data.market;
  if (!d) return shell('玩家市场', '', '<div class="panel empty">正在加载…</div>');
  const s = d.stats || {};
  const rows = d.rows.map(x => `<tr><td>#${x.market_id}</td><td><strong>${esc(x.item_name)}</strong>${x.quality_level ? ` ${badge('高品质', 'warn')}` : ''}<span class="cell-sub">${esc(x.item_description || '')}</span></td><td>${esc(TYPE_LABELS[x.item_type] || x.item_type)}</td><td class="num">${['rod', 'accessory'].includes(x.item_type) ? `+${x.refine_level}` : '-'}</td><td class="num">${fmt(x.quantity)}</td><td class="num">${fmt(x.price)}</td><td><strong>${esc(x.seller_nickname || x.user_id)}</strong>${x.is_anonymous ? ` ${badge('匿名', 'off')}` : ''}<span class="cell-sub">${esc(x.user_id)}</span></td><td class="nowrap">${time(x.listed_at)}${x.expires_at ? `<span class="cell-sub">过期 ${time(x.expires_at)}</span>` : ''}</td><td>${rowActions([act('改价', 'market-price', { id: x.market_id, price: x.price, name: x.item_name }), act('下架', 'market-remove', { id: x.market_id, name: x.item_name }, true)])}</td></tr>`);
  const f = state.market;
  return shell('玩家市场', '查看玩家挂单，修改价格或强制下架（物品退回卖家）。', `<div class="stack">
    <section class="grid metrics">${metric('挂单总数', fmt(s.total_listings), `筛选结果 ${fmt(s.filtered_listings)} 单`)}${metric('鱼类 / 道具', `${fmt(s.fish_count)} / ${fmt(s.item_count)}`, '按数量统计')}${metric('鱼竿 / 饰品', `${fmt(s.rod_count)} / ${fmt(s.accessory_count)}`, '按挂单统计')}${metric('大宗商品', fmt(s.commodity_count), `本页总价 ${fmt(s.total_value)}`)}</section>
    <section class="panel">
      <form class="toolbar" data-filter="market">
        <input class="grow" name="search" value="${esc(f.search)}" placeholder="搜索物品名或卖家" aria-label="搜索">
        <select name="item_type" aria-label="物品类型">${options([['', '全部类型'], ['fish', '鱼类'], ['rod', '鱼竿'], ['accessory', '饰品'], ['item', '道具'], ['commodity', '大宗商品']], f.item_type)}</select>
        <input name="min_price" type="number" min="0" value="${esc(f.min_price)}" placeholder="最低价" aria-label="最低价">
        <input name="max_price" type="number" min="0" value="${esc(f.max_price)}" placeholder="最高价" aria-label="最高价">
        <button type="submit" class="btn tonal">查询</button>
      </form>
      ${table(['ID', '商品', '类型', { label: '精炼', cls: 'num' }, { label: '数量', cls: 'num' }, { label: '单价', cls: 'num' }, '卖家', '上架时间', '操作'], rows, '没有符合条件的挂单。')}
      ${pagination(d.pagination, 'market')}
    </section>
  </div>`);
}

// ---------------------------------------------------------------------------
// 交易所
// ---------------------------------------------------------------------------

function exchangeView() {
  const d = state.data.exchange;
  if (!d) return shell('交易所', '', '<div class="panel empty">正在加载…</div>');
  const st = d.status || {}; const h = d.history || {}; const hold = d.holdings?.stats || {};
  const ids = Object.keys(st.prices || {});
  const cards = ids.map(id => {
    const series = h.history?.[id] || [];
    const prev = series.length > 1 ? series[series.length - 2] : null;
    const now = st.prices[id];
    const diff = prev ? (now - prev) / prev : null;
    const trend = diff === null ? '暂无对比' : `<span class="${diff >= 0 ? 'trend-up' : 'trend-down'}">${diff >= 0 ? '▲' : '▼'} ${pct(Math.abs(diff))}</span> 较上次`;
    const stats = hold.commodity_stats?.[id] || {};
    return `<div class="metric"><span>${esc(st.commodities?.[id]?.name || id)}</span><strong>${fmt(now)}</strong><small>${trend}</small><p>${esc(st.commodities?.[id]?.description || '')}</p><p>持仓 ${fmt(stats.total_quantity)} 份 · ${fmt(stats.user_count)} 人</p></div>`;
  }).join('');
  const labels = h.labels || [];
  const historyRows = labels.map((label, i) => `<tr><td class="nowrap">${esc(label)}</td>${ids.map(id => `<td class="num">${fmt(h.history?.[id]?.[i])}</td>`).join('')}</tr>`).reverse();
  const holderRows = ids.flatMap(id => (hold.commodity_stats?.[id]?.users || []).map(u => `<tr><td>${esc(st.commodities?.[id]?.name || id)}</td><td>${esc(u.user_id)}</td><td class="num">${fmt(u.quantity)}</td></tr>`));
  return shell('交易所', '大宗商品价格与玩家持仓。', `<div class="stack">
    <section class="price-cards">${cards || '<div class="panel empty">暂无商品。</div>'}</section>
    <section class="panel"><div class="panel-head"><div><h3>市场状态</h3><p>日期 ${esc(st.date || '-')} · 情绪 ${esc(SENTIMENT[st.market_sentiment] || st.market_sentiment || '-')} · 走势 ${esc(TREND[st.price_trend] || st.price_trend || '-')} · 供需 ${esc(st.supply_demand || '-')}</p></div>
      <div class="page-actions"><button type="button" class="btn tonal" data-action="exchange-update">立即刷新价格</button><button type="button" class="btn tonal-danger" data-action="exchange-reset">重置为初始价格</button></div></div>
      <div class="grid metrics three">${metric('持仓玩家', fmt(hold.total_users), '至少持有一种商品')}${metric('持仓总量', fmt(hold.total_holdings), '所有商品合计')}${metric('价格记录', fmt(labels.length), `最近 ${fmt(h.days || 7)} 天`)}</div>
    </section>
    <section class="grid two">
      <div class="panel"><h3>价格历史</h3>${table(['时间', ...ids.map(id => ({ label: st.commodities?.[id]?.name || id, cls: 'num' }))], historyRows, '还没有价格记录。')}</div>
      <div class="panel"><h3>持仓明细</h3>${table(['商品', '用户 ID', { label: '数量', cls: 'num' }], holderRows, '暂无玩家持仓。')}</div>
    </section>
  </div>`);
}

// ---------------------------------------------------------------------------
// 商店
// ---------------------------------------------------------------------------

function shopsView() {
  if (state.sub?.type === 'shop') return shopDetailView();
  const rows = (state.data.shops?.rows || []).map(s => `<tr><td>#${s.shop_id}</td><td><strong>${esc(s.name)}</strong><span class="cell-sub">${esc(s.description || '')}</span></td><td>${esc(SHOP_TYPES[s.shop_type] || s.shop_type)}</td><td>${yesNo(s.is_active, '营业中', '已停用')}</td><td class="nowrap">${s.start_time || s.end_time ? `${time(s.start_time)} ~ ${time(s.end_time)}` : '长期'}${s.daily_start_time || s.daily_end_time ? `<span class="cell-sub">每日 ${esc(s.daily_start_time || '00:00')} - ${esc(s.daily_end_time || '23:59')}</span>` : ''}</td><td class="num">${fmt(s.sort_order)}</td><td class="num">${fmt(s.item_count)}</td><td>${rowActions([act('商品', 'shop-open', { id: s.shop_id }), act('编辑', 'shop-edit', { id: s.shop_id }), act('删除', 'shop-delete', { id: s.shop_id, name: s.name }, true)])}</td></tr>`);
  return shell('商店', '商店与商品完全由面板管理，玩家用“商店”“商店购买”指令购买。', `<div class="panel">${table(['ID', '商店', '类型', '状态', '营业时间', { label: '排序', cls: 'num' }, { label: '商品数', cls: 'num' }, '操作'], rows, '还没有商店。')}</div>`, `<button type="button" class="btn primary" data-action="shop-create">${icon('plus')}新建商店</button>`);
}

function shopFormBody(s = {}) {
  return `<div class="form-grid">
    ${field({ name: 'name', label: '商店名称', value: s.name || '', required: true })}
    ${selectField({ name: 'shop_type', label: '商店类型', choices: Object.entries(SHOP_TYPES), value: s.shop_type || 'normal' })}
    ${field({ name: 'description', label: '描述', type: 'textarea', value: s.description || '', cls: 'full' })}
    ${field({ name: 'start_time', label: '开始时间', type: 'datetime-local', value: toLocalInput(s.start_time), hint: '留空表示不限' })}
    ${field({ name: 'end_time', label: '结束时间', type: 'datetime-local', value: toLocalInput(s.end_time), hint: '留空表示不限' })}
    ${field({ name: 'daily_start_time', label: '每日开始营业', type: 'time', value: s.daily_start_time || '' })}
    ${field({ name: 'daily_end_time', label: '每日结束营业', type: 'time', value: s.daily_end_time || '' })}
    ${field({ name: 'sort_order', label: '排序', type: 'number', value: s.sort_order ?? 100, hint: '数字越小越靠前' })}
    ${switchField({ name: 'is_active', label: '启用商店', checked: s.is_active ?? true })}
  </div>`;
}

const costLabel = c => `${c.name}${c.quality_level ? '（高品质）' : ''} ×${fmt(c.cost_amount)}`;
const rewardLabel = r => `${r.name}${r.quality_level ? '（高品质）' : ''}${r.reward_refine_level > 1 ? ` +${r.reward_refine_level}` : ''} ×${fmt(r.reward_quantity)}`;

function describeCosts(costs) {
  if (!costs.length) return '免费';
  const groups = {};
  const plain = [];
  costs.forEach(c => { if (c.cost_relation === 'or' && c.group_id) (groups[c.group_id] = groups[c.group_id] || []).push(c); else plain.push(c); });
  const parts = plain.map(costLabel);
  Object.values(groups).forEach(list => parts.push(`(${list.map(costLabel).join(' 或 ')})`));
  return parts.join(' + ');
}

function shopDetailView() {
  const d = state.data.shop;
  if (!d) return shell('商店', '', '<div class="panel empty">正在加载…</div>');
  const rows = d.rows.map(({ item: i, costs, rewards }) => `<tr><td>#${i.item_id}</td><td><strong>${esc(i.name)}</strong><span class="cell-sub">${esc(i.description || '')}</span></td><td class="wrap-text">${esc(describeCosts(costs))}</td><td class="wrap-text">${esc(rewards.map(rewardLabel).join('、') || '-')}</td><td class="num">${i.stock_total === null || i.stock_total === undefined ? '不限' : `${fmt(i.stock_total - (i.stock_sold || 0))} / ${fmt(i.stock_total)}`}<span class="cell-sub">已售 ${fmt(i.stock_sold)}</span></td><td class="nowrap">${i.per_user_limit ? `总 ${i.per_user_limit}` : '总不限'}<span class="cell-sub">${i.per_user_daily_limit ? `每日 ${i.per_user_daily_limit}` : '每日不限'}</span></td><td>${yesNo(i.is_active, '上架', '下架')}</td><td class="num">${fmt(i.sort_order)}</td><td>${rowActions([act('编辑', 'shop-item-edit', { id: i.item_id }), act('删除', 'shop-item-delete', { id: i.item_id, name: i.name }, true)])}</td></tr>`);
  const s = d.shop;
  return shell(s.name, `${SHOP_TYPES[s.shop_type] || s.shop_type} · ${s.is_active ? '营业中' : '已停用'} · 商店 ID ${s.shop_id}`, `<button type="button" class="back" data-action="back">${icon('back')}返回商店列表</button>
    <div class="panel">${table(['ID', '商品', '消耗', '奖励', { label: '库存', cls: 'num' }, '每人限购', '状态', { label: '排序', cls: 'num' }, '操作'], rows, '这个商店还没有商品。')}</div>`,
  `<button type="button" class="btn text" data-action="shop-edit" data-id="${s.shop_id}">编辑商店</button><button type="button" class="btn primary" data-action="shop-item-create">${icon('plus')}添加商品</button>`);
}

const COST_TYPES = [['coins', '金币'], ['premium', '高级货币'], ['fish', '鱼类'], ['item', '道具'], ['rod', '鱼竿'], ['accessory', '饰品']];
const REWARD_TYPES = [['rod', '鱼竿'], ['bait', '鱼饵'], ['accessory', '饰品'], ['item', '道具'], ['fish', '鱼类']];

function costRow(c, i) {
  const type = c.cost_type || 'coins';
  return `<div class="editor-row" data-scope data-cost-row>
    <select name="cost_type" aria-label="消耗类型" data-item-target="[data-role=item]">${options(COST_TYPES, type)}</select>
    <div data-show-for="fish item rod accessory"><select name="cost_item_id" data-role="item" aria-label="消耗物品">${itemSelectOptions(['coins', 'premium'].includes(type) ? 'fish' : type, c.cost_item_id || '')}</select></div>
    <input name="cost_amount" type="number" min="1" value="${esc(c.cost_amount ?? 1)}" placeholder="数量" aria-label="数量">
    <select name="cost_relation" aria-label="关系">${options([['and', '必须'], ['or', '可选']], c.cost_relation || 'and')}</select>
    <input name="group_id" type="number" min="1" value="${esc(c.group_id ?? '')}" placeholder="组 ID" aria-label="组 ID">
    <div data-show-for="fish"><select name="quality_level" aria-label="品质">${options([[0, '普通'], [1, '高品质']], c.quality_level || 0)}</select></div>
    <button type="button" class="icon-btn" data-action="row-remove" data-list="costs" data-index="${i}" aria-label="删除消耗">${icon('delete')}</button>
  </div>`;
}

function rewardRow(r, i) {
  const type = r.reward_type || 'rod';
  return `<div class="editor-row reward" data-scope data-reward-row>
    <select name="reward_type" aria-label="奖励类型" data-item-target="[data-role=item]">${options(REWARD_TYPES, type)}</select>
    <select name="reward_item_id" data-role="item" aria-label="奖励物品">${itemSelectOptions(type, r.reward_item_id || '')}</select>
    <input name="reward_quantity" type="number" min="1" value="${esc(r.reward_quantity ?? 1)}" placeholder="数量" aria-label="数量">
    <div data-show-for="rod accessory"><input name="reward_refine_level" type="number" min="1" max="10" value="${esc(r.reward_refine_level ?? '')}" placeholder="精炼等级" aria-label="精炼等级"></div>
    <div data-show-for="fish"><select name="quality_level" aria-label="品质">${options([[0, '普通'], [1, '高品质']], r.quality_level || 0)}</select></div>
    <button type="button" class="icon-btn" data-action="row-remove" data-list="rewards" data-index="${i}" aria-label="删除奖励">${icon('delete')}</button>
  </div>`;
}

function readRows() {
  const d = state.dialog;
  if (!d || !d.costs) return;
  d.costs = [...document.querySelectorAll('[data-cost-row]')].map(row => ({
    cost_type: row.querySelector('[name=cost_type]').value, cost_item_id: row.querySelector('[name=cost_item_id]').value,
    cost_amount: row.querySelector('[name=cost_amount]').value, cost_relation: row.querySelector('[name=cost_relation]').value,
    group_id: row.querySelector('[name=group_id]').value, quality_level: row.querySelector('[name=quality_level]').value,
  }));
  d.rewards = [...document.querySelectorAll('[data-reward-row]')].map(row => ({
    reward_type: row.querySelector('[name=reward_type]').value, reward_item_id: row.querySelector('[name=reward_item_id]').value,
    reward_quantity: row.querySelector('[name=reward_quantity]').value, reward_refine_level: row.querySelector('[name=reward_refine_level]').value,
    quality_level: row.querySelector('[name=quality_level]').value,
  }));
  const form = document.querySelector('form[data-form="shop-item"]');
  if (form) d.values = formValues(form);
}

function openShopItemDialog(row) {
  const i = row?.item || {};
  openDialog({
    form: 'shop-item', title: row ? '编辑商品' : '添加商品', subtitle: state.data.shop.shop.name, size: 'xwide', itemId: i.item_id || '',
    values: { ...i }, costs: row ? row.costs.map(c => ({ ...c })) : [{ cost_type: 'coins', cost_amount: 100, cost_relation: 'and' }],
    rewards: row ? row.rewards.map(r => ({ ...r })) : [{ reward_type: 'rod', reward_quantity: 1 }],
    body: () => {
      const v = state.dialog.values;
      return `<div class="modal-section">基本信息</div><div class="form-grid three">
        ${field({ name: 'name', label: '商品名称', value: v.name || '', required: true })}
        ${field({ name: 'sort_order', label: '排序', type: 'number', value: v.sort_order ?? 100 })}
        ${switchField({ name: 'is_active', label: '在商店中上架', checked: v.is_active ?? true })}
        ${field({ name: 'description', label: '描述', type: 'textarea', value: v.description || '', cls: 'full' })}
        ${field({ name: 'stock_total', label: '库存总量', type: 'number', min: 0, value: v.stock_total ?? '', hint: '留空表示不限' })}
        ${field({ name: 'stock_sold', label: '已售数量', type: 'number', min: 0, value: v.stock_sold ?? 0 })}
        ${field({ name: 'per_user_limit', label: '每人总限购', type: 'number', min: 1, value: v.per_user_limit ?? '', hint: '留空表示不限' })}
        ${field({ name: 'per_user_daily_limit', label: '每人每日限购', type: 'number', min: 1, value: v.per_user_daily_limit ?? '', hint: '留空表示不限' })}
        ${field({ name: 'start_time', label: '开始时间', type: 'datetime-local', value: toLocalInput(v.start_time) })}
        ${field({ name: 'end_time', label: '结束时间', type: 'datetime-local', value: toLocalInput(v.end_time) })}
      </div>
      <div class="modal-section">消耗</div>
      <div class="note" style="margin-bottom:10px">“必须”的消耗都要支付；“可选”且组 ID 相同的几项只需满足其一，不同组之间仍需同时满足。不填消耗表示免费。</div>
      <div class="row-editor">
        <div class="editor-row editor-head"><span>类型</span><span>物品</span><span>数量</span><span>关系</span><span>组 ID</span><span>品质</span><span></span></div>
        ${state.dialog.costs.map(costRow).join('')}
      </div>
      <button type="button" class="btn text" data-action="row-add" data-list="costs" style="margin-top:6px">${icon('plus')}添加消耗</button>
      <div class="modal-section">奖励</div>
      <div class="row-editor">
        <div class="editor-row reward editor-head"><span>类型</span><span>物品</span><span>数量</span><span>精炼等级</span><span>品质</span><span></span></div>
        ${state.dialog.rewards.map(rewardRow).join('')}
      </div>
      <button type="button" class="btn text" data-action="row-add" data-list="rewards" style="margin-top:6px">${icon('plus')}添加奖励</button>`;
    },
  });
}

// ---------------------------------------------------------------------------
// 抽卡池
// ---------------------------------------------------------------------------

function gachaView() {
  if (state.sub?.type === 'pool') return poolDetailView();
  const rows = (state.data.gacha?.rows || []).map(p => {
    const cost = p.cost_premium_currency ? `${fmt(p.cost_premium_currency)} 高级货币` : p.cost_coins ? `${fmt(p.cost_coins)} 金币` : '免费';
    return `<tr><td>#${p.gacha_pool_id}</td><td><strong>${esc(p.name)}</strong><span class="cell-sub">${esc(p.description || '')}</span></td><td class="num">${cost}</td><td>${p.is_limited_time ? `${badge('限时', 'warn')}<span class="cell-sub">截止 ${time(p.open_until)}</span>` : badge('常驻', 'off')}</td><td class="num">${fmt(p.item_count)}</td><td>${rowActions([act('物品', 'pool-open', { id: p.gacha_pool_id }), act('编辑', 'pool-edit', { id: p.gacha_pool_id }), act('复制', 'pool-copy', { id: p.gacha_pool_id, name: p.name }), act('删除', 'pool-delete', { id: p.gacha_pool_id, name: p.name }, true)])}</td></tr>`;
  });
  return shell('抽卡池', '玩家使用“抽卡 卡池ID”“十连 卡池ID”抽取。', `<div class="panel">${table(['ID', '卡池', { label: '单抽消耗', cls: 'num' }, '开放', { label: '物品数', cls: 'num' }, '操作'], rows, '还没有卡池。')}</div>`, `<button type="button" class="btn primary" data-action="pool-create">${icon('plus')}新建卡池</button>`);
}

function poolFormBody(p = {}) {
  const currency = p.cost_premium_currency ? 'premium' : 'coins';
  return `<div class="form-grid">
    ${field({ name: 'name', label: '卡池名称', value: p.name || '', required: true, cls: 'full' })}
    ${field({ name: 'description', label: '描述', type: 'textarea', value: p.description || '', cls: 'full' })}
    ${selectField({ name: 'currency_type', label: '消耗货币', choices: [['coins', '金币'], ['premium', '高级货币']], value: currency })}
    ${field({ name: 'cost_amount', label: '单抽消耗', type: 'number', min: 0, value: (currency === 'premium' ? p.cost_premium_currency : p.cost_coins) ?? 0, hint: '0 表示免费' })}
    ${switchField({ name: 'is_limited_time', label: '限时开放', checked: !!p.is_limited_time })}
    ${field({ name: 'open_until', label: '开放截止时间', type: 'datetime-local', value: toLocalInput(p.open_until), hint: '仅在限时开放时生效' })}
  </div>`;
}

function poolDetailView() {
  const d = state.data.pool;
  if (!d) return shell('卡池', '', '<div class="panel empty">正在加载…</div>');
  const p = d.pool;
  const rows = d.rows.map(x => `<tr><td>${esc(TYPE_LABELS[x.item_type] || x.item_type)}</td><td><strong>${esc(x.item_name)}</strong>${x.item_type !== 'coins' ? `<span class="cell-sub">#${x.item_id}</span>` : ''}</td><td>${stars(x.rarity)}</td><td class="num">${fmt(x.quantity)}</td><td class="num"><input class="inline-input" type="number" min="1" value="${x.weight}" data-weight="${x.gacha_pool_item_id}" aria-label="权重"></td><td class="num">${pct(x.probability)}</td><td>${rowActions([act('编辑', 'pool-item-edit', { id: x.gacha_pool_item_id }), act('删除', 'pool-item-delete', { id: x.gacha_pool_item_id, name: x.item_name }, true)])}</td></tr>`);
  return shell(p.name, `卡池 ID ${p.gacha_pool_id} · 修改权重后按回车或移出输入框即可保存`, `<button type="button" class="back" data-action="back">${icon('back')}返回卡池列表</button>
    <div class="panel">${table(['类型', '物品', '稀有度', { label: '数量', cls: 'num' }, { label: '权重', cls: 'num' }, { label: '概率', cls: 'num' }, '操作'], rows, '卡池里还没有物品。')}</div>`,
  `<button type="button" class="btn text" data-action="pool-edit" data-id="${p.gacha_pool_id}">编辑卡池</button><button type="button" class="btn primary" data-action="pool-item-create">${icon('plus')}添加物品</button>`);
}

function openPoolItemDialog(item) {
  const type = item?.item_type || 'rod';
  openDialog({
    form: 'pool-item', title: item ? '编辑卡池物品' : '添加卡池物品', subtitle: state.data.pool.pool.name, itemPoolId: item?.gacha_pool_item_id || '',
    body: () => `<div class="form-grid" data-scope>
      ${selectField({ name: 'item_type', label: '物品类型', choices: [['rod', '鱼竿'], ['accessory', '饰品'], ['bait', '鱼饵'], ['item', '道具'], ['titles', '称号'], ['coins', '金币']], value: type, attrs: 'data-item-target="[data-role=item]"' })}
      <div class="field" data-show-for="rod accessory bait item titles"><label for="f_item_id">物品</label><select id="f_item_id" name="item_id" data-role="item">${itemSelectOptions(type === 'coins' ? 'rod' : type, item?.item_id || '')}</select></div>
      ${field({ name: 'quantity', label: '数量', type: 'number', min: 1, value: item?.quantity ?? 1, hint: '金币填发放的金币数' })}
      ${field({ name: 'weight', label: '权重', type: 'number', min: 1, value: item?.weight ?? 10, hint: '数字越大越容易抽到' })}
    </div>`,
  });
}

// ---------------------------------------------------------------------------
// 钓鱼区域
// ---------------------------------------------------------------------------

function zonesView() {
  const fishName = id => state.catalog?.fish?.find(f => f.id === id)?.name || `#${id}`;
  const itemName = id => state.catalog?.item?.find(f => f.id === id)?.name || `#${id}`;
  const rows = (state.data.zones?.rows || []).map(z => {
    const dist = (z.configs?.rarity_distribution || []).map((v, i) => `${i < 5 ? i + 1 : '6+'}★ ${pct(v, 1)}`).join(' · ');
    const fish = z.specific_fish_ids?.length ? `${z.specific_fish_ids.length} 种：${z.specific_fish_ids.slice(0, 4).map(fishName).join('、')}${z.specific_fish_ids.length > 4 ? '…' : ''}` : '全局鱼池';
    return `<tr><td>#${z.id}</td><td><strong>${esc(z.name)}</strong><span class="cell-sub">${esc(z.description || '')}</span></td><td>${yesNo(z.is_active, '开放', '关闭')}${z.available_from || z.available_until ? `<span class="cell-sub">${time(z.available_from)} ~ ${time(z.available_until)}</span>` : ''}</td><td class="num">${fmt(z.fishing_cost)}</td><td class="num">${fmt(z.rare_fish_caught_today)} / ${fmt(z.daily_rare_fish_quota)}</td><td class="wrap-text">${esc(dist)}<span class="cell-sub">${esc(fish)}</span></td><td>${z.requires_pass && z.required_item_id ? badge(itemName(z.required_item_id), 'warn') : badge('无需通行证', 'off')}</td><td>${rowActions([act('编辑', 'zone-edit', { id: z.id }), ...(z.id === 1 ? [] : [act('删除', 'zone-delete', { id: z.id, name: z.name }, true)])])}</td></tr>`;
  });
  return shell('钓鱼区域', '玩家用“钓鱼区域 ID”切换区域；稀有鱼（4 星及以上）受每日配额限制。', `<div class="panel">${table(['ID', '区域', '状态', { label: '单次消耗', cls: 'num' }, { label: '今日稀有鱼', cls: 'num' }, '稀有度分布 / 鱼池', '通行证', '操作'], rows, '还没有钓鱼区域。')}</div>`,
  `<button type="button" class="btn text" data-action="replenish">补充鱼池</button><button type="button" class="btn primary" data-action="zone-create">${icon('plus')}新建区域</button>`);
}

function zoneFormBody(z) {
  const isNew = !z;
  z = z || { is_active: true, fishing_cost: 10, daily_rare_fish_quota: 0, configs: { rarity_distribution: [0.5, 0.3, 0.15, 0.04, 0.01, 0] }, specific_fish_ids: [] };
  const dist = [...(z.configs?.rarity_distribution || [])];
  while (dist.length < 6) dist.push(0);
  const selected = new Set(z.specific_fish_ids || []);
  const fish = [...(state.catalog?.fish || [])].sort((a, b) => a.rarity - b.rarity || a.id - b.id);
  let lastRarity = null;
  const list = fish.map(f => {
    const head = f.rarity !== lastRarity ? `<div class="picker-group" data-group="${f.rarity}">${'★'.repeat(Math.min(f.rarity, 10))} ${f.rarity} 星</div>` : '';
    lastRarity = f.rarity;
    return `${head}<label class="picker-item" data-fish-name="${esc(f.name)}" data-rarity="${f.rarity}"><input type="checkbox" name="specific_fish_ids" value="${f.id}" data-multi ${selected.has(f.id) ? 'checked' : ''}><span>${esc(f.name)}</span><span class="muted">#${f.id}</span></label>`;
  }).join('');
  const passItems = [['', '选择通行证道具'], ...(state.catalog?.item || []).map(i => [i.id, `${i.name} · #${i.id}`])];
  const limited = !!(z.available_from || z.available_until);
  return `<input type="hidden" name="is_new" value="${isNew ? '1' : ''}">
  <div class="form-grid three">
    ${field({ name: 'id', label: '区域 ID', type: 'number', min: 1, value: z.id ?? '', required: true, attrs: isNew ? '' : 'readonly' })}
    ${field({ name: 'name', label: '区域名称', value: z.name || '', required: true, cls: 'wide' })}
    ${field({ name: 'description', label: '描述', type: 'textarea', value: z.description || '', cls: 'full' })}
    ${field({ name: 'fishing_cost', label: '单次钓鱼消耗 (金币)', type: 'number', min: 1, value: z.fishing_cost ?? 10 })}
    ${field({ name: 'daily_rare_fish_quota', label: '稀有鱼每日配额', type: 'number', min: 0, value: z.daily_rare_fish_quota ?? 0, hint: '0 表示不产出稀有鱼' })}
    ${switchField({ name: 'is_active', label: '开放区域', checked: z.is_active ?? true })}
    ${switchField({ name: 'limit_time', label: '限定开放时间', checked: limited })}
    ${field({ name: 'available_from', label: '开放时间', type: 'datetime-local', value: toLocalInput(z.available_from) })}
    ${field({ name: 'available_until', label: '结束时间', type: 'datetime-local', value: toLocalInput(z.available_until) })}
    ${switchField({ name: 'requires_pass', label: '需要通行证', checked: !!z.requires_pass })}
    ${selectField({ name: 'required_item_id', label: '通行证道具', choices: passItems, value: z.required_item_id ?? '', cls: 'wide', hint: '进入区域时自动消耗' })}
  </div>
  <div class="modal-section">稀有度分布 <span class="hint" id="dist-sum"></span></div>
  <div class="form-grid three" data-dist>${dist.slice(0, 6).map((v, i) => field({ name: `rarity_${i}`, label: i < 5 ? `${i + 1} 星` : '6 星及以上', type: 'number', min: 0, max: 1, step: 'any', value: v })).join('')}</div>
  <div class="modal-section">限定鱼类 <span class="hint">不选则使用全局鱼池</span></div>
  <div class="picker">
    <div class="picker-tools"><input type="search" placeholder="搜索鱼名" data-picker-search aria-label="搜索鱼名"><select data-picker-rarity aria-label="稀有度筛选">${options([['', '全部稀有度'], ...[...new Set(fish.map(f => f.rarity))].map(r => [r, `${r} 星`])], '')}</select><button type="button" class="btn text" data-action="picker-all">选中可见</button><button type="button" class="btn text" data-action="picker-none">清空</button></div>
    <div class="picker-list">${list || '<div class="empty">还没有鱼类模板。</div>'}</div>
    <div class="picker-foot" data-picker-count></div>
  </div>`;
}

function updateZoneHelpers() {
  const form = document.querySelector('form[data-form="zone"]');
  if (!form) return;
  const values = [...form.querySelectorAll('[data-dist] input')].map(i => Number(i.value || 0));
  const sum = values.reduce((a, b) => a + b, 0);
  const out = document.getElementById('dist-sum');
  if (out) { out.textContent = `合计 ${sum.toFixed(3)}${Math.abs(sum - 1) > 0.001 ? '，应为 1' : ''}`; out.style.color = Math.abs(sum - 1) > 0.001 ? 'var(--error)' : ''; }
  const checked = form.querySelectorAll('[name=specific_fish_ids]:checked').length;
  const count = form.querySelector('[data-picker-count]');
  if (count) count.textContent = checked ? `已选择 ${checked} 种鱼` : '未选择，使用全局鱼池';
  const limited = form.querySelector('[name=limit_time]').checked;
  form.querySelectorAll('[name=available_from],[name=available_until]').forEach(i => { i.disabled = !limited; });
  const pass = form.querySelector('[name=requires_pass]').checked;
  const passSelect = form.querySelector('[name=required_item_id]');
  passSelect.disabled = !pass;
  syncTrigger(passSelect);
}

function filterPicker() {
  const search = (document.querySelector('[data-picker-search]')?.value || '').trim().toLowerCase();
  const rarity = document.querySelector('[data-picker-rarity]')?.value || '';
  const visibleGroups = new Set();
  document.querySelectorAll('.picker-item').forEach(item => {
    const show = (!search || item.dataset.fishName.toLowerCase().includes(search)) && (!rarity || item.dataset.rarity === rarity);
    item.hidden = !show;
    if (show) visibleGroups.add(item.dataset.rarity);
  });
  document.querySelectorAll('.picker-group').forEach(g => { g.hidden = !visibleGroups.has(g.dataset.group); });
}

// ---------------------------------------------------------------------------
// 物品模板
// ---------------------------------------------------------------------------

function templateCell(f, value) {
  if (value === null || value === undefined || value === '') return f.optional ? '<span class="muted">-</span>' : '-';
  if (f.key === 'rarity') return stars(value);
  if (f.type === 'bool') return yesNo(value);
  if (f.type === 'select') return esc((f.options.find(o => o[0] === value) || [value, value])[1]);
  if (f.type === 'int') return fmt(value);
  return esc(value);
}

function templatesView() {
  const kinds = state.meta?.template_kinds || {};
  const kind = state.templates.kind;
  const spec = kinds[kind];
  const tabs = Object.entries(kinds).map(([k, s]) => `<button type="button" class="subtab ${k === kind ? 'active' : ''}" data-action="template-kind" data-kind="${k}">${esc(s.label)}</button>`).join('');
  if (!spec) return shell('物品模板', '', `<div class="panel"><div class="subtabs">${tabs}</div></div>`);
  const fields = Object.fromEntries(spec.fields.map(f => [f.key, f]));
  const search = state.templates.search.trim().toLowerCase();
  const PAGE = 30;
  const matched = (state.data.templates?.kind === kind ? state.data.templates.rows : [])
    .filter(r => !search || String(r.name).toLowerCase().includes(search) || String(r[spec.id_field]) === search);
  const pages = Math.max(1, Math.ceil(matched.length / PAGE));
  state.templates.page = Math.min(Math.max(1, state.templates.page), pages);
  const pageInfo = { current_page: state.templates.page, total_pages: pages, total_count: matched.length };
  const rows = matched.slice((state.templates.page - 1) * PAGE, state.templates.page * PAGE)
    .map(r => `<tr><td>#${r[spec.id_field]}</td>${spec.columns.map(c => c === 'name' ? `<td><strong>${esc(r.name)}</strong>${r.description ? `<span class="cell-sub">${esc(r.description)}</span>` : ''}</td>` : `<td class="${['int', 'float'].includes(fields[c]?.type) ? 'num' : ''}">${templateCell(fields[c] || {}, r[c])}</td>`).join('')}<td>${rowActions([act('编辑', 'template-edit', { id: r[spec.id_field] }), act('删除', 'template-delete', { id: r[spec.id_field], name: r.name }, true)])}</td></tr>`);
  const headers = ['ID', ...spec.columns.map(c => ({ label: fields[c]?.label || c, cls: ['int', 'float'].includes(fields[c]?.type) ? 'num' : '' })), '操作'];
  return shell('物品模板', '鱼类、鱼竿、鱼饵、饰品与道具的基础数据。仍被玩家、卡池或商店使用的模板无法删除。', `<div class="panel">
    <div class="subtabs">${tabs}</div>
    <form class="toolbar" data-filter="templates"><input class="grow" name="search" value="${esc(state.templates.search)}" placeholder="按名称或 ID 搜索${esc(spec.label)}" aria-label="搜索"><button type="submit" class="btn tonal">查询</button>
      <button type="button" class="btn text" data-action="template-csv">${icon('download')}CSV 模板</button>
      <label class="btn text" for="csv-import">${icon('upload')}导入 CSV</label><input id="csv-import" class="hidden-input" type="file" accept=".csv,text/csv">
      <button type="button" class="btn primary" data-action="template-create">${icon('plus')}新建${esc(spec.label)}</button></form>
    ${table(headers, rows, `没有匹配的${spec.label}。`)}
    ${pagination(pageInfo, 'templates')}
  </div>`);
}

function templateFormBody(spec, row = {}) {
  return `<div class="form-grid">${spec.fields.map(f => {
    const value = row[f.key] ?? (row[spec.id_field] ? '' : f.default ?? '');
    const cls = f.type === 'textarea' ? 'full' : '';
    if (f.type === 'bool') return switchField({ name: f.key, label: f.label, checked: row[spec.id_field] ? !!row[f.key] : !!f.default });
    if (f.type === 'select') return selectField({ name: f.key, label: f.label, choices: f.options, value: value || f.default, hint: f.hint || '' });
    const type = f.type === 'textarea' ? 'textarea' : ['int', 'float'].includes(f.type) ? 'number' : 'text';
    return field({ name: f.key, label: f.label, type, value, required: !!f.required, min: f.min, max: f.max, step: f.type === 'float' ? 'any' : undefined, hint: f.hint || '', cls });
  }).join('')}</div>`;
}

function csvTemplate(spec) {
  const cell = v => /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
  const keys = spec.fields.map(f => f.key);
  const sample = spec.fields.map(f => f.key === 'name' ? `示例${spec.label}` : f.type === 'bool' ? (f.default ? 1 : 0) : f.default ?? '');
  return '﻿' + [keys, sample].map(r => r.map(cell).join(',')).join('\n') + '\n';
}

// ---------------------------------------------------------------------------
// 称号
// ---------------------------------------------------------------------------

function titlesView() {
  const rows = (state.data.titles?.rows || []).map(t => `<tr><td>#${t.title_id}</td><td><strong>${esc(t.name)}</strong></td><td class="wrap-text">${esc(t.description || '')}</td><td><code class="code">${esc(t.display_format || '{name}')}</code></td><td>${rowActions([act('编辑', 'title-edit', { id: t.title_id }), act('删除', 'title-delete', { id: t.title_id, name: t.name }, true)])}</td></tr>`);
  return shell('称号', '成就会自动发放部分称号；在玩家详情里可以手动授予或移除。', `<div class="panel">${table(['ID', '名称', '描述', '显示格式', '操作'], rows, '还没有称号。')}</div>`, `<button type="button" class="btn primary" data-action="title-create">${icon('plus')}新建称号</button>`);
}

function titleFormBody(t = {}) {
  return `<div class="form-grid">
    ${field({ name: 'name', label: '称号名称', value: t.name || '', required: true, cls: 'full' })}
    ${field({ name: 'description', label: '描述', type: 'textarea', value: t.description || '', cls: 'full', placeholder: '留空时自动生成' })}
    ${field({ name: 'display_format', label: '显示格式', value: t.display_format || '{name}', cls: 'full', hint: '{name} 为称号名，{username} 为玩家昵称' })}
  </div>`;
}

// ---------------------------------------------------------------------------
// 全服操作
// ---------------------------------------------------------------------------

function opsView() {
  const imp = state.data.impersonation?.rows || [];
  const impRows = imp.map(r => `<tr><td>${esc(r.admin_id)}</td><td><strong>${esc(r.target_nickname || '未知玩家')}</strong><span class="cell-sub">${esc(r.target_id)}</span></td><td>${rowActions([act('结束代理', 'imp-stop', { id: r.admin_id }, true)])}</td></tr>`);
  return shell('全服操作', '原管理员指令对应的批量操作。系统账号（如市场托管）不参与。', `<div class="stack">
    <section class="grid two">
      <div class="panel"><h3>全体货币</h3><p>给所有玩家发放或扣除金币、高级货币。扣除时余额不足的扣到 0。</p>
        <form data-form="broadcast-currency" novalidate><div class="form-grid">
          ${selectField({ name: 'currency', label: '货币', choices: [['coins', '金币'], ['premium_currency', '高级货币']] })}
          ${selectField({ name: 'mode', label: '操作', choices: [['add', '发放'], ['subtract', '扣除']] })}
          ${field({ name: 'amount', label: '每人数量', type: 'number', min: 1, required: true, cls: 'full' })}
        </div><div class="form-actions" style="margin-top:16px"><button type="submit" class="btn primary">执行</button></div></form></div>
      <div class="panel"><h3>全体发放物品</h3><p>给所有玩家发放同一种物品。</p>
        <form data-form="broadcast-item" novalidate>${itemPickerFields()}<div class="form-actions" style="margin-top:16px"><button type="submit" class="btn primary">发放</button></div></form></div>
    </section>
    <section class="grid two">
      <div class="panel"><h3>数据维护</h3>
        <div class="list-card">
          <div class="row"><div><h4>同步初始设定</h4><p>按插件内置数据补齐缺失的物品、商店与卡池，不会删除已有内容。</p></div><button type="button" class="btn tonal" data-action="sync">同步</button></div>
          <div class="row"><div><h4>补充鱼池</h4><p>把所有区域今天已钓走的稀有鱼数量清零，配额恢复为满。</p></div><button type="button" class="btn tonal" data-action="replenish">补充</button></div>
        </div></div>
      <div class="panel"><h3>代理玩家</h3><p>开启后，该账号在聊天中发送的游戏指令会以目标玩家的身份执行。重载插件后自动失效。</p>
        <form data-form="imp-start" novalidate><div class="form-grid">${field({ name: 'admin_id', label: '你的账号 ID', required: true, placeholder: '例如你的 QQ 号' })}${field({ name: 'target_id', label: '目标玩家 ID', required: true })}</div><div class="form-actions" style="margin-top:16px"><button type="submit" class="btn primary">开始代理</button></div></form>
        <div style="margin-top:16px">${table(['账号', '代理的玩家', '操作'], impRows, '当前没有进行中的代理。')}</div></div>
    </section>
  </div>`);
}

function openBroadcastDialog(kind) {
  if (kind === 'currency') {
    openDialog({ form: 'broadcast-currency', title: '全体发放金币', subtitle: '给所有玩家发放或扣除货币', submit: '执行', body: () => `<div class="form-grid">${selectField({ name: 'currency', label: '货币', choices: [['coins', '金币'], ['premium_currency', '高级货币']] })}${selectField({ name: 'mode', label: '操作', choices: [['add', '发放'], ['subtract', '扣除']] })}${field({ name: 'amount', label: '每人数量', type: 'number', min: 1, required: true, cls: 'full' })}</div>` });
  } else {
    openDialog({ form: 'broadcast-item', title: '全体发放物品', subtitle: '给所有玩家发放同一种物品', submit: '发放', body: () => itemPickerFields() });
  }
}

// ---------------------------------------------------------------------------
// 渲染
// ---------------------------------------------------------------------------

const VIEWS = { overview: overviewView, users: usersView, market: marketView, exchange: exchangeView, shops: shopsView, gacha: gachaView, zones: zonesView, templates: templatesView, titles: titlesView, ops: opsView };

function render() {
  closeMenu();
  if (state.fatal) { app.innerHTML = `<div class="loading-screen"><div class="panel empty">${esc(state.fatal)}</div></div>`; return; }
  if (state.loading) { app.innerHTML = '<div class="loading-screen">正在连接钓鱼插件…</div>'; return; }
  app.innerHTML = VIEWS[state.tab]() + dialogView() + confirmView();
  bind();
}

function bind() {
  enhanceSelects();
  applyShowFor(document);
  if (state.dialog?.form === 'zone') { updateZoneHelpers(); filterPicker(); }
}

// 依据类型显示或隐藏相关字段（品质、精炼等级、物品选择）
function applyShowFor(root) {
  root.querySelectorAll('[data-scope]').forEach(scope => {
    const typeSelect = scope.querySelector('select[data-item-target]');
    if (!typeSelect) return;
    const type = typeSelect.value;
    scope.querySelectorAll('[data-show-for]').forEach(el => {
      if (el.closest('[data-scope]') !== scope) return;
      const show = el.dataset.showFor.split(' ').includes(type);
      el.style.visibility = show ? '' : 'hidden';
      el.style.display = show || el.closest('.editor-row') ? '' : 'none';
      el.querySelectorAll('input,select').forEach(i => { i.disabled = !show; if (i.tagName === 'SELECT') syncTrigger(i); });
    });
  });
}

// ---------------------------------------------------------------------------
// 交互
// ---------------------------------------------------------------------------

function findUser(id) {
  return state.data.users?.users?.find(u => u.user_id === id);
}

const ACTIONS = {
  refresh: async () => { await loadCatalog(); await refresh(); notify('已刷新'); },
  goto: async b => { if (b.dataset.kind) state.templates.kind = b.dataset.kind; await switchTab(b.dataset.tab); },
  back: async () => { state.sub = null; await refresh(); },
  page: async b => { state[b.dataset.scope].page = Number(b.dataset.page); if (b.dataset.scope === 'templates') render(); else await refresh(); window.scrollTo(0, 0); },
  'dialog-cancel': () => closeDialog(),
  'confirm-cancel': () => { state.confirm = null; render(); },
  'confirm-submit': async () => { const c = state.confirm; state.confirm = null; render(); try { const r = await c.run(); if (r?.message) notify(r.message); } catch (e) { notify(errText(e), true); } },

  // 玩家
  'user-create': () => openDialog({ form: 'user-create', title: '新建玩家', subtitle: '手动登记一位玩家', size: 'wide', submit: '创建', body: () => userFormBody() }),
  'user-edit': b => { const u = findUser(b.dataset.id); openDialog({ form: 'user-update', title: '编辑玩家', subtitle: u.nickname || u.user_id, size: 'wide', body: () => userFormBody(u) }); },
  'user-detail': b => openUserDetail(b.dataset.id),
  'user-currency': b => openCurrencyDialog(findUser(b.dataset.id)),
  'user-inventory': async b => { state.sub = { type: 'inventory', user_id: b.dataset.id }; await refresh(); window.scrollTo(0, 0); },
  'user-delete': b => { const u = findUser(b.dataset.id); confirmAction({ title: '删除玩家', message: `确定删除 ${u.nickname || u.user_id}（${u.user_id}）吗？其库存、记录都会一并删除，且无法恢复。`, label: '删除玩家', run: async () => { const r = await post('users/delete', { user_id: u.user_id }); await refresh(); return r; } }); },
  'title-revoke': b => confirmAction({ title: '移除称号', message: `确定从 ${b.dataset.user} 移除称号“${b.dataset.name}”吗？`, label: '移除', run: async () => { const r = await post('users/titles/revoke', { user_id: b.dataset.user, title_name: b.dataset.name }); await openUserDetail(b.dataset.user); return r; } }),
  'inv-add': b => openDialog({ form: 'inv-add', title: '添加物品', subtitle: `给 ${state.data.inventory.nickname || b.dataset.user} 添加物品`, userId: b.dataset.user, submit: '添加', body: () => itemPickerFields() }),
  'inv-remove': b => openDialog({ form: 'inv-remove', title: '移除物品', subtitle: `${TYPE_LABELS[b.dataset.type]} #${b.dataset.item}`, userId: b.dataset.user, itemType: b.dataset.type, itemId: b.dataset.item, submit: '移除', danger: true, body: () => `<div class="form-grid">${field({ name: 'quantity', label: '移除数量', type: 'number', min: 1, max: b.dataset.max, value: 1, cls: 'full', hint: `当前持有 ${b.dataset.max}${['rod', 'accessory'].includes(b.dataset.type) ? '（同种装备按数量依次移除）' : ''}` })}</div>` }),
  'rod-edit': b => openDialog({ form: 'rod-edit', title: '编辑鱼竿', subtitle: `实例 #${b.dataset.id}`, userId: b.dataset.user, instanceId: b.dataset.id, body: () => `<div class="form-grid">${field({ name: 'refine_level', label: '精炼等级', type: 'number', min: 1, max: 10, value: b.dataset.refine })}${field({ name: 'durability', label: '耐久度', type: 'number', min: 0, value: b.dataset.durability, hint: '留空表示无限耐久' })}</div>` }),
  'acc-edit': b => openDialog({ form: 'acc-edit', title: '编辑饰品', subtitle: `实例 #${b.dataset.id}`, userId: b.dataset.user, instanceId: b.dataset.id, body: () => `<div class="form-grid">${field({ name: 'refine_level', label: '精炼等级', type: 'number', min: 1, max: 10, value: b.dataset.refine, cls: 'full' })}</div>` }),


  // 市场与交易所
  'market-price': b => openDialog({ form: 'market-price', title: '修改价格', subtitle: b.dataset.name, marketId: b.dataset.id, body: () => `<div class="form-grid">${field({ name: 'price', label: '新单价', type: 'number', min: 1, value: b.dataset.price, required: true, cls: 'full' })}</div>` }),
  'market-remove': b => confirmAction({ title: '下架商品', message: `确定下架 #${b.dataset.id}「${b.dataset.name}」吗？物品会退回卖家。`, label: '下架', run: async () => { const r = await post('market/remove', { market_id: b.dataset.id }); await refresh(); return r; } }),
  'exchange-update': () => confirmAction({ title: '刷新价格', message: '立即按市场规则生成一次新价格吗？', label: '刷新', danger: false, run: async () => { const r = await post('exchange/update'); await refresh(); return r; } }),
  'exchange-reset': () => confirmAction({ title: '重置价格', message: '把所有商品价格恢复为初始值吗？', label: '重置', run: async () => { const r = await post('exchange/reset'); await refresh(); return r; } }),

  // 商店
  'shop-create': () => openDialog({ form: 'shop', title: '新建商店', size: 'wide', submit: '创建', body: () => shopFormBody() }),
  'shop-edit': b => { const id = Number(b.dataset.id); const s = state.data.shops?.rows?.find(x => x.shop_id === id) || state.data.shop?.shop; openDialog({ form: 'shop', title: '编辑商店', subtitle: s.name, size: 'wide', shopId: id, body: () => shopFormBody(s) }); },
  'shop-delete': b => confirmAction({ title: '删除商店', message: `确定删除商店「${b.dataset.name}」及其全部商品吗？`, label: '删除商店', run: async () => { const r = await post('shops/delete', { shop_id: b.dataset.id }); await refresh(); return r; } }),
  'shop-open': async b => { state.sub = { type: 'shop', shop_id: Number(b.dataset.id) }; await refresh(); window.scrollTo(0, 0); },
  'shop-item-create': () => openShopItemDialog(null),
  'shop-item-edit': b => openShopItemDialog(state.data.shop.rows.find(r => r.item.item_id === Number(b.dataset.id))),
  'shop-item-delete': b => confirmAction({ title: '删除商品', message: `确定删除商品「${b.dataset.name}」吗？`, label: '删除', run: async () => { const r = await post('shops/items/delete', { item_id: b.dataset.id }); await refresh(); return r; } }),
  'row-add': b => { readRows(); state.dialog[b.dataset.list].push(b.dataset.list === 'costs' ? { cost_type: 'coins', cost_amount: 1, cost_relation: 'and' } : { reward_type: 'item', reward_quantity: 1 }); render(); },
  'row-remove': b => { readRows(); state.dialog[b.dataset.list].splice(Number(b.dataset.index), 1); render(); },

  // 抽卡
  'pool-create': () => openDialog({ form: 'pool', title: '新建卡池', submit: '创建', body: () => poolFormBody() }),
  'pool-edit': b => { const id = Number(b.dataset.id); const p = state.data.gacha?.rows?.find(x => x.gacha_pool_id === id) || state.data.pool?.pool; openDialog({ form: 'pool', title: '编辑卡池', subtitle: p.name, poolId: id, body: () => poolFormBody(p) }); },
  'pool-copy': b => confirmAction({ title: '复制卡池', message: `复制卡池「${b.dataset.name}」及其全部物品吗？`, label: '复制', danger: false, run: async () => { const r = await post('gacha/copy', { pool_id: b.dataset.id }); await refresh(); return r; } }),
  'pool-delete': b => confirmAction({ title: '删除卡池', message: `确定删除卡池「${b.dataset.name}」吗？`, label: '删除卡池', run: async () => { const r = await post('gacha/delete', { pool_id: b.dataset.id }); await refresh(); return r; } }),
  'pool-open': async b => { state.sub = { type: 'pool', pool_id: Number(b.dataset.id) }; await refresh(); window.scrollTo(0, 0); },
  'pool-item-create': () => openPoolItemDialog(null),
  'pool-item-edit': b => openPoolItemDialog(state.data.pool.rows.find(r => r.gacha_pool_item_id === Number(b.dataset.id))),
  'pool-item-delete': b => confirmAction({ title: '删除卡池物品', message: `确定从卡池移除「${b.dataset.name}」吗？`, label: '删除', run: async () => { const r = await post('gacha/items/delete', { gacha_pool_item_id: b.dataset.id }); await refresh(); return r; } }),

  // 区域
  'zone-create': () => openDialog({ form: 'zone', title: '新建钓鱼区域', size: 'xwide', submit: '创建', body: () => zoneFormBody(null) }),
  'zone-edit': b => { const z = state.data.zones.rows.find(x => x.id === Number(b.dataset.id)); openDialog({ form: 'zone', title: '编辑钓鱼区域', subtitle: z.name, size: 'xwide', body: () => zoneFormBody(z) }); },
  'zone-delete': b => confirmAction({ title: '删除钓鱼区域', message: `确定删除区域「${b.dataset.name}」吗？位于该区域的玩家下次钓鱼时会回到 1 号区域。`, label: '删除区域', run: async () => { const r = await post('zones/delete', { id: b.dataset.id }); await refresh(); return r; } }),
  'picker-all': () => { document.querySelectorAll('.picker-item:not([hidden]) input').forEach(i => { i.checked = true; }); updateZoneHelpers(); },
  'picker-none': () => { document.querySelectorAll('.picker-item input').forEach(i => { i.checked = false; }); updateZoneHelpers(); },

  // 模板
  'template-kind': async b => { state.templates.kind = b.dataset.kind; state.templates.search = ''; state.templates.page = 1; await refresh(); },
  'template-create': () => { const spec = state.meta.template_kinds[state.templates.kind]; openDialog({ form: 'template', title: `新建${spec.label}`, size: 'wide', submit: '创建', body: () => templateFormBody(spec) }); },
  'template-edit': b => { const spec = state.meta.template_kinds[state.templates.kind]; const row = state.data.templates.rows.find(r => String(r[spec.id_field]) === b.dataset.id); openDialog({ form: 'template', title: `编辑${spec.label}`, subtitle: row.name, size: 'wide', templateId: b.dataset.id, body: () => templateFormBody(spec, row) }); },
  'template-delete': b => { const spec = state.meta.template_kinds[state.templates.kind]; confirmAction({ title: `删除${spec.label}`, message: `确定删除「${b.dataset.name}」吗？删除后无法恢复。`, label: '删除', run: async () => { const r = await post('templates/delete', { kind: state.templates.kind, id: b.dataset.id }); await loadCatalog(); await refresh(); return r; } }); },
  'template-csv': () => { const spec = state.meta.template_kinds[state.templates.kind]; download(`${state.templates.kind}_template.csv`, csvTemplate(spec)); notify(`已下载${spec.label} CSV 模板`); },

  // 称号
  'title-create': () => openDialog({ form: 'title', title: '新建称号', submit: '创建', body: () => titleFormBody() }),
  'title-edit': b => { const t = state.data.titles.rows.find(x => x.title_id === Number(b.dataset.id)); openDialog({ form: 'title', title: '编辑称号', subtitle: t.name, titleId: t.title_id, body: () => titleFormBody(t) }); },
  'title-delete': b => confirmAction({ title: '删除称号', message: `确定删除称号「${b.dataset.name}」吗？`, label: '删除', run: async () => { const r = await post('titles/delete', { title_id: b.dataset.id }); await loadCatalog(); await refresh(); return r; } }),

  // 全服
  'broadcast-currency': () => openBroadcastDialog('currency'),
  'broadcast-item': () => openBroadcastDialog('item'),
  sync: () => confirmAction({ title: '同步初始设定', message: '按插件内置数据补齐缺失的物品、商店与卡池吗？已有内容不会被删除。', label: '同步', danger: false, run: async () => { const r = await post('ops/sync'); await loadCatalog(); await refresh(); return r; } }),
  replenish: () => confirmAction({ title: '补充鱼池', message: '把所有区域今天已钓走的稀有鱼数量清零吗？', label: '补充', danger: false, run: async () => { const r = await post('ops/replenish'); await refresh(); return r; } }),
  'imp-stop': b => confirmAction({ title: '结束代理', message: `结束账号 ${b.dataset.id} 的代理吗？`, label: '结束代理', run: async () => { const r = await post('ops/impersonation/stop', { admin_id: b.dataset.id }); await refresh(); return r; } }),
};

// 表单提交：返回 {message} 时关闭对话框并提示
const FORMS = {
  'user-create': v => post('users/create', { ...v, coins: v.coins === '' ? undefined : v.coins }),
  'user-update': v => post('users/update', v),
  'user-currency': (v, d) => post('users/currency', { ...v, user_id: d.userId }),
  'title-grant': async (v, d) => { if (!v.title_name) throw new Error('请选择要授予的称号'); const r = await post('users/titles/grant', { user_id: d.userId, title_name: v.title_name }); await openUserDetail(d.userId); notify(r.message || '称号已授予'); return { keepOpen: true }; },
  'inv-add': (v, d) => post('users/inventory/add', { ...v, user_id: d.userId }),
  'inv-remove': (v, d) => post('users/inventory/remove', { quantity: v.quantity, user_id: d.userId, item_type: d.itemType, item_id: d.itemId }),
  'rod-edit': (v, d) => post('users/inventory/rod', { ...v, user_id: d.userId, instance_id: d.instanceId }),
  'acc-edit': (v, d) => post('users/inventory/accessory', { ...v, user_id: d.userId, instance_id: d.instanceId }),
  'market-price': (v, d) => post('market/price', { ...v, market_id: d.marketId }),
  shop: (v, d) => post('shops/save', { ...v, shop_id: d.shopId || '' }),
  'shop-item': async (v, d) => { readRows(); return post('shops/items/save', { ...formValues(document.querySelector('form[data-form="shop-item"]')), shop_id: state.data.shop.shop.shop_id, item_id: d.itemId, costs: d.costs, rewards: d.rewards }); },
  pool: (v, d) => post('gacha/save', { ...v, pool_id: d.poolId || '' }),
  'pool-item': (v, d) => post('gacha/items/save', { ...v, pool_id: state.data.pool.pool.gacha_pool_id, gacha_pool_item_id: d.itemPoolId }),
  zone: v => post('zones/save', { ...v, rarity_distribution: [0, 1, 2, 3, 4, 5].map(i => v[`rarity_${i}`]), specific_fish_ids: v.specific_fish_ids || [] }),
  template: (v, d) => post('templates/save', { kind: state.templates.kind, id: d.templateId || '', data: v }),
  title: (v, d) => post('titles/save', { ...v, title_id: d.titleId || '' }),
  'broadcast-currency': v => post('broadcast/currency', v),
  'broadcast-item': v => post('broadcast/item', v),
  'imp-start': v => post('ops/impersonation/start', v),
};
// 改动模板、称号、区域后，物品下拉要跟着更新
const CATALOG_FORMS = new Set(['template', 'title', 'zone', 'user-create']);
const CONFIRM_FORMS = {
  'broadcast-currency': v => `确定给所有玩家${v.mode === 'add' ? '发放' : '扣除'}每人 ${fmt(v.amount)} ${v.currency === 'coins' ? '金币' : '高级货币'}吗？`,
  'broadcast-item': v => `确定给所有玩家发放 ${TYPE_LABELS[v.item_type]} #${v.item_id} ×${v.quantity} 吗？`,
};

async function submitForm(form) {
  const name = form.dataset.form;
  const handler = FORMS[name];
  if (!handler) return;
  const values = formValues(form);
  const inDialog = !!form.closest('.modal');
  const run = async () => {
    const button = form.querySelector('[type=submit]');
    if (button) button.disabled = true;
    try {
      const result = await handler(values, state.dialog || {});
      if (result?.keepOpen) return;
      if (inDialog) state.dialog = null;
      if (CATALOG_FORMS.has(name)) await loadCatalog();
      await refresh();
      notify(result?.message || '已保存');
    } catch (error) {
      if (inDialog && state.dialog) showDialogError(errText(error)); else notify(errText(error), true);
    } finally { if (button?.isConnected) button.disabled = false; }
  };
  if (!inDialog && CONFIRM_FORMS[name]) { confirmAction({ title: '确认操作', message: CONFIRM_FORMS[name](values), label: '确认执行', run: async () => { await run(); } }); return; }
  await run();
}

async function submitFilter(form) {
  const scope = form.dataset.filter;
  const values = formValues(form);
  Object.assign(state[scope], values);
  if ('page' in state[scope]) state[scope].page = 1;
  if (scope === 'templates') { render(); return; }
  await refresh();
}

app.addEventListener('click', async event => {
  const button = event.target.closest('[data-action],[data-nav]');
  if (!button || button.disabled) return;
  if (button.dataset.nav) { try { await switchTab(button.dataset.nav); } catch (e) { notify(errText(e), true); } return; }
  const handler = ACTIONS[button.dataset.action];
  if (!handler) return;
  try { await handler(button); } catch (error) { notify(errText(error), true); }
});

app.addEventListener('submit', event => {
  const form = event.target;
  event.preventDefault();
  if (form.dataset.form) submitForm(form);
  else if (form.dataset.filter) submitFilter(form).catch(e => notify(errText(e), true));
});

app.addEventListener('mousedown', event => {
  const backdrop = event.target.closest('[data-backdrop]');
  if (backdrop && event.target === backdrop) {
    if (backdrop.dataset.backdrop === 'dialog') closeDialog(); else { state.confirm = null; render(); }
  }
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || openSelect) return;
  if (state.confirm) { state.confirm = null; render(); } else if (state.dialog) closeDialog();
});

app.addEventListener('change', async event => {
  const el = event.target;
  if (el.matches('select[data-item-target]')) {
    const scope = el.closest('[data-scope]');
    const target = scope?.querySelector(el.dataset.itemTarget);
    if (target && state.catalog?.[el.value]) { target.innerHTML = itemSelectOptions(el.value, ''); syncTrigger(target); }
    applyShowFor(scope.parentElement || document);
  }
  if (el.id === 'csv-import' && el.files?.[0]) {
    const file = el.files[0];
    el.value = '';
    try {
      const text = await file.text();
      const r = await post('templates/import', { kind: state.templates.kind, csv: text });
      await loadCatalog(); await refresh();
      notify(r.errors?.length ? `${r.message}。${r.errors.join('；')}` : r.message, !r.imported);
    } catch (error) { notify(errText(error), true); }
  }
  if (el.dataset.weight) {
    const weight = Number(el.value);
    if (!Number.isInteger(weight) || weight < 1) { notify('权重必须是大于 0 的整数', true); return; }
    try { await post('gacha/items/save', { gacha_pool_item_id: el.dataset.weight, ...poolItemPayload(Number(el.dataset.weight), weight) }); await refresh(); notify('权重已更新'); }
    catch (error) { notify(errText(error), true); }
  }
  if (el.closest('form[data-form="zone"]')) updateZoneHelpers();
  if (el.matches('[data-picker-rarity]')) filterPicker();
});

app.addEventListener('input', event => {
  if (event.target.matches('[data-picker-search]')) filterPicker();
  if (event.target.closest('[data-dist]')) updateZoneHelpers();
});

app.addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target.dataset?.weight) { event.preventDefault(); event.target.blur(); }
});

function poolItemPayload(id, weight) {
  const row = state.data.pool.rows.find(r => r.gacha_pool_item_id === id);
  return { item_type: row.item_type, item_id: row.item_id, quantity: row.quantity, weight };
}

// ---------------------------------------------------------------------------
// 下拉框：保留原生 select 作为数据源，绘制 Vuetify v-select 风格的浮层菜单
// ---------------------------------------------------------------------------

let openSelect = null;
const selectMenu = document.createElement('div');
selectMenu.className = 'select-menu';
selectMenu.setAttribute('role', 'listbox');
selectMenu.hidden = true;
document.body.appendChild(selectMenu);

function selectTrigger(select) { return select.parentElement?.querySelector(':scope > .select-trigger'); }

function syncTrigger(select) {
  const trigger = selectTrigger(select);
  if (!trigger) return;
  const value = select.selectedOptions[0]?.textContent || '';
  trigger.querySelector('.select-value').textContent = value;
  trigger.disabled = select.disabled;
  trigger.setAttribute('aria-label', trigger.dataset.label ? `${trigger.dataset.label}：${value}` : value);
}

function enhanceSelects() {
  document.querySelectorAll('#app select:not(.native)').forEach(select => {
    const wrap = document.createElement('div');
    wrap.className = 'select';
    select.classList.add('native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'select-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.dataset.label = select.getAttribute('aria-label') || (select.id && document.querySelector(`label[for="${select.id}"]`)?.textContent.trim()) || '';
    trigger.innerHTML = `<span class="select-value"></span>${icon('menuDown')}`;
    select.before(wrap);
    wrap.append(select, trigger);
    syncTrigger(select);
    trigger.addEventListener('click', () => (openSelect === select ? closeMenu() : openMenu(select)));
    trigger.addEventListener('keydown', event => { if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) { event.preventDefault(); openMenu(select); } });
    select.addEventListener('focus', () => trigger.focus());
    select.addEventListener('change', () => syncTrigger(select));
  });
  document.querySelectorAll('#app select.native').forEach(syncTrigger);
}

function placeMenu(trigger) {
  const rect = trigger.getBoundingClientRect();
  selectMenu.style.minWidth = `${rect.width}px`;
  selectMenu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - selectMenu.offsetWidth - 8))}px`;
  const below = window.innerHeight - rect.bottom - 8;
  const height = selectMenu.offsetHeight;
  selectMenu.style.top = `${height > below && rect.top > below ? Math.max(8, rect.top - height - 4) : rect.bottom + 4}px`;
}

function openMenu(select) {
  closeMenu();
  const trigger = selectTrigger(select);
  if (!trigger || select.disabled) return;
  openSelect = select;
  trigger.setAttribute('aria-expanded', 'true');
  trigger.classList.add('open');
  selectMenu.innerHTML = [...select.options].map((option, index) => `<button type="button" class="select-option ${option.selected ? 'selected' : ''}" role="option" aria-selected="${option.selected}" data-option="${index}">${esc(option.textContent)}</button>`).join('');
  selectMenu.hidden = false;
  placeMenu(trigger);
  const current = selectMenu.querySelector('.selected') || selectMenu.firstElementChild;
  if (current) selectMenu.scrollTop = Math.max(0, current.offsetTop - (selectMenu.clientHeight - current.offsetHeight) / 2);
  current?.focus({ preventScroll: true });
}

function closeMenu(focusTrigger = false) {
  if (!openSelect) return;
  const trigger = selectTrigger(openSelect);
  openSelect = null;
  selectMenu.hidden = true;
  selectMenu.innerHTML = '';
  trigger?.setAttribute('aria-expanded', 'false');
  trigger?.classList.remove('open');
  if (focusTrigger && trigger?.isConnected) trigger.focus();
}

function chooseOption(index) {
  const select = openSelect;
  if (!select) return;
  const changed = select.selectedIndex !== index;
  select.selectedIndex = index;
  closeMenu(true);
  if (changed) select.dispatchEvent(new Event('change', { bubbles: true }));
}

selectMenu.addEventListener('click', event => { const option = event.target.closest('.select-option'); if (option) chooseOption(Number(option.dataset.option)); });
selectMenu.addEventListener('keydown', event => {
  const items = [...selectMenu.querySelectorAll('.select-option')];
  const index = items.indexOf(document.activeElement);
  const moves = { ArrowDown: Math.min(items.length - 1, index + 1), ArrowUp: Math.max(0, index - 1), Home: 0, End: items.length - 1 };
  if (event.key in moves) { event.preventDefault(); items[moves[event.key]]?.focus(); }
  else if (event.key === 'Escape' || event.key === 'Tab') { event.preventDefault(); closeMenu(true); }
  else if (event.key.length === 1) {
    // 按首字母跳转，长列表（如上百种鱼）更好找
    const key = event.key.toLowerCase();
    const next = items.find((item, i) => i > index && item.textContent.toLowerCase().startsWith(key)) || items.find(item => item.textContent.toLowerCase().startsWith(key));
    next?.focus();
  }
});
document.addEventListener('mousedown', event => { if (openSelect && !selectMenu.contains(event.target) && !openSelect.parentElement?.contains(event.target)) closeMenu(); });
function followTrigger() {
  const trigger = openSelect && selectTrigger(openSelect);
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  if (rect.bottom < 0 || rect.top > window.innerHeight) closeMenu(); else placeMenu(trigger);
}
document.addEventListener('scroll', event => { if (!selectMenu.contains(event.target)) followTrigger(); }, true);
window.addEventListener('resize', followTrigger);

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------

(async () => {
  render();
  if (!bridge) { state.fatal = '请在 AstrBot 面板的插件详情页中打开钓鱼管理页。'; render(); return; }
  try {
    const context = await bridge.ready();
    const applyTheme = ctx => { document.documentElement.dataset.theme = ctx?.isDark ? 'dark' : 'light'; };
    applyTheme(context);
    bridge.onContext?.(applyTheme);
    [state.meta] = await Promise.all([get('meta'), loadCatalog()]);
    await LOADERS.overview();
    state.loading = false;
    render();
  } catch (error) {
    state.fatal = `无法连接钓鱼插件：${errText(error)}`;
    render();
  }
})();
