import { api } from '../api.js';
import { store, applyTheme } from '../store.js';
import {
  icon, esc, avatar, toast, openModal, confirmDialog, loadingBlock, emptyState,
  timeAgo, fmtDateTime, setUnread, requestNotifyPermission
} from '../ui.js';

/* ------------------------------------------------------------ 私信 */
export async function renderMessages(el, ctx) {
  el.innerHTML = loadingBlock('正在打开信箱…');
  const state = { conversations: [], peerId: ctx.params[0] ? Number(ctx.params[0]) : null, peer: null, messages: [] };
  el.innerHTML = `<div class="view-page">
    <div class="page-head"><div><h2>私信</h2><p>和同学一对一交流。请不要在私信中发送密码、验证码等敏感信息。</p></div>
      <div class="page-head-actions"><a class="btn btn-ghost" href="#/forum">${icon('users')}去论坛找人</a></div></div>
    <div class="inbox">
      <div class="inbox-list">
        <div class="inbox-head">会话 <span class="tiny muted" id="convMeta"></span></div>
        <div id="convList">${loadingBlock('加载中…')}</div>
      </div>
      <div class="thread" id="threadPanel">${emptyState({ iconName: 'message', title: '选择一个会话', desc: '从左侧选择一位同学开始聊天。' })}</div>
    </div>
  </div>`;

  async function loadConversations() {
    const data = await api.get('/api/messages/conversations');
    state.conversations = data.items || [];
    setUnread(data.unread, null);
    renderConversations();
    if (!state.peerId && state.conversations.length) {
      openPeer(state.conversations[0].peer.id, false);
    } else if (state.peerId) {
      openPeer(state.peerId, false);
    } else {
      renderThreadEmpty();
    }
  }

  function renderConversations() {
    const list = el.querySelector('#convList');
    const meta = el.querySelector('#convMeta');
    if (meta) meta.textContent = state.conversations.length ? `${state.conversations.length} 个` : '';
    if (!state.conversations.length) {
      list.innerHTML = emptyState({ iconName: 'inbox', title: '还没有私信', desc: '去论坛的帖子或主页找同学聊聊。' });
      return;
    }
    list.innerHTML = state.conversations.map((conv) => `
      <div class="conversation ${state.peerId === conv.peer.id ? 'active' : ''}" data-peer="${conv.peer.id}">
        ${avatar(conv.peer, 'sm')}
        <div class="conv-body">
          <div class="conv-name"><span>${esc(conv.peer.nickname)}</span>
            ${conv.unread ? `<span class="unread-dot">${conv.unread}</span>` : `<span class="tiny muted">${timeAgo(conv.last.created_at)}</span>`}</div>
          <div class="conv-last">${conv.last.mine ? '我：' : ''}${esc(conv.last.body)}</div>
        </div>
      </div>`).join('');
    list.querySelectorAll('[data-peer]').forEach((node) => {
      node.addEventListener('click', () => openPeer(Number(node.getAttribute('data-peer')), true));
    });
  }

  function renderThreadEmpty() {
    const panel = el.querySelector('#threadPanel');
    panel.innerHTML = emptyState({ iconName: 'message', title: '还没有选择会话', desc: '选择一个同学开始聊天，或从论坛发起私信。' });
  }

  async function openPeer(peerId, updateHash = true) {
    state.peerId = peerId;
    if (updateHash) window.history.replaceState({}, '', `#/messages/${peerId}`);
    renderConversations();
    const panel = el.querySelector('#threadPanel');
    panel.innerHTML = loadingBlock('正在加载对话…');
    try {
      const data = await api.get(`/api/messages/${peerId}`);
      state.peer = data.peer;
      state.messages = data.messages || [];
      renderThread();
      const conv = state.conversations.find((item) => item.peer.id === peerId);
      if (conv && conv.unread) {
        const unreadCount = conv.unread;
        conv.unread = 0;
        setUnread(Math.max(0, (store.unread.messages || 0) - unreadCount), null);
        renderConversations();
      }
    } catch (error) {
      panel.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  function renderThread() {
    const panel = el.querySelector('#threadPanel');
    const peer = state.peer;
    if (!peer) { renderThreadEmpty(); return; }
    panel.innerHTML = `<div class="thread-head">
        ${avatar(peer, 'sm')}
        <div class="grow"><a class="strong" href="#/forum/user/${peer.id}" style="color:var(--text)">${esc(peer.nickname)}</a>
          <div class="tiny muted">${esc([peer.department, peer.major].filter(Boolean).join(' · ') || '华东师范大学')}${peer.grade ? ` · ${esc(peer.grade)}` : ''}</div></div>
        <span class="tiny muted">${state.messages.length} 条消息</span>
      </div>
      <div class="thread-log" id="threadLog">
        ${state.messages.length ? state.messages.map((message) => `
          <div>
            <div class="bubble ${message.mine ? 'mine' : ''}">${esc(message.body)}</div>
            <div class="bubble-time ${message.mine ? 'text-right' : ''}">${fmtDateTime(message.created_at)}</div>
          </div>`).join('') : `<div class="empty" style="margin:auto"><div class="empty-icon">${icon('message')}</div><h3>打个招呼吧</h3><p>这是你和 ${esc(peer.nickname)} 的第一条消息。</p></div>`}
      </div>
      <div class="thread-composer">
        <textarea id="messageInput" maxlength="1000" rows="1" placeholder="输入消息，Enter 发送"></textarea>
        <button class="btn btn-primary" id="sendMessage" type="button">${icon('send')}发送</button>
      </div>`;
    const log = panel.querySelector('#threadLog');
    if (log) log.scrollTop = log.scrollHeight;
    const input = panel.querySelector('#messageInput');
    const send = async () => {
      const body = input.value.trim();
      if (!body) return;
      try {
        await api.post('/api/messages', { to: state.peerId, body });
        input.value = '';
        await openPeer(state.peerId, false);
        loadConversations().catch(() => {});
      } catch (error) { toast(error.message, 'error'); }
    };
    panel.querySelector('#sendMessage').addEventListener('click', send);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); }
    });
    input.focus();
  }

  await loadConversations();
  window.addEventListener('app:notification', (event) => {
    const detail = event.detail;
    if (detail && detail.kind === 'message') {
      loadConversations().catch(() => {});
      if (state.peerId) openPeer(state.peerId, false).catch(() => {});
    }
  }, { signal: ctx.signal });
}

/* ------------------------------------------------------------ 通知 */
const NOTIFICATION_ICONS = {
  reminder: 'bell', plan: 'calendar', comment: 'message', reply: 'message', like: 'heart',
  follow: 'users', message: 'message', moderation: 'shield', report: 'flag', appeal: 'alert'
};

const NOTIFICATION_LABELS = {
  reminder: '提醒', plan: '计划', comment: '评论', reply: '回复', like: '点赞',
  follow: '关注', message: '私信', moderation: '审核', report: '举报', appeal: '申诉'
};

export async function renderNotifications(el, ctx) {
  el.innerHTML = loadingBlock('正在读取通知…');
  let data = null;
  const load = async () => {
    data = await api.get('/api/notifications?limit=50');
    setUnread(null, data.unread);
    render();
  };

  function render() {
    el.innerHTML = `<div class="view-page">
      <div class="page-head"><div><h2>通知</h2><p>提醒、点赞、评论、关注、审核与系统消息都在这里。</p></div>
        <div class="page-head-actions">
          ${data.unread ? '<button class="btn btn-ghost" id="markAll">全部标为已读</button>' : ''}
          <a class="btn btn-ghost" href="#/messages">${icon('message')}私信</a>
        </div></div>
      <section class="card" style="overflow:hidden">
        ${data.items.length ? data.items.map((item) => {
          const payload = item.payload || {};
          return `<div class="notification ${item.read ? '' : 'unread'}" data-id="${item.id}" data-link="${esc(payload.link || '')}">
            <div class="n-icon">${icon(NOTIFICATION_ICONS[item.kind] || 'bell')}</div>
            <div class="grow">
              <div class="n-text">${esc(payload.text || '收到一条通知')}${payload.preview ? `<div class="tiny muted mt-6">${esc(payload.preview)}</div>` : ''}</div>
              <div class="n-time">${timeAgo(item.created_at)} · ${esc(NOTIFICATION_LABELS[item.kind] || item.kind)}</div>
            </div>
            ${item.read ? '' : '<span class="tag tag-teal">未读</span>'}
          </div>`;
        }).join('') : emptyState({ iconName: 'bell', title: '暂时没有通知', desc: '提醒到期、有人评论或关注你时，会在这里出现。' })}
      </section>
    </div>`;
    bind();
  }

  function bind() {
    el.querySelector('#markAll')?.addEventListener('click', async () => {
      try {
        await api.post('/api/notifications/read', { all: true });
        setUnread(null, 0);
        await load();
      } catch (error) { toast(error.message, 'error'); }
    });
    el.querySelectorAll('.notification').forEach((node) => {
      node.addEventListener('click', async () => {
        const id = Number(node.getAttribute('data-id'));
        const link = node.getAttribute('data-link');
        if (!node.classList.contains('unread')) {
          if (link) window.location.hash = link.replace(/^#/, '');
          return;
        }
        try {
          await api.post('/api/notifications/read', { ids: [id] });
          node.classList.remove('unread');
          const tag = node.querySelector('.tag.tag-teal');
          if (tag) tag.remove();
          setUnread(null, Math.max(0, (store.unread.notifications || 0) - 1));
        } catch (e) { /* 忽略 */ }
        if (link) window.location.hash = link.replace(/^#/, '');
      });
    });
  }

  await load();
}

/* ------------------------------------------------------------ 个人设置 */
function tagEditor(values, placeholder) {
  return `<div class="tag-input" data-tag-editor>
    ${values.map((value) => `<span class="tag tag-teal" data-value="${esc(value)}">${esc(value)}<button type="button" data-remove aria-label="移除">×</button></span>`).join('')}
    <input maxlength="60" placeholder="${esc(placeholder)}">
    <button class="tag-add" type="button" data-add aria-label="添加">＋</button>
  </div>`;
}

function readTagEditor(container) {
  return Array.from(container.querySelectorAll('[data-value]')).map((node) => node.getAttribute('data-value'));
}

export async function renderProfile(el, ctx) {
  el.innerHTML = loadingBlock('正在读取个人资料…');
  const [profileData, stats] = await Promise.all([api.get('/api/profile'), api.get('/api/profile/stats')]);
  const user = profileData.user;
  store.user = { ...store.user, ...user };
  const meta = store.meta || {};
  const access = meta.access || { urls: [], lan_enabled: false, public_base_url: '' };
  const academics = (meta.academics && meta.academics.departments) || [];
  const majorOptions = (departmentName) => {
    const hit = academics.find((item) => item.name === departmentName);
    const list = hit ? hit.majors || [] : academics.flatMap((item) => item.majors || []);
    return Array.from(new Set(list));
  };
  const orgLine = [user.department, user.major].filter(Boolean).join(' · ') || '华东师范大学';
  let avatarValue = user.avatar;
  let themeValue = user.settings?.theme || 'system';

  el.innerHTML = `<div class="view-page">
    <div class="page-head"><div><h2>个人设置</h2><p>完善资料后，论文、热点与学习资料推荐会更贴合你。所有个人信息只保存在本机。</p></div>
      <div class="page-head-actions"><button class="btn btn-primary" id="saveProfile" type="button">${icon('check')}保存资料</button></div></div>
    <div class="profile-grid">
      <aside class="card profile-card">
        <div id="profileAvatar">${avatar({ ...user, avatar: avatarValue }, 'xl', 'avatar-ring')}</div>
        <h2>${esc(user.nickname)}</h2>
        <div class="p-meta">${esc(orgLine)}${user.grade ? ` · ${esc(user.grade)}` : ''}${user.role === 'admin' ? ' · 管理员' : ''}</div>
        <p class="p-bio">${esc(user.bio || '还没有写简介。')}</p>
        <div class="user-stats" style="justify-content:center">
          <div><strong>${stats.posts}</strong><span>帖子</span></div>
          <div><strong>${stats.followers}</strong><span>关注者</span></div>
          <div><strong>${stats.plans}</strong><span>计划</span></div>
        </div>
        <div class="divider mt-16"></div>
        <div class="stack-6 mt-16">
          <a class="btn btn-sm btn-ghost" href="#/forum/user/${user.id}">${icon('user')}查看公开主页</a>
          <button class="btn btn-sm btn-ghost" id="logoutBtn" type="button">${icon('logout')}退出登录</button>
        </div>
      </aside>

      <div class="stack">
        <section class="card pad">
          <div class="section-title">${icon('user')} 基本资料</div>
          <div class="form-grid">
            <div class="field"><label for="profNickname">昵称</label><input class="input" id="profNickname" value="${esc(user.nickname)}" maxlength="16"></div>
            <div class="field"><label for="profDepartment">院系</label><select class="select" id="profDepartment">
              <option value="">未填写</option>
              ${academics.map((item) => `<option value="${esc(item.name)}" ${user.department === item.name ? 'selected' : ''}>${esc(item.name)}${item.category ? ` · ${esc(item.category)}` : ''}</option>`).join('')}
            </select></div>
            <div class="field"><label for="profMajor">专业</label>
              <select class="select" id="profMajor">
                <option value="">未填写</option>
                ${majorOptions(user.department || '').map((major) => `<option value="${esc(major)}" ${user.major === major ? 'selected' : ''}>${esc(major)}</option>`).join('')}
                <option value="__custom__" ${user.major && !majorOptions(user.department || '').includes(user.major) ? 'selected' : ''}>其他（手动填写）</option>
              </select>
              <input class="input mt-6" id="profMajorCustom" maxlength="40" placeholder="填写专业名称"
                value="${esc(user.major && !majorOptions(user.department || '').includes(user.major) ? user.major : '')}"
                ${user.major && !majorOptions(user.department || '').includes(user.major) ? '' : 'hidden'}>
            </div>
            <div class="field"><label for="profGrade">年级</label><select class="select" id="profGrade">
              <option value="">未填写</option>
              ${(meta.grades || ['大一', '大二', '大三', '大四', '研一', '研二', '研三', '博士', '教师', '其他']).map((grade) => `<option value="${esc(grade)}" ${user.grade === grade ? 'selected' : ''}>${esc(grade)}</option>`).join('')}
            </select></div>
            <div class="field"><label for="profBio">简介</label><input class="input" id="profBio" value="${esc(user.bio || '')}" maxlength="200" placeholder="一句话介绍自己"></div>
          </div>
          <div class="field mt-16"><span class="field-label">头像</span>
            <div class="avatar-picker" id="avatarPicker">
              ${(meta.avatars || []).map((item) => `<button class="avatar-choice ${avatarValue === `preset:${item.key}` ? 'active' : ''}" type="button" data-avatar="preset:${esc(item.key)}">
                <span class="avatar avatar-md" style="background:${item.bg}">${item.emoji}</span>${esc(item.label)}</button>`).join('')}
            </div>
            <div class="flex mt-10">
              <label class="btn btn-sm btn-ghost">${icon('upload')}上传图片<input type="file" id="avatarFile" accept="image/png,image/jpeg,image/webp" hidden></label>
              <span class="tiny muted">建议正方形，≤ 600KB，会统一转为 256px PNG。</span>
            </div>
          </div>
        </section>

        <section class="card pad">
          <div class="section-title">${icon('cap')} 学习偏好</div>
          <div class="stack">
            <div class="field"><span class="field-label">学习方向（用于论文与资料推荐）</span>
              <div id="directionsEditor">${tagEditor(user.directions || [], '输入方向后回车，例如：人工智能')}</div>
            </div>
            <div class="field"><span class="field-label">本学期课程</span>
              <div id="coursesEditor">${tagEditor(user.courses || [], '输入课程名后回车')}</div>
            </div>
            <div class="field"><span class="field-label">热点偏好</span>
              <div class="chip-row">
                ${(meta.news_categories || []).map((cat) => `<label class="chip" style="cursor:pointer"><input type="checkbox" name="newsCat" value="${esc(cat.key)}" ${(user.settings?.news_categories || []).includes(cat.key) ? 'checked' : ''} style="accent-color:var(--teal-500)"> ${esc(cat.label)}</label>`).join('')}
              </div>
            </div>
            <div class="field"><span class="field-label">自定义热点话题</span>
              <div id="newsTopicsEditor">${tagEditor(user.settings?.news_topics || [], '输入话题后回车，例如：AI、考研、新能源')}</div>
              <span class="hint">填什么就按什么去查热点（公开新闻源），可以填多个。</span>
            </div>
          </div>
        </section>

        <section class="card pad">
          <div class="section-title">${icon('bell')} 提醒与外观</div>
          <div class="settings-list">
            <div class="settings-row">
              <div><div class="s-label">默认提醒方式</div><div class="s-desc">新建提醒时会默认勾选这些方式；系统弹窗与 CMD 窗口仅在本机服务运行时生效。</div></div>
            </div>
            <div class="check-grid" style="margin-bottom:12px">
              ${(meta.channels || ['inapp', 'browser']).map((channel) => {
                const labels = { inapp: '应用内', browser: '浏览器通知', system: '系统弹窗', cmd: 'CMD 窗口' };
                return `<label class="check"><input type="checkbox" name="defaultChannel" value="${channel}" ${(user.settings?.notify_channels || ['inapp', 'browser']).includes(channel) ? 'checked' : ''}><span><span class="check-title">${labels[channel] || channel}</span></span></label>`;
              }).join('')}
            </div>
            <div class="settings-row">
              <div><div class="s-label">主题</div><div class="s-desc">跟随系统，或固定浅色 / 深色。</div></div>
              <div class="segmented" id="themeChoice">
                ${[['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']].map(([value, label]) => `<button type="button" data-theme-choice="${value}" class="${themeValue === value ? 'active' : ''}">${label}</button>`).join('')}
              </div>
            </div>
            <div class="settings-row">
              <div><div class="s-label">浏览器通知</div><div class="s-desc">允许后，提醒到期会出现在系统通知中心。</div></div>
              <button class="btn btn-sm btn-ghost" id="notifyPermission" type="button">${icon('bell')}检查权限</button>
            </div>
          </div>
        </section>

        <section class="card pad">
          <div class="section-title">${icon('globe')} 访问方式</div>
          <div class="settings-list">
            <div class="settings-row">
              <div><div class="s-label">本机地址</div><div class="s-desc">在这台电脑的浏览器里打开就是它。</div></div>
              <div class="flex">
                <span class="tag tag-navy mono">${esc(access.urls?.[0] || '')}</span>
                <button class="btn btn-xs btn-ghost" type="button" data-copy="${esc(access.urls?.[0] || '')}">${icon('copy')}复制</button>
              </div>
            </div>
            ${access.lan_enabled
              ? (access.urls || []).slice(1).map((url) => `<div class="settings-row">
                  <div><div class="s-label">局域网地址</div><div class="s-desc">连同一个 Wi-Fi 的同学，可以在浏览器里直接打开它。</div></div>
                  <div class="flex">
                    <span class="tag tag-teal mono">${esc(url)}</span>
                    <button class="btn btn-xs btn-ghost" type="button" data-copy="${esc(url)}">${icon('copy')}复制</button>
                  </div>
                </div>`).join('')
              : `<div class="settings-row">
                  <div><div class="s-label">局域网共享</div><div class="s-desc">当前只监听本机。在项目目录运行 <span class="mono">python -m app --lan</span>（或设置 <span class="mono">ECNU_HOST=0.0.0.0</span>），同一局域网的同学即可访问；首次运行 Windows 会询问是否允许防火墙。</div></div>
                </div>`}
            ${access.public_base_url && access.public_base_url !== access.urls?.[0]
              ? `<div class="settings-row">
                  <div><div class="s-label">对外地址</div><div class="s-desc">部署到服务器或反向代理时配置的公开地址（ECNU_PUBLIC_BASE_URL）。</div></div>
                  <span class="tag tag-teal mono">${esc(access.public_base_url)}</span>
                </div>`
              : ''}
          </div>
        </section>

        <section class="card pad">
          <div class="section-title">${icon('key')} 模型与隐私</div>
          <div class="settings-list">
            <div class="settings-row">
              <div><div class="s-label">登录方式</div><div class="s-desc">${esc(store.auth?.label || '本地演示模式')} · 本应用不接触、不保存学号和密码。</div></div>
              <span class="tag tag-navy">${store.auth?.mode || 'dev'}</span>
            </div>
            <div class="settings-row">
              <div><div class="s-label">模型 API Key</div><div class="s-desc">当前：${store.llm.model ? esc(store.llm.model) : '未配置'}；Key 仅保存在本浏览器会话。</div></div>
              <button class="btn btn-sm btn-ghost" id="clearKey" type="button">清除 Key</button>
            </div>
            <div class="settings-row">
              <div><div class="s-label">删除账号</div><div class="s-desc">删除个人资料、待办、计划与私信；公开帖子会显示为已注销用户。此操作不可恢复。</div></div>
              <button class="btn btn-sm btn-danger" id="deleteAccount" type="button">删除账号</button>
            </div>
          </div>
        </section>
      </div>
    </div>`;

  bindTagEditor(el.querySelector('#directionsEditor'));
  bindTagEditor(el.querySelector('#coursesEditor'));
  bindTagEditor(el.querySelector('#newsTopicsEditor'));

  el.querySelectorAll('[data-avatar]').forEach((button) => {
    button.addEventListener('click', () => {
      avatarValue = button.getAttribute('data-avatar');
      el.querySelectorAll('[data-avatar]').forEach((item) => item.classList.toggle('active', item === button));
      el.querySelector('#profileAvatar').innerHTML = avatar({ ...user, avatar: avatarValue }, 'xl', 'avatar-ring');
    });
  });

  el.querySelector('#avatarFile').addEventListener('change', async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 600 * 1024) { toast('图片不能超过 600KB', 'warn'); return; }
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const result = await api.post('/api/profile/avatar', { image: reader.result });
        store.user.avatar = result.avatar;
        store.user.avatar_url = result.avatar_url;
        avatarValue = result.avatar;
        el.querySelector('#profileAvatar').innerHTML = avatar(store.user, 'xl', 'avatar-ring');
        toast('头像已更新', 'success');
      } catch (error) { toast(error.message, 'error'); }
    };
    reader.readAsDataURL(file);
  });

  el.querySelectorAll('[data-theme-choice]').forEach((button) => {
    button.addEventListener('click', async () => {
      themeValue = button.getAttribute('data-theme-choice');
      el.querySelectorAll('[data-theme-choice]').forEach((item) => item.classList.toggle('active', item === button));
      const resolved = applyTheme(themeValue);
      try { await api.patch('/api/profile', { settings: { theme: resolved } }); } catch (e) { /* 忽略 */ }
    });
  });

  el.querySelector('#notifyPermission').addEventListener('click', async () => {
    const ok = await requestNotifyPermission();
    toast(ok ? '浏览器通知已开启' : '未获得通知权限', ok ? 'success' : 'warn');
  });

  el.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const text = button.getAttribute('data-copy') || '';
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        toast('已复制访问地址', 'success');
      } catch (error) {
        toast(text, 'info', 8000);
      }
    });
  });

  el.querySelector('#clearKey').addEventListener('click', async () => {
    const { clearLLMKey } = await import('../store.js');
    clearLLMKey();
    toast('已清除 API Key', 'success');
  });

  el.querySelector('#profMajor')?.addEventListener('change', (event) => {
    const custom = el.querySelector('#profMajorCustom');
    if (!custom) return;
    const isCustom = event.target.value === '__custom__';
    custom.hidden = !isCustom;
    if (isCustom) custom.focus();
  });

  el.querySelector('#profDepartment')?.addEventListener('change', (event) => {
    const select = el.querySelector('#profMajor');
    const custom = el.querySelector('#profMajorCustom');
    if (!select) return;
    const list = majorOptions(event.target.value);
    select.innerHTML = '<option value="">未填写</option>'
      + list.map((major) => `<option value="${esc(major)}">${esc(major)}</option>`).join('')
      + '<option value="__custom__">其他（手动填写）</option>';
    if (custom) { custom.value = ''; custom.hidden = true; }
  });

  el.querySelector('#saveProfile').addEventListener('click', async () => {
    const nickname = el.querySelector('#profNickname').value.trim();
    if (nickname.length < 2) { toast('昵称至少 2 个字', 'warn'); return; }
    const directions = readTagEditor(el.querySelector('#directionsEditor'));
    const courses = readTagEditor(el.querySelector('#coursesEditor'));
    const newsCats = Array.from(el.querySelectorAll('input[name=newsCat]:checked')).map((input) => input.value);
    const channels = Array.from(el.querySelectorAll('input[name=defaultChannel]:checked')).map((input) => input.value);
    try {
      const result = await api.patch('/api/profile', {
        nickname,
        bio: el.querySelector('#profBio').value.trim(),
        major: el.querySelector('#profMajor')?.value === '__custom__'
          ? el.querySelector('#profMajorCustom').value.trim()
          : (el.querySelector('#profMajor')?.value || ''),
        department: el.querySelector('#profDepartment')?.value.trim() || '',
        grade: el.querySelector('#profGrade').value,
        directions,
        courses,
        avatar: avatarValue,
        settings: {
          news_categories: newsCats,
          news_topics: readTagEditor(el.querySelector('#newsTopicsEditor')),
          notify_channels: channels,
          theme: themeValue
        }
      });
      store.user = { ...store.user, ...result.user };
      toast('资料已保存', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });

  el.querySelector('#logoutBtn').addEventListener('click', async () => {
    const ok = await confirmDialog('退出登录', '确定退出当前账号吗？', { confirmText: '退出' });
    if (!ok) return;
    try { await api.post('/api/auth/logout'); } catch (e) { /* 忽略 */ }
    window.location.reload();
  });

  el.querySelector('#deleteAccount').addEventListener('click', async () => {
    const ok = await confirmDialog('删除账号', '这会删除你的个人资料、待办、计划、私信与关注关系，且无法恢复。公开帖子会转为匿名。确定继续吗？', { danger: true, confirmText: '继续' });
    if (!ok) return;
    const modal = openModal({
      title: '最后确认',
      body: `<div class="field"><label for="deleteConfirm">请输入 DELETE 以确认</label><input class="input" id="deleteConfirm" autocomplete="off"></div>
        <div class="notice notice-danger mt-10">${icon('alert')}<div>删除后无法恢复。</div></div>`,
      footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger" id="reallyDelete">永久删除</button>`,
      onMount: (root, close) => {
        root.querySelector('#reallyDelete').addEventListener('click', async () => {
          if (root.querySelector('#deleteConfirm').value !== 'DELETE') { toast('请输入 DELETE 确认', 'warn'); return; }
          try {
            await api.del('/api/profile?confirm=DELETE');
            close();
            toast('账号已删除', 'success');
            window.setTimeout(() => window.location.reload(), 800);
          } catch (error) { toast(error.message, 'error'); }
        });
      }
    });
    return modal;
  });

  function bindTagEditor(container) {
    if (!container) return;
    const input = container.querySelector('input');
    const addButton = container.querySelector('[data-add]');
    // 容器是外层 div，真正的行内编辑器是 input 的父节点
    const host = input.parentNode || container;
    const add = (focus = true) => {
      const raw = input.value.trim();
      if (!raw) return;
      // 支持一次粘贴多个：逗号、顿号、分号、换行都当作分隔符
      const parts = raw.split(/[,，、;；\n]+/).map((item) => item.trim()).filter(Boolean).slice(0, 24);
      let added = false;
      for (const value of parts) {
        const exists = Array.from(container.querySelectorAll('[data-value]'))
          .some((node) => node.getAttribute('data-value') === value);
        if (exists) continue;
        const chip = document.createElement('span');
        chip.className = 'tag tag-teal';
        chip.setAttribute('data-value', value);
        chip.innerHTML = `${esc(value)}<button type="button" data-remove aria-label="移除">×</button>`;
        host.insertBefore(chip, input);
        bindRemove(chip);
        added = true;
      }
      input.value = '';
      if (added && focus) input.focus();
    };
    const bindRemove = (chip) => {
      chip.querySelector('[data-remove]').addEventListener('click', () => chip.remove());
    };
    container.querySelectorAll('[data-value]').forEach(bindRemove);
    input.addEventListener('keydown', (event) => {
      // 中文输入法按回车是在确认候选词，此时不能当成「添加」
      if (event.isComposing || event.keyCode === 229) return;
      if (event.key === 'Enter' || event.key === ',' || event.key === '，') {
        event.preventDefault();
        add();
        return;
      }
      if (event.key === 'Backspace' && !input.value) {
        const chips = container.querySelectorAll('[data-value]');
        if (chips.length) chips[chips.length - 1].remove();
      }
    });
    // 离开输入框也帮用户提交，避免「输了没按回车」导致丢失
    input.addEventListener('blur', () => add(false));
    addButton?.addEventListener('click', () => add());
  }
}
