import { api } from './api.js';
import { store, initTheme, loadLLM, applyTheme, toggleTheme, logoutLocal } from './store.js';
import {
  icon, avatar, toast, setUnread, notifyBrowser, loadingBlock, timeAgo
} from './ui.js';
import { renderLogin } from './views/auth.js';
import { renderDashboard } from './views/dashboard.js';
import { renderChat } from './views/chat.js';
import { renderTasks } from './views/tasks.js';
import { renderPlans } from './views/plans.js';
import { renderNews, renderPapers, renderStudy } from './views/discover.js';
import { renderSources } from './views/sources.js';
import { renderForumList, renderForumPost, renderForumNew, renderForumUser } from './views/forum.js';
import { renderMessages, renderNotifications, renderProfile } from './views/social.js';
import { renderAdmin } from './views/admin.js';

const routes = [
  { pattern: /^\/$/, view: renderDashboard, title: '工作台', eyebrow: '今天', nav: '#/' },
  { pattern: /^\/ask$/, view: renderChat, props: { mode: 'official' }, title: '官网文件问答', eyebrow: '检索增强', nav: '#/ask' },
  { pattern: /^\/academic$/, view: renderChat, props: { mode: 'academic' }, title: '学业问答', eyebrow: 'AI 学习助手', nav: '#/academic' },
  { pattern: /^\/tasks$/, view: renderTasks, title: '待办与提醒', eyebrow: '主动提醒', nav: '#/tasks' },
  { pattern: /^\/plans$/, view: renderPlans, title: '定期计划', eyebrow: '日拱一卒', nav: '#/plans' },
  { pattern: /^\/news$/, view: renderNews, title: '今日热点', eyebrow: '天下事', nav: '#/news' },
  { pattern: /^\/papers$/, view: renderPapers, title: '论文推荐', eyebrow: '学术前沿', nav: '#/papers' },
  { pattern: /^\/study$/, view: renderStudy, title: '学习资料', eyebrow: '按年级与课程', nav: '#/study' },
  { pattern: /^\/sources$/, view: renderSources, title: '官网文件', eyebrow: '学校公开信息', nav: '#/sources' },
  { pattern: /^\/forum$/, view: renderForumList, title: '校园论坛', eyebrow: 'ECNU 社区', nav: '#/forum' },
  { pattern: /^\/forum\/new$/, view: renderForumNew, title: '发布帖子', eyebrow: '校园论坛', nav: '#/forum' },
  { pattern: /^\/forum\/(\d+)$/, view: renderForumPost, title: '帖子详情', eyebrow: '校园论坛', nav: '#/forum' },
  { pattern: /^\/forum\/user\/(\d+)$/, view: renderForumUser, title: '同学主页', eyebrow: '校园论坛', nav: '#/forum' },
  { pattern: /^\/messages(?:\/(\d+))?$/, view: renderMessages, title: '私信', eyebrow: '消息', nav: '#/messages' },
  { pattern: /^\/notifications$/, view: renderNotifications, title: '通知', eyebrow: '消息', nav: '#/notifications' },
  { pattern: /^\/me$/, view: renderProfile, title: '个人设置', eyebrow: '我的', nav: '#/me' },
  { pattern: /^\/admin$/, view: renderAdmin, title: '管理后台', eyebrow: '维护者', nav: '#/admin', admin: true }
];

const NAV_GROUPS = [
  {
    label: '学习',
    items: [
      { href: '#/', iconName: 'home', text: '工作台' },
      { href: '#/ask', iconName: 'sparkles', text: '官网问答' },
      { href: '#/academic', iconName: 'cap', text: '学业问答' },
      { href: '#/plans', iconName: 'calendar', text: '定期计划' },
      { href: '#/tasks', iconName: 'checkSquare', text: '待办提醒' }
    ]
  },
  {
    label: '发现',
    items: [
      { href: '#/news', iconName: 'news', text: '今日热点' },
      { href: '#/papers', iconName: 'file', text: '论文推荐' },
      { href: '#/study', iconName: 'book', text: '学习资料' },
      { href: '#/sources', iconName: 'database', text: '官网文件' }
    ]
  },
  {
    label: '社区',
    items: [
      { href: '#/forum', iconName: 'users', text: '校园论坛' },
      { href: '#/messages', iconName: 'message', text: '私信', badge: 'messages' }
    ]
  },
  {
    label: '我的',
    items: [{ href: '#/me', iconName: 'settings', text: '个人设置' }]
  }
];

const MOBILE_NAV = [
  { href: '#/', iconName: 'home', text: '工作台' },
  { href: '#/ask', iconName: 'sparkles', text: '问答' },
  { href: '#/forum', iconName: 'users', text: '论坛' },
  { href: '#/messages', iconName: 'message', text: '私信' },
  { href: '#/me', iconName: 'user', text: '我的' }
];

function currentRoute() {
  let raw = window.location.hash.replace(/^#/, '') || '/';
  const question = raw.indexOf('?');
  let path = question >= 0 ? raw.slice(0, question) : raw;
  const query = new URLSearchParams(question >= 0 ? raw.slice(question + 1) : '');
  if (!path.startsWith('/')) path = `/${path}`;
  for (const route of routes) {
    const match = path.match(route.pattern);
    if (match) return { route, params: match.slice(1), query, path };
  }
  return { route: routes[0], params: [], query, path: '/' };
}

function navHtml(activeHref) {
  const groups = NAV_GROUPS.map((group) => {
    const items = group.items.map((item) => {
      const active = activeHref === item.href || (item.href !== '#/' && activeHref && activeHref.startsWith(item.href));
      const badge = item.badge
        ? `<span class="nav-badge" data-unread-badge="${item.badge}" hidden></span>`
        : '';
      return `<a class="nav-link${active ? ' active' : ''}" href="${item.href}">
        <span class="nav-icon">${icon(item.iconName)}</span><span>${item.text}</span>${badge}</a>`;
    }).join('');
    return `<div class="nav-group"><div class="nav-label">${group.label}</div>${items}</div>`;
  });
  if (store.user && store.user.is_admin) {
    groups.push(`<div class="nav-group"><div class="nav-label">维护</div>
      <a class="nav-link${activeHref === '#/admin' ? ' active' : ''}" href="#/admin">
        <span class="nav-icon">${icon('shield')}</span><span>管理后台</span></a></div>`);
  }
  return groups.join('');
}

function renderShell() {
  const meta = store.meta || {};
  document.getElementById('mainNav').innerHTML = navHtml('');
  const mobile = MOBILE_NAV.map((item) => `<a href="${item.href}">
      ${icon(item.iconName)}<span>${item.text}</span></a>`).join('');
  document.getElementById('mobileNav').innerHTML = mobile;
  document.getElementById('mobileNav').hidden = false;
  const user = store.user;
  const roleTag = user.is_admin ? '<span class="tag tag-amber" style="margin-left:auto">管理员</span>' : '';
  document.getElementById('sidebarUser').innerHTML = `
    ${avatar(user, 'sm')}
    <span class="meta"><strong>${escapeText(user.nickname)}</strong><small>${escapeText(user.major || '华东师范大学')}</small></span>
    ${roleTag}`;
  document.getElementById('userChip').innerHTML = `
    ${avatar(user, 'sm')}
    <span class="user-name">${escapeText(user.nickname)}</span>
    ${icon('chevronDown')}`;
  const portal = document.getElementById('portalButton');
  portal.href = meta.portal_url || 'https://portal2023.ecnu.edu.cn/portal/home';
  document.getElementById('menuBtn').innerHTML = icon('menu');
  document.getElementById('searchBtn').innerHTML = icon('search');
  const bellIcon = document.querySelector('#bellBtn .bell-icon');
  if (bellIcon) bellIcon.innerHTML = icon('bell');
  updateThemeIcon();
  setUnread();
}

function escapeText(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function updateThemeIcon() {
  const btn = document.getElementById('themeBtn');
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  btn.innerHTML = icon(dark ? 'sun' : 'moon');
  btn.title = dark ? '切换到浅色模式' : '切换到深色模式';
}

function setActiveNav(hash) {
  document.querySelectorAll('#mainNav .nav-link').forEach((link) => {
    const href = link.getAttribute('href');
    const active = href === hash || (href !== '#/' && hash && hash.startsWith(href));
    link.classList.toggle('active', active);
  });
  document.querySelectorAll('#mobileNav a').forEach((link) => {
    const href = link.getAttribute('href');
    link.classList.toggle('active', href === hash || (href !== '#/' && hash.startsWith(href)));
  });
}

let currentAbort = null;

async function route() {
  if (!store.user) return;
  const { route: matched, params, query, path } = currentRoute();
  if (matched.admin && !(store.user && store.user.is_admin)) {
    toast('需要管理员权限', 'warn');
    window.location.hash = '#/';
    return;
  }
  if (currentAbort) currentAbort.abort();
  const controller = new AbortController();
  currentAbort = controller;
  const viewEl = document.getElementById('view');
  document.getElementById('pageTitle').textContent = matched.title;
  document.getElementById('pageEyebrow').textContent = matched.eyebrow || 'ECNU 小助手';
  document.title = `${matched.title} · ECNU 小助手`;
  setActiveNav(matched.nav || path);
  document.body.classList.remove('nav-open');
  document.getElementById('sidebarBackdrop').classList.remove('show');
  viewEl.innerHTML = loadingBlock('正在加载…');
  window.scrollTo({ top: 0, behavior: 'auto' });
  try {
    const result = matched.view(viewEl, {
      params,
      query,
      ...(matched.props || {}),
      signal: controller.signal
    });
    if (result && typeof result.then === 'function') await result;
    if (matched.dynamicTitle) document.getElementById('pageTitle').textContent = matched.dynamicTitle;
  } catch (error) {
    if (error && error.name === 'AbortError') return;
    console.error(error);
    viewEl.innerHTML = `<div class="card pad"><h2>页面加载失败</h2>
      <p class="muted">${escapeText(error.message || '请稍后重试')}</p>
      <div class="mt-16"><button class="btn btn-primary" data-reload>刷新页面</button></div></div>`;
  }
}

async function refreshUnread() {
  try {
    const [notifications, messages] = await Promise.all([
      api.get('/api/notifications?limit=1'),
      api.get('/api/messages/unread')
    ]);
    setUnread(messages.unread, notifications.unread);
  } catch (e) { /* 忽略 */ }
}

function handleServerEvent(event) {
  if (!event || !event.type) return;
  if (event.type === 'reminder') {
    const payload = event.payload || {};
    const overdue = payload.overdue_hours > 0 ? `（逾期 ${payload.overdue_hours} 小时）` : '';
    toast(`提醒：${payload.title}${overdue}`, 'warn', 7000);
    setUnread(null, (store.unread.notifications || 0) + 1);
    if ((payload.channels || []).includes('browser')) {
      notifyBrowser(`ECNU 小助手提醒 · ${payload.title}`, payload.notes || '到时间啦，记得完成计划。', '#/tasks');
    }
    window.dispatchEvent(new CustomEvent('app:reminder', { detail: payload }));
  } else if (event.type === 'notification') {
    const payload = event.payload || {};
    if (event.kind === 'message') {
      setUnread((store.unread.messages || 0) + 1, null);
      toast(payload.text || '收到一条私信', 'info');
    } else {
      setUnread(null, (store.unread.notifications || 0) + 1);
      toast(payload.text || '收到一条新通知', 'info');
    }
    window.dispatchEvent(new CustomEvent('app:notification', { detail: event }));
  }
}

let eventSource = null;

function connectEvents() {
  if (!('EventSource' in window)) return;
  if (eventSource) eventSource.close();
  eventSource = new EventSource('/api/events');
  eventSource.onmessage = (message) => {
    try { handleServerEvent(JSON.parse(message.data)); } catch (e) { /* 忽略 */ }
  };
  eventSource.onerror = () => { /* EventSource 会自动重连 */ };
}

function showLogin(auth, message = '') {
  document.getElementById('boot').hidden = true;
  const app = document.getElementById('app');
  app.hidden = false;
  app.className = 'login-page';
  const { html, bind } = renderLogin(auth || store.auth || {}, message);
  app.innerHTML = html;
  bind(app);
}

function showBootError(error) {
  document.getElementById('boot').hidden = true;
  const app = document.getElementById('app');
  app.hidden = false;
  app.className = '';
  app.innerHTML = `<div class="boot-screen" style="position:static;min-height:100vh">
    <div class="boot-card" style="flex-direction:column;text-align:center;max-width:460px">
      <div class="boot-logo">!</div>
      <strong>无法连接本地服务</strong>
      <p style="color:#b9cbe0">${escapeText(error.message || '请确认 Python 服务仍在运行，然后刷新页面。')}</p>
      <button class="btn btn-accent" data-reload>重新加载</button>
    </div></div>`;
}

async function boot() {
  initTheme();
  loadLLM();
  const ssoError = new URLSearchParams(window.location.search).get('auth_error');
  if (ssoError) {
    window.history.replaceState({}, '', window.location.pathname + window.location.hash);
  }
  let me;
  try {
    me = await api.get('/api/auth/me');
  } catch (error) {
    showBootError(error);
    return;
  }
  store.auth = me.auth;
  if (!me.authenticated) {
    showLogin(me.auth, ssoError || '');
    return;
  }
  store.user = me.user;
  store.csrf = me.csrf;
  if (me.user.settings && me.user.settings.theme) {
    // 以账号设置为准（跨浏览器同步）；localStorage 作为未登录时的偏好
    applyTheme(me.user.settings.theme);
  }
  try {
    store.meta = await api.get('/api/meta');
  } catch (error) {
    store.meta = null;
  }
  document.getElementById('boot').hidden = true;
  document.getElementById('app').hidden = false;
  renderShell();
  connectEvents();
  await refreshUnread();
  if (ssoError) toast(ssoError, 'error', 6000);
  if (!window.location.hash) window.location.hash = '#/';
  await route();
}

function bindShell() {
  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-reload]')) window.location.reload();
  });
  document.getElementById('menuBtn').addEventListener('click', () => {
    document.body.classList.toggle('nav-open');
    document.getElementById('sidebarBackdrop').classList.toggle('show');
  });
  document.getElementById('sidebarBackdrop').addEventListener('click', () => {
    document.body.classList.remove('nav-open');
    document.getElementById('sidebarBackdrop').classList.remove('show');
  });
  document.getElementById('themeBtn').addEventListener('click', () => {
    toggleTheme();
    updateThemeIcon();
    if (store.user) {
      api.patch('/api/profile', { settings: { theme: applyTheme() } }).catch(() => {});
    }
  });
  document.getElementById('userChip').addEventListener('click', () => {
    window.location.hash = '#/me';
  });
  document.getElementById('bellBtn').addEventListener('click', () => {
    refreshUnread();
  });
  window.addEventListener('hashchange', () => {
    if (store.user) route();
  });
  window.addEventListener('auth:expired', async () => {
    if (!store.user) return;
    logoutLocal();
    toast('登录已过期，请重新登录', 'warn');
    window.setTimeout(() => window.location.reload(), 800);
  });
  window.addEventListener('app:login-required', () => {
    if (!store.user) return;
    logoutLocal();
    window.location.reload();
  });
}

bindShell();
boot();
