import { store } from './store.js';

export class ApiError extends Error {
  constructor(message, status = 0, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

function errorMessage(data, status) {
  if (data && typeof data.detail === 'string') return data.detail;
  if (data && Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || '参数无效').join('；');
  }
  if (status === 401) return '请先登录';
  if (status === 403) return '没有权限或安全校验失败，请刷新页面';
  if (status === 429) return '操作太频繁，请稍后再试';
  return `请求失败（${status}）`;
}

export async function request(path, options = {}) {
  const { method = 'GET', body, headers = {}, signal, raw = false } = options;
  const finalHeaders = { Accept: 'application/json', ...llmHeaders(), ...headers };
  let payload;
  if (body !== undefined) {
    finalHeaders['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  if (method !== 'GET' && method !== 'HEAD' && store.csrf) {
    finalHeaders['X-CSRF-Token'] = store.csrf;
  }
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: finalHeaders,
      body: payload,
      signal,
      credentials: 'same-origin'
    });
  } catch (err) {
    if (err && err.name === 'AbortError') throw err;
    throw new ApiError('网络连接失败，请确认服务仍在运行', 0);
  }
  const type = response.headers.get('content-type') || '';
  let data = null;
  if (type.includes('application/json')) {
    try { data = await response.json(); } catch (e) { data = null; }
  } else if (raw) {
    data = await response.blob();
  } else {
    data = await response.text();
  }
  if (response.status === 401 && !path.startsWith('/api/auth/me')) {
    window.dispatchEvent(new CustomEvent('auth:expired'));
  }
  if (!response.ok) {
    throw new ApiError(errorMessage(data, response.status), response.status, data);
  }
  return data;
}

export const api = {
  get: (path, options = {}) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options = {}) => request(path, { ...options, method: 'POST', body }),
  patch: (path, body, options = {}) => request(path, { ...options, method: 'PATCH', body }),
  del: (path, options = {}) => request(path, { ...options, method: 'DELETE' }),
  request
};

export function llmHeaders() {
  const headers = {};
  if (store.llm.key) headers['X-LLM-Key'] = store.llm.key;
  if (store.llm.model) headers['X-LLM-Model'] = store.llm.model;
  if (store.llm.base_url) headers['X-LLM-Base-URL'] = store.llm.base_url;
  return headers;
}

/**
 * POST 一个 SSE 接口，逐个解析 data: 事件。
 * 返回完整事件列表（通常用于调试）。
 */
export async function streamRequest(path, body, onEvent, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...llmHeaders(),
    ...(options.headers || {})
  };
  if (store.csrf) headers['X-CSRF-Token'] = store.csrf;
  const response = await fetch(path, {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    body: JSON.stringify(body),
    signal: options.signal
  });
  if (!response.ok) {
    let data = null;
    try { data = await response.json(); } catch (e) { data = null; }
    throw new ApiError(errorMessage(data, response.status), response.status, data);
  }
  if (!response.body) throw new ApiError('当前浏览器不支持流式响应', 0);
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  const events = [];
  const dispatch = (chunk) => {
    const line = chunk.trim();
    if (!line || line.startsWith(':')) return;
    if (!line.startsWith('data:')) return;
    const raw = line.slice(5).trim();
    if (!raw) return;
    try {
      const event = JSON.parse(raw);
      events.push(event);
      onEvent && onEvent(event);
    } catch (e) { /* 忽略半包 */ }
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      dispatch(chunk);
    }
  }
  if (buffer.trim()) dispatch(buffer);
  return events;
}

export function authExpiredHandler() {
  return (event) => {
    store.csrf = null;
    store.user = null;
    window.dispatchEvent(new CustomEvent('app:login-required'));
  };
}
