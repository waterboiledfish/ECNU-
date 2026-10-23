import { api } from '../api.js';
import { store } from '../store.js';
import {
  icon, esc, avatar, toast, openModal, loadingBlock, emptyState, statusBadge, fmtDateTime, timeAgo
} from '../ui.js';

const TABS = [
  { key: 'moderation', label: '内容审核', iconName: 'shield' },
  { key: 'reports', label: '举报', iconName: 'flag' },
  { key: 'appeals', label: '申诉', iconName: 'alert' },
  { key: 'users', label: '用户', iconName: 'users' },
  { key: 'audit', label: '审计', iconName: 'file' }
];

export async function renderAdmin(el, ctx) {
  if (!store.user?.is_admin) { el.innerHTML = '<div class="notice notice-danger">需要管理员权限</div>'; return; }
  el.innerHTML = loadingBlock('正在加载管理后台…');
  let overview = null;
  let tab = ctx.query?.get('tab') || 'moderation';
  let moderationKind = 'posts';
  let moderationStatus = 'pending';
  let reportsStatus = 'open';
  let appealsStatus = 'open';
  let userQuery = '';

  const loadOverview = async () => {
    overview = await api.get('/api/admin/overview');
  };

  function renderShell() {
    el.innerHTML = `<div class="view-page">
      <div class="page-head"><div><h2>管理后台</h2><p>内容审核、举报与申诉处理、采集概况。所有操作都会写入审计日志。</p></div>
        <div class="page-head-actions"><a class="btn btn-ghost" href="#/sources">${icon('database')}官网采集</a></div></div>
      <div class="stat-row">
        <div class="stat"><div class="label">用户</div><div class="value">${overview.users}</div><div class="hint">注册账号</div></div>
        <div class="stat"><div class="label">待审核</div><div class="value" style="color:var(--amber-500)">${overview.pending_posts + overview.pending_comments}</div><div class="hint">帖子 ${overview.pending_posts} · 评论 ${overview.pending_comments}</div></div>
        <div class="stat"><div class="label">待处理举报</div><div class="value" style="color:var(--red-600)">${overview.open_reports}</div><div class="hint">申诉 ${overview.open_appeals} 条</div></div>
        <div class="stat"><div class="label">文件库</div><div class="value">${overview.documents}</div><div class="hint">${overview.sites} 个站点 · ${overview.chunks} 段</div></div>
      </div>
      <div class="toolbar"><div class="tabs" id="adminTabs">${TABS.map((item) => `<button class="tab ${tab === item.key ? 'active' : ''}" data-tab="${item.key}">${icon(item.iconName)} ${item.label}</button>`).join('')}</div>
        <span class="tiny muted right">${overview.last_crawl ? `最近采集：${statusText(overview.last_crawl.status)} · ${timeAgo(overview.last_crawl.started_at)}` : '尚未采集'}</span>
      </div>
      <div id="adminContent">${loadingBlock('正在加载…')}</div>
    </div>`;
    el.querySelector('#adminTabs').addEventListener('click', (event) => {
      const button = event.target.closest('[data-tab]');
      if (!button) return;
      tab = button.getAttribute('data-tab');
      el.querySelectorAll('#adminTabs .tab').forEach((item) => item.classList.toggle('active', item.getAttribute('data-tab') === tab));
      window.history.replaceState({}, '', `#/admin?tab=${tab}`);
      loadTab();
    });
    loadTab();
  }

  function statusText(status) {
    return { running: '进行中', finished: '完成', failed: '失败', cancelled: '已停止' }[status] || status;
  }

  async function loadTab() {
    const box = el.querySelector('#adminContent');
    if (!box) return;
    box.innerHTML = loadingBlock('正在加载…');
    try {
      if (tab === 'moderation') await renderModeration(box);
      else if (tab === 'reports') await renderReports(box);
      else if (tab === 'appeals') await renderAppeals(box);
      else if (tab === 'users') await renderUsers(box);
      else await renderAudit(box);
    } catch (error) {
      box.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  async function renderModeration(box) {
    const data = await api.get(`/api/admin/moderation?kind=${moderationKind}&status=${moderationStatus}`);
    box.innerHTML = `<div class="toolbar mb-12">
        <div class="segmented" id="modKind"><button data-kind="posts" class="${moderationKind === 'posts' ? 'active' : ''}">帖子</button><button data-kind="comments" class="${moderationKind === 'comments' ? 'active' : ''}">评论</button></div>
        <div class="segmented" id="modStatus"><button data-status="pending" class="${moderationStatus === 'pending' ? 'active' : ''}">待审核</button><button data-status="hidden" class="${moderationStatus === 'hidden' ? 'active' : ''}">已隐藏</button><button data-status="all" class="${moderationStatus === 'all' ? 'active' : ''}">全部</button></div>
        <span class="tiny muted right">${data.total} 条</span></div>
      ${data.items.length ? `<div class="stack">${data.items.map((item) => `
        <article class="queue-item">
          <div class="queue-head">
            <div><div class="queue-title">${item.kind === 'post' ? esc(item.title) : `评论：${esc(item.post_title || '')}`}</div>
              <div class="queue-meta mt-6">
                ${avatar(item.author, 'xs')} ${esc(item.author.nickname)} ${item.anonymous ? '<span class="tag">匿名</span>' : ''}
                <span>${timeAgo(item.created_at)}</span>${statusBadge(item.status)}
                <span class="tag tag-red">风险 ${item.moderation?.risk || 0}</span>
                ${(item.moderation?.categories || []).map((cat) => `<span class="tag tag-amber">${esc(cat)}</span>`).join('')}
              </div>
            </div>
            <a class="btn btn-xs btn-ghost" href="${esc(item.link)}">查看原帖</a>
          </div>
          <div class="queue-body">${esc(item.body)}</div>
          <div class="queue-actions">
            <button class="btn btn-xs btn-accent" data-mod="${item.kind}" data-id="${item.id}" data-action="approve">通过</button>
            <button class="btn btn-xs btn-ghost" data-mod="${item.kind}" data-id="${item.id}" data-action="hide">隐藏</button>
            <button class="btn btn-xs btn-danger" data-mod="${item.kind}" data-id="${item.id}" data-action="remove">删除</button>
          </div>
        </article>`).join('')}</div>` : emptyState({ iconName: 'shield', title: '没有待处理内容', desc: '当前队列是空的。' })}`;
    box.querySelectorAll('#modKind [data-kind]').forEach((button) => {
      button.addEventListener('click', () => { moderationKind = button.getAttribute('data-kind'); loadTab(); });
    });
    box.querySelectorAll('#modStatus [data-status]').forEach((button) => {
      button.addEventListener('click', () => { moderationStatus = button.getAttribute('data-status'); loadTab(); });
    });
    box.querySelectorAll('[data-mod]').forEach((button) => {
      button.addEventListener('click', async () => {
        const kind = button.getAttribute('data-mod');
        const id = button.getAttribute('data-id');
        const action = button.getAttribute('data-action');
        askNote(action, async (note) => {
          try {
            await api.post(`/api/admin/moderation/${kind}/${id}`, { action, note });
            toast('处理完成', 'success');
            await loadTab();
            await loadOverview();
          } catch (error) { toast(error.message, 'error'); }
        });
      });
    });
  }

  function askNote(action, callback) {
    const labels = { approve: '通过并恢复可见', hide: '隐藏内容', remove: '删除内容' };
    openModal({
      title: labels[action] || '处理内容',
      body: `<div class="field"><label for="adminNote">备注（可选，记录在审核日志中）</label><textarea class="textarea" id="adminNote" maxlength="300" rows="3"></textarea></div>`,
      footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="confirmNote">确认</button>`,
      onMount: (root, close) => {
        root.querySelector('#confirmNote').addEventListener('click', async () => {
          const note = root.querySelector('#adminNote').value.trim();
          close();
          await callback(note);
        });
      }
    });
  }

  async function renderReports(box) {
    const data = await api.get(`/api/admin/reports?status=${reportsStatus}`);
    box.innerHTML = `<div class="toolbar mb-12"><div class="segmented" id="reportStatus">
        ${[['open', '待处理'], ['resolved', '已处理'], ['all', '全部']].map(([value, label]) => `<button data-status="${value}" class="${reportsStatus === value ? 'active' : ''}">${label}</button>`).join('')}
      </div><span class="tiny muted right">${data.items.length} 条</span></div>
      ${data.items.length ? `<div class="stack">${data.items.map((report) => `
        <article class="queue-item">
          <div class="queue-head"><div><div class="queue-title">${esc(report.reason)} <span class="badge badge-warn">${esc(report.target_type)}</span></div>
            <div class="queue-meta mt-6"><span>举报人：${esc(report.reporter)}</span><span>${timeAgo(report.created_at)}</span><a href="${esc(report.link)}" class="link-btn">查看内容</a></div></div>
            <span class="tag ${report.status === 'open' ? 'tag-amber' : 'tag-green'}">${report.status === 'open' ? '待处理' : '已处理'}</span></div>
          ${report.preview ? `<div class="queue-body">${esc(report.preview)}</div>` : ''}
          ${report.detail ? `<p class="small muted">${esc(report.detail)}</p>` : ''}
          ${report.status === 'open' ? `<div class="queue-actions">
            <button class="btn btn-xs btn-ghost" data-report="${report.id}" data-action="ignore">忽略</button>
            <button class="btn btn-xs btn-ghost" data-report="${report.id}" data-action="warn">警告</button>
            <button class="btn btn-xs btn-ghost" data-report="${report.id}" data-action="hide">隐藏内容</button>
            <button class="btn btn-xs btn-danger" data-report="${report.id}" data-action="remove">删除内容</button>
          </div>` : `<div class="tiny muted">处理结果：${esc(report.action || '—')}</div>`}
        </article>`).join('')}</div>` : emptyState({ iconName: 'flag', title: '没有举报', desc: '当前筛选条件下没有记录。' })}`;
    box.querySelectorAll('#reportStatus [data-status]').forEach((button) => {
      button.addEventListener('click', () => { reportsStatus = button.getAttribute('data-status'); loadTab(); });
    });
    box.querySelectorAll('[data-report]').forEach((button) => {
      button.addEventListener('click', () => {
        const action = button.getAttribute('data-action');
        const id = button.getAttribute('data-report');
        openModal({
          title: '处理举报',
          body: `<div class="field"><label for="reportReply">给举报人的说明（可选）</label><textarea class="textarea" id="reportReply" maxlength="500" rows="3"></textarea></div>`,
          footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="resolveReport">确认处理</button>`,
          onMount: (root, close) => {
            root.querySelector('#resolveReport').addEventListener('click', async () => {
              try {
                await api.post(`/api/admin/reports/${id}`, { action, reply: root.querySelector('#reportReply').value.trim() });
                close();
                toast('举报已处理', 'success');
                await loadTab();
                await loadOverview();
              } catch (error) { toast(error.message, 'error'); }
            });
          }
        });
      });
    });
  }

  async function renderAppeals(box) {
    const data = await api.get(`/api/admin/appeals?status=${appealsStatus}`);
    box.innerHTML = `<div class="toolbar mb-12"><div class="segmented" id="appealStatus">
        ${[['open', '待处理'], ['resolved', '已处理'], ['all', '全部']].map(([value, label]) => `<button data-status="${value}" class="${appealsStatus === value ? 'active' : ''}">${label}</button>`).join('')}
      </div></div>
      ${data.items.length ? `<div class="stack">${data.items.map((appeal) => `
        <article class="queue-item">
          <div class="queue-head"><div><div class="queue-title">${esc(appeal.nickname)} 的申诉</div>
            <div class="queue-meta mt-6"><span>${timeAgo(appeal.created_at)}</span><span class="tag">${esc(appeal.target_type)}</span><span>${esc(appeal.status)}</span></div></div>
            <a class="btn btn-xs btn-ghost" href="${esc(appeal.link)}">查看内容</a></div>
          <div class="queue-body">${esc(appeal.preview)}</div>
          <p class="small">申诉理由：${esc(appeal.reason)}</p>
          ${appeal.status === 'open' ? `<div class="queue-actions">
            <button class="btn btn-xs btn-accent" data-appeal="${appeal.id}" data-action="accept">通过并恢复</button>
            <button class="btn btn-xs btn-ghost" data-appeal="${appeal.id}" data-action="reject">驳回</button>
          </div>` : ''}
        </article>`).join('')}</div>` : emptyState({ iconName: 'alert', title: '没有申诉', desc: '当前筛选条件下没有记录。' })}`;
    box.querySelectorAll('#appealStatus [data-status]').forEach((button) => {
      button.addEventListener('click', () => { appealsStatus = button.getAttribute('data-status'); loadTab(); });
    });
    box.querySelectorAll('[data-appeal]').forEach((button) => {
      button.addEventListener('click', () => {
        const action = button.getAttribute('data-action');
        const id = button.getAttribute('data-appeal');
        openModal({
          title: action === 'accept' ? '通过申诉' : '驳回申诉',
          body: `<div class="field"><label for="appealReply">回复用户（可选）</label><textarea class="textarea" id="appealReply" maxlength="500" rows="3"></textarea></div>`,
          footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="resolveAppeal">确认</button>`,
          onMount: (root, close) => {
            root.querySelector('#resolveAppeal').addEventListener('click', async () => {
              try {
                await api.post(`/api/admin/appeals/${id}`, { action, reply: root.querySelector('#appealReply').value.trim() });
                close();
                toast('申诉已处理', 'success');
                await loadTab();
                await loadOverview();
              } catch (error) { toast(error.message, 'error'); }
            });
          }
        });
      });
    });
  }

  async function renderUsers(box) {
    const data = await api.get(`/api/admin/users?q=${encodeURIComponent(userQuery)}`);
    box.innerHTML = `<div class="toolbar mb-12"><input class="input input-sm" id="adminUserSearch" placeholder="搜索昵称" value="${esc(userQuery)}" style="max-width:260px"><span class="tiny muted right">${data.total} 位用户</span></div>
      <section class="card" style="overflow:hidden"><div class="list">${data.items.map((user) => `
        <div class="list-item" style="align-items:center">
          ${avatar({ nickname: user.nickname, avatar_url: user.avatar_url, avatar: 'preset:ocean' }, 'sm')}
          <div class="grow"><div class="list-title">${esc(user.nickname)} ${user.role === 'admin' ? '<span class="tag tag-amber">管理员</span>' : ''}</div>
            <div class="list-meta">${esc(user.major || '未填写专业')}${user.grade ? ` · ${esc(user.grade)}` : ''} · ${user.posts} 篇帖子 · 注册于 ${esc((user.created_at || '').slice(0, 10))}</div></div>
          <a class="btn btn-xs btn-ghost" href="#/forum/user/${user.id}">主页</a>
        </div>`).join('')}</div></section>`;
    const search = box.querySelector('#adminUserSearch');
    search.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { userQuery = event.currentTarget.value.trim(); loadTab(); }
    });
  }

  async function renderAudit(box) {
    const data = await api.get('/api/admin/audit');
    box.innerHTML = `<section class="card pad"><div class="section-title">${icon('file')} 最近 50 条操作</div>
      ${data.items.length ? `<div class="list">${data.items.map((item) => `
        <div class="list-item"><div class="grow"><div class="list-title">${esc(item.action)}</div>
          <div class="list-meta">${esc(item.actor)} · ${esc(item.target)} · ${fmtDateTime(item.created_at, true)}</div></div></div>`).join('')}</div>`
        : emptyState({ iconName: 'file', title: '还没有审计记录', desc: '' })}</section>`;
  }

  await loadOverview();
  renderShell();
}
