/* 前端状态：只保存用户偏好；模型 API Key 默认只放 sessionStorage。 */
const LS = window.localStorage;
const SS = window.sessionStorage;

const state = {
  user: null,
  csrf: null,
  meta: null,
  auth: null,
  unread: { notifications: 0, messages: 0 },
  llm: { key: '', model: '', base_url: '', provider: '' },
  sources: null,
  theme: LS.getItem('ecnu-theme') || 'system'
};

export const store = state;

export function loadLLM() {
  try {
    const cfg = JSON.parse(LS.getItem('ecnu-llm') || '{}');
    state.llm.model = cfg.model || '';
    state.llm.base_url = cfg.base_url || '';
    state.llm.provider = cfg.provider || '';
  } catch (e) { /* ignore */ }
  state.llm.key = SS.getItem('ecnu-llm-key') || '';
  return state.llm;
}

export function saveLLM(cfg, rememberKey = false) {
  state.llm = { ...state.llm, ...cfg };
  if (rememberKey && cfg.key) {
    try { SS.setItem('ecnu-llm-key', cfg.key); } catch (e) { /* ignore */ }
  } else if (cfg.key) {
    try { SS.setItem('ecnu-llm-key', cfg.key); } catch (e) { /* ignore */ }
  }
  try {
    LS.setItem('ecnu-llm', JSON.stringify({ model: state.llm.model, base_url: state.llm.base_url, provider: state.llm.provider }));
  } catch (e) { /* ignore */ }
}

export function clearLLMKey() {
  state.llm.key = '';
  try { SS.removeItem('ecnu-llm-key'); } catch (e) { /* ignore */ }
}

export function hasLLM() {
  return !!(state.llm.key && state.llm.model);
}

export function applyTheme(mode = state.theme) {
  state.theme = mode || 'system';
  LS.setItem('ecnu-theme', state.theme);
  let resolved = state.theme;
  if (state.theme === 'system') {
    resolved = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  document.documentElement.setAttribute('data-theme', resolved);
  document.body.setAttribute('data-theme', resolved);
  document.documentElement.style.colorScheme = resolved;
  return resolved;
}

export function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  applyTheme(current === 'dark' ? 'light' : 'dark');
  return state.theme;
}

export function initTheme() {
  applyTheme(state.theme);
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (state.theme === 'system') applyTheme('system');
    });
  }
}

export function logoutLocal() {
  state.user = null;
  state.csrf = null;
  state.unread = { notifications: 0, messages: 0 };
}
