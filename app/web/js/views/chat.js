import { api, streamRequest } from '../api.js';
import { store, saveLLM, clearLLMKey } from '../store.js';
import {
  icon, esc, avatar, toast, openModal, safeHttpUrl, copyText, timeAgo
} from '../ui.js';
import { renderMarkdown, typeset } from '../markdown.js';

const PROMPTS = {
  official: [
    '教务处缓考申请的流程是什么？',
    '图书馆的借阅规则和开放时间？',
    '奖学金评定一般需要哪些材料？',
    '研究生学位论文的开题要求？'
  ],
  academic: [
    '用例子解释贝叶斯定理，并说明常见误区。',
    '如何高效阅读一篇学术论文？给我一套流程。',
    '帮我制定两周的线性代数复习计划。',
    '解释一下梯度下降和牛顿法的区别。'
  ]
};

/* 会话状态放在模块级：切到别的页面时流式输出继续跑，回到对话页还能接着看。 */
const SESSIONS = {
  official: {
    mode: 'official', messages: [], threads: [], threadId: null, sending: false, controller: null,
    view: null, library: null, selectedSites: new Set(), siteQuery: ''
  },
  academic: {
    mode: 'academic', messages: [], threads: [], threadId: null, sending: false, controller: null,
    view: null, library: null, selectedSites: new Set(), siteQuery: ''
  }
};

function sessionFor(mode) {
  return SESSIONS[mode === 'academic' ? 'academic' : 'official'];
}

function notify(mode) {
  const session = sessionFor(mode);
  const view = session.view;
  if (!view) return;
  if (!view.el || !view.el.isConnected) { session.view = null; return; }
  try {
    view.refresh();
  } catch (error) {
    /* 视图已经被路由替换，忽略 */
  }
}

function sessionMessages(session) {
  return session.messages
    .filter((message) => message.content && String(message.content).trim())
    .map((message) => ({
      role: message.role,
      content: message.content,
      sources: message.sources || [],
      insufficient: !!message.insufficient,
      error: message.error || ''
    }));
}

async function persistSession(session) {
  const messages = sessionMessages(session);
  if (!messages.length) return;
  try {
    if (!session.threadId) {
      const created = await api.post('/api/chat/threads', { mode: session.mode });
      session.threadId = Number(created.id);
    }
    await api.put(`/api/chat/threads/${session.threadId}`, { messages });
    if (session.view && session.view.loadThreads) session.view.loadThreads();
  } catch (error) {
    /* 历史保存失败不影响当前对话 */
  }
}

async function runChatStream(session, question, siteIds, history) {
  const assistantIndex = session.messages.length - 1;
  const controller = new AbortController();
  session.sending = true;
  session.controller = controller;
  const path = session.mode === 'official' ? '/api/chat/official/stream' : '/api/chat/academic/stream';
  try {
    await streamRequest(path, { question, site_ids: siteIds, history }, (event) => {
      const assistant = session.messages[assistantIndex];
      if (!assistant) return;
      if (event.type === 'sources') {
        assistant.sources = event.sources || [];
      } else if (event.type === 'delta') {
        assistant.content += event.text || '';
        notify(session.mode);
      } else if (event.type === 'done') {
        assistant.content = event.answer || assistant.content;
        assistant.sources = event.sources || assistant.sources || [];
        assistant.insufficient = !!event.insufficient;
        assistant.streaming = false;
        notify(session.mode);
        persistSession(session);
      } else if (event.type === 'error') {
        assistant.error = event.detail || '回答失败，请稍后重试';
        assistant.streaming = false;
        notify(session.mode);
        toast(assistant.error, 'error');
        persistSession(session);
      }
    }, { signal: controller.signal });
  } catch (error) {
    const assistant = session.messages[assistantIndex];
    if (assistant) {
      assistant.streaming = false;
      if (error && error.name === 'AbortError') {
        assistant.content = assistant.content ? `${assistant.content}\n\n（已停止生成）` : '（已停止生成）';
      } else {
        assistant.error = error.message || '请求失败，请稍后重试';
        toast(error.message || '请求失败', 'error');
      }
      notify(session.mode);
      persistSession(session);
    }
  } finally {
    if (session.controller === controller) session.controller = null;
    session.sending = false;
    notify(session.mode);
  }
}

function stopSession(session) {
  if (session.controller) session.controller.abort();
}

export async function renderChat(el, ctx) {
  const mode = ctx.mode === 'academic' ? 'academic' : 'official';
  const state = sessionFor(mode);

  el.innerHTML = `<div class="chat-page">
    <section class="chat-main">
      <div class="chat-head">
        <div class="tabs" role="tablist">
          <button class="tab ${mode === 'official' ? 'active' : ''}" data-mode="official" role="tab">官网文件</button>
          <button class="tab ${mode === 'academic' ? 'active' : ''}" data-mode="academic" role="tab">学业问答</button>
        </div>
        <span class="chat-status" id="chatStatus"><span class="status-dot"></span>${mode === 'official' ? '正在加载文件库…' : '通用学业助手'}</span>
        <button class="btn btn-xs btn-ghost" id="newChatBtn" type="button">${icon('plus')}新对话</button>
      </div>
      <div class="chat-log" id="chatLog" aria-live="polite"></div>
      <div class="composer-wrap">
        <div class="composer">
          <textarea id="chatInput" rows="1" maxlength="2000" placeholder="${mode === 'official' ? '问一个关于学校官网文件的问题…' : '问一个学业问题，例如概念、方法或复习计划…'}"></textarea>
          <button class="send" id="sendBtn" type="button" aria-label="发送">${icon('send')}</button>
        </div>
        <div class="composer-meta">
          <span>Enter 发送 · Shift + Enter 换行</span>
          <span class="right" id="composerHint">${mode === 'official' ? '回答只依据已采集的官网文件，并附原文链接' : 'AI 可能出错，请自行核对'}</span>
        </div>
      </div>
    </section>
    <aside class="chat-side">
      <div class="card pad-sm" id="threadCard"></div>
      <div class="card pad-sm" id="modelCard"></div>
      ${mode === 'official' ? `<div class="card pad-sm" id="libraryCard"></div><div class="card pad-sm" id="siteCard"></div>` : ''}
      <div class="card pad-sm">
        <div class="section-title">${icon('shield')} 数据与隐私</div>
        <p class="tiny muted" style="line-height:1.7">API Key 只保存在当前浏览器会话（sessionStorage），随请求发送给本机服务后再转给模型提供方，不写入数据库或日志。</p>
      </div>
    </aside>
  </div>`;

  const logEl = el.querySelector('#chatLog');
  const input = el.querySelector('#chatInput');
  const sendBtn = el.querySelector('#sendBtn');
  let renderedCount = -1;
  // 注册当前视图：流式输出进行中时切换页面，回来仍然能实时更新
  state.view = { el, refresh: () => refreshFromSession(), loadThreads: () => loadThreads() };

  el.querySelectorAll('[data-mode]').forEach((tab) => {
    tab.addEventListener('click', () => {
      const next = tab.getAttribute('data-mode');
      if (next === state.mode) return;
      window.location.hash = next === 'academic' ? '#/academic' : '#/ask';
    });
  });
  el.querySelector('#newChatBtn').addEventListener('click', () => {
    if (state.sending) return;
    state.messages = [];
    state.threadId = null;
    renderLog();
    renderThreadCard();
    input.focus();
  });

  function keyStatus() {
    const ok = !!(store.llm.key && store.llm.model);
    return `<div class="flex-between">
      <div class="key-state ${ok ? 'ok' : ''}"><span class="dot"></span><span>${ok ? esc(store.llm.model) : '尚未配置模型'}</span></div>
      <button class="btn btn-xs btn-ghost" id="openModelBtn" type="button">${icon('settings')}设置</button>
    </div>
    ${ok ? '' : `<p class="tiny muted" style="margin-top:8px">接入你自己的 OpenAI 兼容 API Key 后即可问答。</p>`}`;
  }

  function renderModelCard() {
    const card = el.querySelector('#modelCard');
    if (!card) return;
    card.innerHTML = `<div class="section-title">${icon('sparkles')} 模型</div>${keyStatus()}`;
    card.querySelector('#openModelBtn').addEventListener('click', () => openModelSettings());
  }

  /* ---------------------------------------------------------- 历史对话 */
  function renderThreadCard() {
    const card = el.querySelector('#threadCard');
    if (!card) return;
    const items = state.threads || [];
    card.innerHTML = `<div class="section-title">${icon('message')} 历史对话
        <span class="spacer"></span><span class="tiny muted">${items.length ? `${items.length} 条` : ''}</span></div>
      ${items.length ? `<div class="thread-list">${items.map((thread) => `
        <div class="thread-item ${thread.id === state.threadId ? 'active' : ''}">
          <button class="link-btn grow thread-open" type="button" data-open="${thread.id}" ${thread.id === state.threadId ? 'aria-current="true"' : ''}>${esc(thread.title || '新对话')}</button>
          <span class="tiny muted">${esc(timeAgo(thread.updated_at))}</span>
          <button class="icon-btn thread-del" type="button" data-del="${thread.id}" title="删除这条对话">${icon('trash')}</button>
        </div>`).join('')}</div>`
        : '<p class="tiny muted" style="line-height:1.7">还没有历史对话。提问后会自动保存，刷新或换页都不会丢。</p>'}`;
    card.querySelectorAll('[data-open]').forEach((button) => {
      button.addEventListener('click', () => openThread(Number(button.getAttribute('data-open'))));
    });
    card.querySelectorAll('[data-del]').forEach((button) => {
      button.addEventListener('click', async (event) => {
        event.stopPropagation();
        await removeThread(Number(button.getAttribute('data-del')));
      });
    });
  }

  async function loadThreads() {
    try {
      const result = await api.get(`/api/chat/threads?mode=${mode}`);
      state.threads = result.threads || [];
    } catch (error) {
      state.threads = [];
    }
    renderThreadCard();
    return state.threads;
  }

  async function openThread(threadId) {
    if (state.sending || threadId === state.threadId) return;
    try {
      const data = await api.get(`/api/chat/threads/${threadId}`);
      state.threadId = data.id;
      state.messages = (data.messages || []).map((message) => ({
        role: message.role,
        content: message.content || '',
        sources: message.sources || [],
        insufficient: !!message.insufficient,
        error: message.error || ''
      }));
      renderLog();
      renderThreadCard();
    } catch (error) {
      toast(error.message || '读取对话失败', 'error');
    }
  }

  async function removeThread(threadId) {
    try {
      await api.del(`/api/chat/threads/${threadId}`);
      if (state.threadId === threadId) {
        state.threadId = null;
        state.messages = [];
        renderLog();
      }
      await loadThreads();
      toast('对话已删除', 'success', 1600);
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  async function persistThread() {
    // 统一走模块级的 persistSession，保证切换页面后仍能保存
    await persistSession(state);
  }

  function renderLibraryCard() {
    const card = el.querySelector('#libraryCard');
    if (!card) return;
    const lib = state.library;
    if (!lib) {
      card.innerHTML = `<div class="section-title">${icon('database')} 文件库</div><div class="skeleton loading-line"></div><div class="skeleton loading-line" style="width:70%"></div>`;
      return;
    }
    const docs = lib.index ? lib.index.documents : 0;
    const chunks = lib.index ? lib.index.chunks : 0;
    const building = !!(lib.index && lib.index.building);
    card.innerHTML = `<div class="section-title">${icon('database')} 文件库</div>
      <p class="small soft" style="line-height:1.7">${docs
        ? `已索引 <strong>${docs}</strong> 份文件、${chunks} 个片段。${building ? '（索引正在后台更新）' : ''}`
        : (building ? '正在后台建立检索索引，稍等片刻…' : '还没有采集官网文件，暂时只能给出"依据不足"的提示。')}</p>
      <a class="btn btn-xs btn-soft btn-block mt-10" href="#/sources">${docs ? '管理官网文件' : '去采集官网文件'}</a>`;
  }

  function siteListHtml() {
    const lib = state.library;
    if (!lib) return '<div class="skeleton loading-line"></div>';
    const q = state.siteQuery.trim();
    const sites = lib.sites
      .filter((site) => !q || site.name.includes(q) || site.category.includes(q))
      .sort((a, b) => b.doc_count - a.doc_count || a.name.localeCompare(b.name, 'zh'));
    if (!sites.length) return '<p class="tiny muted">没有匹配的站点</p>';
    return sites.map((site) => `<label>
      <input type="checkbox" value="${site.id}" ${state.selectedSites.has(String(site.id)) ? 'checked' : ''}>
      <span class="grow"><span>${esc(site.name)}</span><span class="sub"> · ${site.doc_count} 份</span></span>
    </label>`).join('');
  }

  function renderSiteCard() {
    const card = el.querySelector('#siteCard');
    if (!card) return;
    card.innerHTML = `<div class="section-title">${icon('filter')} 检索范围
        <span class="spacer"></span><span class="tiny muted" id="siteCount"></span></div>
      <input class="input input-sm" id="siteSearch" placeholder="搜索学院/部门" value="${esc(state.siteQuery)}">
      <div class="site-filter mt-10" id="siteFilter">${siteListHtml()}</div>
      <div class="flex mt-10">
        <button class="link-btn" type="button" id="selectAllSites">全选</button>
        <button class="link-btn" type="button" id="clearSites">清空</button>
        <span class="tiny muted right">不选 = 全部站点</span>
      </div>`;
    const updateCount = () => {
      const count = el.querySelector('#siteCount');
      if (count) count.textContent = state.selectedSites.size ? `已选 ${state.selectedSites.size}` : '全部';
    };
    updateCount();
    card.querySelector('#siteSearch').addEventListener('input', (event) => {
      state.siteQuery = event.target.value;
      const box = el.querySelector('#siteFilter');
      box.innerHTML = siteListHtml();
      bindSiteChecks();
    });
    const bindSiteChecks = () => {
      card.querySelectorAll('#siteFilter input[type=checkbox]').forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) state.selectedSites.add(checkbox.value);
          else state.selectedSites.delete(checkbox.value);
          updateCount();
        });
      });
    };
    bindSiteChecks();
    card.querySelector('#selectAllSites').addEventListener('click', () => {
      (state.library?.sites || []).forEach((site) => state.selectedSites.add(String(site.id)));
      renderSiteCard();
    });
    card.querySelector('#clearSites').addEventListener('click', () => {
      state.selectedSites.clear();
      renderSiteCard();
    });
  }

  function chatStatus() {
    const status = el.querySelector('#chatStatus');
    if (!status) return;
    if (state.mode === 'academic') {
      status.innerHTML = `<span class="status-dot"></span>通用学业助手 · 不引用学校文件`;
      return;
    }
    if (!state.library) {
      status.innerHTML = '<span class="status-dot"></span>正在加载文件库…';
      return;
    }
    const docs = state.library.index?.documents || 0;
    status.innerHTML = `<span class="status-dot"></span>已索引 ${docs} 份官网文件`;
  }

  function sourcesHtml(sources, open = false) {
    if (!sources || !sources.length) return '';
    return `<details class="msg-sources" ${open ? 'open' : ''}>
      <summary>${icon('file')} 参考文件 · ${sources.length} 份</summary>
      ${sources.map((source) => {
        const url = safeHttpUrl(source.url);
        const used = source.used ? '<span class="tag tag-teal" style="margin-left:4px">已引用</span>' : '';
        return `<a class="source-chip" ${url ? `href="${url}" target="_blank" rel="noopener noreferrer"` : ''}>
          <span class="n">${source.index}</span>
          <span class="grow"><span class="t">${esc(source.title)}${used}</span>
          <span class="m">${esc(source.site_name || '')}${source.published_label ? ` · ${esc(source.published_label)}` : ''}</span></span>
          ${icon('external')}
        </a>`;
      }).join('')}
    </details>`;
  }

  function messageHtml(message, index) {
    if (message.role === 'user') {
      return `<div class="msg user" id="msg-${index}">
        <div class="msg-avatar">${avatar(store.user, 'xs')}</div>
        <div class="msg-body">
          <div class="msg-meta">你 · 刚刚</div>
          <div class="msg-bubble tex2jax_ignore">${esc(message.content).replace(/\n/g, '<br>')}</div>
        </div>
      </div>`;
    }
    const streaming = message.streaming;
    const body = streaming && !message.content
      ? '<span class="typing"><i></i><i></i><i></i></span>'
      : `${renderMarkdown(message.content)}${streaming ? '<span class="typing" style="margin-left:6px"><i></i></span>' : ''}`;
    const sources = sourcesHtml(message.sources, false);
    const warning = message.insufficient
      ? `<div class="notice notice-warn mt-10">${icon('alert')}<div>已索引的文件不足以回答这个问题。可以到「官网文件」补充采集，或换一个更具体的关键词。</div></div>`
      : '';
    return `<div class="msg assistant ${message.error ? 'error' : ''}" id="msg-${index}">
      <div class="msg-avatar"><span class="avatar avatar-xs" style="background:linear-gradient(135deg,#0b3a66,#16a3a0)">E</span></div>
      <div class="msg-body">
        <div class="msg-meta">ECNU 小助手 · AI 生成${streaming ? ' · 正在回答' : ''}</div>
        <div class="msg-bubble">${message.error ? `<p>${esc(message.error)}</p>` : body}${warning}${sources}</div>
        ${!streaming && message.content ? `<div class="flex mt-6"><button class="link-btn" data-copy="${index}">${icon('copy')} 复制</button>${message.sources?.length ? '<span class="tiny muted">请打开原文核对</span>' : ''}</div>` : ''}
      </div>
    </div>`;
  }

  function emptyHtml() {
    const prompts = PROMPTS[state.mode];
    return `<div class="chat-empty">
      <div class="orb">${icon(state.mode === 'official' ? 'sparkles' : 'cap')}</div>
      <h3>${state.mode === 'official' ? '从学校文件里找答案' : '把不懂的地方讲清楚'}</h3>
      <p>${state.mode === 'official'
        ? '我会先检索已采集的官网文件，再回答并给出原文链接；证据不足时会直接说明。'
        : '适合概念解释、学习方法、复习规划。这里不会假装查过学校文件。'}</p>
      <div class="prompt-grid">
        ${prompts.map((prompt) => `<button class="prompt-chip" data-prompt="${esc(prompt)}">${esc(prompt)}</button>`).join('')}
      </div>
    </div>`;
  }

  function renderLog() {
    renderedCount = state.messages.length;
    if (!state.messages.length) {
      logEl.innerHTML = emptyHtml();
      bindPrompts();
      return;
    }
    logEl.innerHTML = state.messages.map(messageHtml).join('');
    logEl.querySelectorAll('[data-copy]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const index = Number(btn.getAttribute('data-copy'));
        copyText(state.messages[index]?.content || '');
      });
    });
    typeset(logEl);
    logEl.scrollTop = logEl.scrollHeight;
  }

  function bindPrompts() {
    logEl.querySelectorAll('[data-prompt]').forEach((button) => {
      button.addEventListener('click', () => {
        input.value = button.getAttribute('data-prompt');
        send();
      });
    });
  }

  function updateStreamingBubble(index) {
    const message = state.messages[index];
    const node = logEl.querySelector(`#msg-${index} .msg-bubble`);
    if (!node || !message) return;
    node.innerHTML = `${renderMarkdown(message.content)}<span class="typing" style="margin-left:6px"><i></i></span>`;
    logEl.scrollTop = logEl.scrollHeight;
  }

  /* 会话状态变了就刷新视图：条数没变时只更新最后一条气泡，避免整页重绘。 */
  function refreshFromSession() {
    const count = state.messages.length;
    const last = count ? state.messages[count - 1] : null;
    if (count === renderedCount && last && last.streaming) {
      updateStreamingBubble(count - 1);
    } else {
      renderLog();
    }
    setSending(state.sending);
    renderThreadCard();
  }

  function setSending(value) {
    state.sending = value;
    sendBtn.disabled = false;
    sendBtn.innerHTML = value ? icon('x') : icon('send');
    sendBtn.setAttribute('aria-label', value ? '停止生成' : '发送');
    sendBtn.classList.toggle('stopping', value);
    sendBtn.style.background = value ? 'var(--red-600)' : '';
    input.placeholder = value ? '正在回答… 可点击右侧停止' : (state.mode === 'official' ? '问一个关于学校官网文件的问题…' : '问一个学业问题，例如概念、方法或复习计划…');
    const hint = el.querySelector('#composerHint');
    if (hint) hint.textContent = value ? '正在生成，请稍候' : (state.mode === 'official' ? '回答只依据已采集的官网文件，并附原文链接' : 'AI 可能出错，请自行核对');
  }

  async function send() {
    if (state.sending) {
      stopSession(state);
      return;
    }
    const text = input.value.trim();
    if (!text) return;
    if (!store.llm.key || !store.llm.model) {
      toast('请先填写你的模型 API Key', 'warn');
      openModelSettings();
      return;
    }
    if (text.length > 2000) {
      toast('问题不能超过 2000 字', 'warn');
      return;
    }
    input.value = '';
    input.style.height = 'auto';
    state.messages.push({ role: 'user', content: text });
    state.messages.push({ role: 'assistant', content: '', sources: [], streaming: true });
    const history = state.mode === 'academic'
      ? state.messages.slice(0, -2).slice(-8).map((m) => ({ role: m.role, content: m.content }))
      : [];
    const siteIds = state.mode === 'official' && state.selectedSites.size
      ? Array.from(state.selectedSites).map(Number)
      : [];
    renderLog();
    setSending(true);
    // 不 await：切换页面后这条流仍在跑，结果会写回 session
    runChatStream(state, text, siteIds, history);
  }

  function openModelSettings() {
    const providers = (store.meta && store.meta.providers) || [];
    const defaults = (store.meta && store.meta.defaults) || {};
    const current = { ...store.llm };
    const providerOptions = providers.map((provider) => `<option value="${esc(provider.id)}">${esc(provider.name)}</option>`).join('');
    const body = `
      <div class="stack">
        <div class="notice notice-info">${icon('key')}<div>API Key 只保存在当前标签页的 sessionStorage，关闭标签页即清除。本应用不会把它写入数据库。</div></div>
        <div class="form-grid">
          <div class="field full">
            <label for="llmProvider">服务商</label>
            <select class="select" id="llmProvider"><option value="">自定义 / 保持不变</option>${providerOptions}</select>
            <span class="hint" id="providerHint"></span>
          </div>
          <div class="field full">
            <label for="llmBase">Base URL</label>
            <input class="input" id="llmBase" value="${esc(current.base_url || defaults.base_url || 'https://api.openai.com/v1')}" placeholder="https://api.example.com/v1">
          </div>
          <div class="field full">
            <label for="llmModel">模型 ID</label>
            <input class="input" id="llmModel" value="${esc(current.model || defaults.model || '')}" placeholder="gpt-4.1-mini / deepseek-chat">
            <span class="hint">使用 OpenAI 兼容的 /chat/completions 接口。</span>
          </div>
          <div class="field full">
            <label for="llmKey">API Key</label>
            <div class="key-input-row">
              <input class="input" id="llmKey" type="password" autocomplete="off" value="${esc(current.key || '')}" placeholder="sk-…">
              <button class="btn btn-ghost" type="button" id="toggleKey" aria-label="显示或隐藏 Key">${icon('eye')}</button>
            </div>
            <span class="hint">仅本次浏览器会话有效。</span>
          </div>
        </div>
      </div>`;
    const modal = openModal({
      title: '模型与 API Key',
      body,
      footer: `<button class="btn btn-ghost" type="button" id="clearKeyBtn">${icon('trash')}清除 Key</button>
        <button class="btn btn-ghost" type="button" data-close>取消</button>
        <button class="btn btn-primary" type="button" id="saveModelBtn">保存</button>`,
      size: '',
      onMount: (root, close) => {
        const providerSelect = root.querySelector('#llmProvider');
        const baseInput = root.querySelector('#llmBase');
        const modelInput = root.querySelector('#llmModel');
        const keyInput = root.querySelector('#llmKey');
        providerSelect.addEventListener('change', () => {
          const provider = providers.find((item) => item.id === providerSelect.value);
          if (provider) {
            baseInput.value = provider.base_url;
            modelInput.value = (provider.models && provider.models[0]) || '';
            root.querySelector('#providerHint').textContent = provider.note || '';
          }
        });
        root.querySelector('#toggleKey').addEventListener('click', () => {
          keyInput.type = keyInput.type === 'password' ? 'text' : 'password';
        });
        root.querySelector('#clearKeyBtn').addEventListener('click', () => {
          clearLLMKey();
          keyInput.value = '';
          renderModelCard();
          toast('已清除 API Key', 'success', 1800);
        });
        root.querySelector('#saveModelBtn').addEventListener('click', () => {
          const base = baseInput.value.trim();
          const model = modelInput.value.trim();
          const key = keyInput.value.trim();
          if (!model) { toast('请填写模型 ID', 'warn'); return; }
          if (key && key.length < 8) { toast('API Key 看起来过短', 'warn'); return; }
          saveLLM({ key, base_url: base, model, provider: providerSelect.value });
          renderModelCard();
          close();
          toast('模型设置已保存', 'success', 2000);
        });
        if (current.provider) {
          providerSelect.value = current.provider;
          const provider = providers.find((item) => item.id === current.provider);
          if (provider) root.querySelector('#providerHint').textContent = provider.note || '';
        }
      }
    });
    return modal;
  }

  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(180, input.scrollHeight)}px`;
  }

  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener('click', send);

  renderModelCard();
  renderThreadCard();
  renderLog();
  if (state.mode === 'official') {
    renderLibraryCard();
    renderSiteCard();
    try {
      const data = await api.get('/api/sources');
      state.library = data;
      store.sources = data;
      renderLibraryCard();
      renderSiteCard();
      chatStatus();
    } catch (error) {
      state.library = { sites: [], index: { documents: 0, chunks: 0 } };
      renderLibraryCard();
      renderSiteCard();
      chatStatus();
      toast('官网文件库加载失败', 'warn');
    }
  } else {
    chatStatus();
  }
  refreshFromSession();
  const threads = await loadThreads();
  // 有正在进行的输出时不要用历史覆盖它
  if (!state.messages.length && !state.sending && threads.length) await openThread(threads[0].id);
  input.focus();
}
