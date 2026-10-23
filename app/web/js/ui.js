import { icon } from './icons.js';
import { esc } from './markdown.js';
import { store } from './store.js';

export { icon, esc };

const SIZE = { xs: 'avatar-xs', sm: 'avatar-sm', md: 'avatar-md', lg: 'avatar-lg', xl: 'avatar-xl' };

const FALLBACK_AVATARS = {
  ocean: { bg: 'linear-gradient(135deg,#0b3a66,#16a3a0)', emoji: '🌊' },
  forest: { bg: 'linear-gradient(135deg,#14532d,#84cc16)', emoji: '🌿' },
  sunset: { bg: 'linear-gradient(135deg,#f97316,#ec4899)', emoji: '🌅' },
  grape: { bg: 'linear-gradient(135deg,#5b21b6,#a78bfa)', emoji: '🪻' },
  ink: { bg: 'linear-gradient(135deg,#1f2937,#64748b)', emoji: '🖋️' },
  mint: { bg: 'linear-gradient(135deg,#0f766e,#99f6e4)', emoji: '🍃' },
  candy: { bg: 'linear-gradient(135deg,#db2777,#fbbf24)', emoji: '🍬' },
  night: { bg: 'linear-gradient(135deg,#0f172a,#3b82f6)', emoji: '🌌' },
  ghost: { bg: 'linear-gradient(135deg,#475569,#94a3b8)', emoji: '👻' }
};

export function avatarPreset(key) {
  const list = (store.meta && store.meta.avatars) || [];
  const found = list.find((item) => item.key === key);
  return found || FALLBACK_AVATARS[key] || FALLBACK_AVATARS.ocean;
}

export function avatar(user, size = 'md', extra = '') {
  const cls = `avatar ${SIZE[size] || SIZE.md} ${extra}`.trim();
  const name = user && user.nickname ? user.nickname : '';
  if (user && user.avatar_url) {
    return `<span class="${cls}"><img src="${esc(user.avatar_url)}" alt="${esc(name)}的头像" loading="lazy"></span>`;
  }
  const key = String((user && user.avatar) || 'preset:ocean').replace('preset:', '');
  const preset = avatarPreset(key);
  return `<span class="${cls}" style="background:${preset.bg}" title="${esc(name)}">${preset.emoji || esc(name.slice(0, 1) || 'E')}</span>`;
}

export function toast(message, type = 'info', timeout = 4200) {
  const root = document.getElementById('toasts');
  if (!root) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const name = type === 'success' ? 'check' : type === 'error' || type === 'warn' ? 'alert' : 'info';
  el.innerHTML = `${icon(name)}<div>${esc(message)}</div>`;
  root.appendChild(el);
  window.setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    window.setTimeout(() => el.remove(), 220);
  }, timeout);
}

export function openModal(options = {}) {
  const {
    title = '',
    body = '',
    footer = '',
    size = '',
    onMount = null,
    onClose = null,
    dismissible = true
  } = options;
  const root = document.getElementById('modalRoot');
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal ${size}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head">
        <h3>${esc(title)}</h3>
        <button class="icon-btn" type="button" data-close aria-label="关闭">${icon('x')}</button>
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
    </div>`;
  root.appendChild(overlay);
  document.body.style.overflow = 'hidden';
  const onKey = (event) => { if (event.key === 'Escape' && dismissible) close(); };
  document.addEventListener('keydown', onKey);
  const close = () => {
    overlay.remove();
    if (!root.children.length) document.body.style.overflow = '';
    document.removeEventListener('keydown', onKey);
    if (onClose) onClose();
  };
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay && dismissible) close();
  });
  overlay.querySelectorAll('[data-close]').forEach((btn) => btn.addEventListener('click', close));
  if (onMount) onMount(overlay, close);
  window.setTimeout(() => {
    const target = overlay.querySelector('input:not([type=hidden]), textarea, select');
    if (target) target.focus();
  }, 40);
  return { overlay, close, bodyEl: overlay.querySelector('.modal-body'), footerEl: overlay.querySelector('.modal-foot') };
}

export function confirmDialog(title, message, options = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (value) => { if (!settled) { settled = true; resolve(value); modal.close(); } };
    const modal = openModal({
      title,
      body: `<p class="soft" style="font-size:13.5px;line-height:1.8">${esc(message)}</p>`,
      footer: `<button class="btn btn-ghost" data-cancel>取消</button>
               <button class="btn ${options.danger ? 'btn-danger' : 'btn-primary'}" data-ok>${esc(options.confirmText || '确定')}</button>`,
      size: 'modal-sm',
      onMount: (root) => {
        root.querySelector('[data-cancel]').addEventListener('click', () => done(false));
        root.querySelector('[data-ok]').addEventListener('click', () => done(true));
      },
      onClose: () => done(false)
    });
  });
}

export function pageHead(title, description = '', actions = '') {
  return `<div class="page-head">
    <div><h2>${esc(title)}</h2>${description ? `<p>${descHtml(description)}</p>` : ''}</div>
    ${actions ? `<div class="page-head-actions">${actions}</div>` : ''}
  </div>`;
}

function descHtml(text) {
  return String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
}

export function emptyState(options = {}) {
  const { iconName = 'sparkles', title = '这里还是空的', desc = '', action = '' } = options;
  return `<div class="empty">
    <div class="empty-icon">${icon(iconName)}</div>
    <h3>${esc(title)}</h3>
    ${desc ? `<p>${esc(desc)}</p>` : ''}
    ${action || ''}
  </div>`;
}

export function loadingBlock(text = '正在加载…') {
  return `<div class="loading-overlay"><div class="spinner"></div><span>${esc(text)}</span></div>`;
}

export function skeletonCards(count = 3) {
  return `<div class="grid grid-auto">${Array.from({ length: count }).map(() => `
    <div class="card pad-sm">
      <div class="skeleton loading-line" style="width:60%"></div>
      <div class="skeleton loading-line" style="width:92%"></div>
      <div class="skeleton loading-line" style="width:80%"></div>
    </div>`).join('')}</div>`;
}

export function statusBadge(status) {
  const map = {
    visible: ['tag-green', '已发布'],
    pending: ['tag-amber', '审核中'],
    hidden: ['tag-red', '已隐藏'],
    removed: ['badge-soft', '已删除']
  };
  const [cls, label] = map[status] || ['badge-soft', status || '未知'];
  return `<span class="tag ${cls}">${label}</span>`;
}

export function fmtDateTime(iso, withYear = false) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso).slice(0, 16).replace('T', ' ');
  const options = withYear
    ? { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
    : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' };
  return new Intl.DateTimeFormat('zh-CN', options).format(date);
}

export function fmtDay(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(date);
}

export function timeAgo(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 30) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
  return fmtDay(iso);
}

export function toLocalInput(iso) {
  const date = iso ? new Date(iso) : new Date();
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function fromLocalInput(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

export function tagList(tags = [], extra = '') {
  return tags.map((tag) => `<span class="tag ${extra}">${esc(tag)}</span>`).join('');
}

export function debounce(fn, wait = 300) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

export function safeHttpUrl(url) {
  return /^https?:\/\//i.test(url || '') ? esc(url) : '';
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('已复制', 'success', 1800);
    return true;
  } catch (e) {
    toast('复制失败，请手动选择文本', 'error');
    return false;
  }
}

export async function requestNotifyPermission() {
  if (!('Notification' in window)) {
    toast('当前浏览器不支持系统通知', 'warn');
    return false;
  }
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') {
    toast('浏览器通知已被拒绝，请在浏览器设置中允许', 'warn');
    return false;
  }
  const result = await Notification.requestPermission();
  return result === 'granted';
}

export function notifyBrowser(title, body, link = '') {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    const notification = new Notification(title, {
      body,
      icon: '/favicon.ico',
      tag: 'ecnu-assistant',
      silent: false
    });
    notification.onclick = () => {
      window.focus();
      if (link) window.location.hash = link;
      notification.close();
    };
  } catch (e) { /* 忽略 */ }
}

export function setUnread(messages = null, notifications = null) {
  if (messages != null) store.unread.messages = messages;
  if (notifications != null) store.unread.notifications = notifications;
  const total = (store.unread.messages || 0) + (store.unread.notifications || 0);
  const dot = document.getElementById('bellDot');
  if (dot) dot.hidden = total <= 0;
  document.querySelectorAll('[data-unread-badge]').forEach((el) => {
    const kind = el.getAttribute('data-unread-badge');
    const count = kind === 'messages' ? store.unread.messages : store.unread.notifications;
    el.textContent = count > 99 ? '99+' : String(count || '');
    el.hidden = !count;
  });
}

export function initials(name) {
  const text = String(name || 'E').trim();
  return text.slice(0, 1).toUpperCase();
}

export function externalLink(url, label = '打开原文') {
  const safe = safeHttpUrl(url);
  if (!safe) return '';
  return `<a class="card-link" href="${safe}" target="_blank" rel="noopener noreferrer">${esc(label)}${icon('external')}</a>`;
}
