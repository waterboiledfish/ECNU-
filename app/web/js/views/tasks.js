import { api } from '../api.js';
import { store } from '../store.js';
import {
  icon, esc, toast, openModal, confirmDialog, loadingBlock, emptyState,
  requestNotifyPermission, toLocalInput, fromLocalInput, fmtDateTime, timeAgo
} from '../ui.js';

const CHANNEL_LABELS = {
  inapp: '应用内',
  browser: '浏览器通知',
  system: '系统弹窗',
  cmd: 'CMD 窗口'
};

const RECURRENCE_LABELS = {
  once: '仅一次',
  daily: '每天',
  weekly: '每周',
  monthly: '每月'
};

function defaultDue() {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  date.setSeconds(0, 0);
  date.setMinutes(Math.ceil(date.getMinutes() / 5) * 5);
  return toLocalInput(date.toISOString());
}

function groupItems(items) {
  const now = Date.now();
  const overdue = [];
  const today = [];
  const later = [];
  const parse = (item) => new Date(item.due_at).getTime();
  for (const item of items) {
    if (item.overdue || parse(item) < now) overdue.push(item);
    else {
      const date = new Date(item.due_at);
      const nowDate = new Date();
      if (date.toDateString() === nowDate.toDateString()) today.push(item);
      else later.push(item);
    }
  }
  const sort = (list) => list.sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  return { overdue: sort(overdue), today: sort(today), later: sort(later) };
}

export async function renderTasks(el, ctx) {
  el.innerHTML = loadingBlock('正在读取待办…');
  let data;
  const load = async (silent = false) => {
    data = await api.get('/api/reminders');
    if (!silent) render();
    else render();
  };
  const channels = (data = null) => (data ? data.meta.available_channels : []);
  let reminderData = null;

  function itemHtml(item) {
    const freq = item.recurrence !== 'once'
      ? `<span class="tag tag-navy">${RECURRENCE_LABELS[item.recurrence] || item.recurrence}</span>`
      : '';
    const fired = item.fired ? '<span class="tag">已提醒</span>' : '';
    const channelsHtml = (item.channels || []).map((channel) => `<span class="tag">${esc(CHANNEL_LABELS[channel] || channel)}</span>`).join('');
    return `<div class="task-item ${item.overdue ? 'overdue' : ''}" data-id="${item.id}">
      <button class="task-check" type="button" data-action="complete" aria-label="标记完成">${icon('check')}</button>
      <div class="task-body">
        <div class="task-title">${esc(item.title)}</div>
        ${item.notes ? `<div class="tiny muted" style="margin-top:2px">${esc(item.notes)}</div>` : ''}
        <div class="task-meta">
          <span class="icon-text">${icon('clock')}${esc(item.due_local)}</span>
          ${freq}${fired}${channelsHtml}
          ${item.overdue ? '<span class="tag tag-red">已到期</span>' : ''}
        </div>
      </div>
      <div class="task-actions">
        <button class="icon-btn" type="button" data-action="snooze" title="稍后提醒">${icon('clock')}</button>
        <button class="icon-btn" type="button" data-action="edit" title="编辑">${icon('edit')}</button>
        <button class="icon-btn" type="button" data-action="delete" title="删除">${icon('trash')}</button>
      </div>
    </div>`;
  }

  function section(title, items, emptyText) {
    if (!items.length) return '';
    return `<section class="card pad-sm">
      <div class="section-title">${esc(title)} <span class="spacer"></span><span class="tiny muted">${items.length} 项</span></div>
      <div class="task-group">${items.map(itemHtml).join('')}</div>
    </section>`;
  }

  function render() {
    reminderData = data;
    const groups = groupItems(data.upcoming || []);
    const done = data.done || [];
    const total = (data.upcoming || []).length;
    const overdueCount = groups.overdue.length;
    const todayCount = groups.today.length;
    el.innerHTML = `<div class="view-page">
      <div class="page-head">
        <div><h2>待办与提醒</h2><p>把「几点提醒我做什么」交给小助手。到期后会通过你勾选的方式提醒；在本机运行时还可以弹出窗口。</p></div>
        <div class="page-head-actions">
          <button class="btn btn-ghost" type="button" id="notifyPermBtn">${icon('bell')}开启浏览器通知</button>
          <button class="btn btn-primary" type="button" id="newTaskBtn">${icon('plus')}新建提醒</button>
        </div>
      </div>
      <div class="stat-row">
        <div class="stat"><div class="label">全部待办</div><div class="value">${total}</div><div class="hint">含重复提醒</div></div>
        <div class="stat"><div class="label">已到期</div><div class="value" style="color:var(--red-600)">${overdueCount}</div><div class="hint">建议尽快处理</div></div>
        <div class="stat"><div class="label">今天</div><div class="value">${todayCount}</div><div class="hint">按设定时间提醒</div></div>
        <div class="stat"><div class="label">已完成</div><div class="value">${done.length}</div><div class="hint">保留最近 30 条</div></div>
      </div>
      ${total === 0 ? emptyState({
        iconName: 'bell', title: '还没有待办',
        desc: '例如「今晚 8 点提醒我提交选课」，或「每天早上 9 点提醒我看邮件」。',
        action: '<button class="btn btn-primary" id="emptyNewBtn" type="button">新建第一条提醒</button>'
      }) : `${section('已到期', groups.overdue, '')}
        ${section('今天', groups.today, '')}
        ${section('之后', groups.later, '')}`}
      ${done.length ? `<section class="card pad-sm">
        <div class="section-title">已完成 <span class="spacer"></span><span class="tiny muted">最近 ${done.length} 条</span></div>
        ${done.map((item) => `<div class="task-item done" data-id="${item.id}">
          <span class="task-check checked">${icon('check')}</span>
          <div class="task-body"><div class="task-title">${esc(item.title)}</div>
          <div class="task-meta">${esc(item.due_local)}</div></div>
          <button class="icon-btn" data-action="delete" type="button" title="删除">${icon('trash')}</button>
        </div>`).join('')}
      </section>` : ''}
      <div class="notice notice-info">${icon('info')}<div>「应用内」和「浏览器通知」在任何设备都可用；「系统弹窗 / CMD 窗口」只在运行本服务的这台电脑上弹出，且需要保持服务运行。浏览器通知需要你授予权限。</div></div>
    </div>`;
    bind();
    const permissionButton = el.querySelector('#notifyPermBtn');
    if (permissionButton) {
      if (!('Notification' in window) || Notification.permission === 'granted') {
        permissionButton.hidden = true;
      } else {
        permissionButton.addEventListener('click', async () => {
          const ok = await requestNotifyPermission();
          if (ok) {
            toast('浏览器通知已开启', 'success');
            permissionButton.hidden = true;
          }
        });
      }
    }
  }

  function findItem(id) {
    return [...(reminderData?.upcoming || []), ...(reminderData?.done || [])].find((item) => String(item.id) === String(id));
  }

  function bind() {
    el.querySelectorAll('[data-action]').forEach((button) => {
      button.addEventListener('click', async () => {
        const itemEl = button.closest('[data-id]');
        if (!itemEl) return;
        const id = itemEl.getAttribute('data-id');
        const action = button.getAttribute('data-action');
        const item = findItem(id);
        if (!item) return;
        if (action === 'complete') return complete(item);
        if (action === 'delete') return remove(item);
        if (action === 'edit') return openForm(item);
        if (action === 'snooze') return openSnooze(item);
      });
    });
    el.querySelectorAll('#newTaskBtn, #emptyNewBtn').forEach((button) => {
      button.addEventListener('click', () => openForm(null));
    });
  }

  async function complete(item) {
    try {
      const result = await api.post(`/api/reminders/${item.id}/complete`);
      toast(result.message || '已完成', 'success');
      await load();
    } catch (error) { toast(error.message, 'error'); }
  }

  async function remove(item) {
    const ok = await confirmDialog('删除提醒', `确定删除「${item.title}」吗？`, { danger: true, confirmText: '删除' });
    if (!ok) return;
    try {
      await api.del(`/api/reminders/${item.id}`);
      toast('已删除', 'success', 1600);
      await load();
    } catch (error) { toast(error.message, 'error'); }
  }

  function openSnooze(item) {
    const modal = openModal({
      title: '稍后提醒',
      body: `<p class="small soft">「${esc(item.title)}」推迟多久？</p>
        <div class="chip-row mt-16">
          <button class="chip" data-min="10">10 分钟</button>
          <button class="chip" data-min="30">30 分钟</button>
          <button class="chip" data-min="60">1 小时</button>
          <button class="chip" data-min="180">3 小时</button>
          <button class="chip" data-min="1440">明天</button>
        </div>`,
      footer: '<button class="btn btn-ghost" data-close>取消</button>',
      onMount: (root, close) => {
        root.querySelectorAll('[data-min]').forEach((button) => {
          button.addEventListener('click', async () => {
            try {
              const result = await api.post(`/api/reminders/${item.id}/snooze`, { minutes: Number(button.getAttribute('data-min')) });
              close();
              toast(result.message || '已推迟', 'success');
              await load();
            } catch (error) { toast(error.message, 'error'); }
          });
        });
      }
    });
    return modal;
  }

  function openForm(item) {
    const isEdit = !!item;
    const available = (reminderData?.meta?.available_channels) || ['inapp', 'browser'];
    const selectedChannels = item ? item.channels : ['inapp', 'browser'];
    const body = `<form id="taskForm" class="stack">
      <div class="field">
        <label for="taskTitle">要做什么</label>
        <input class="input" id="taskTitle" maxlength="120" required value="${esc(item?.title || '')}" placeholder="例如：提交选课志愿">
      </div>
      <div class="field">
        <label for="taskNotes">备注（可选）</label>
        <textarea class="textarea" id="taskNotes" maxlength="1000" rows="2" style="min-height:70px">${esc(item?.notes || '')}</textarea>
      </div>
      <div class="form-grid">
        <div class="field">
          <label for="taskDue">提醒时间</label>
          <input class="input" id="taskDue" type="datetime-local" required value="${item ? toLocalInput(item.due_at) : defaultDue()}">
        </div>
        <div class="field">
          <label for="taskRecurrence">重复</label>
          <select class="select" id="taskRecurrence">
            ${Object.entries(RECURRENCE_LABELS).map(([value, label]) => `<option value="${value}" ${item?.recurrence === value ? 'selected' : ''}>${label}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="field">
        <span class="field-label">提醒方式</span>
        <div class="check-grid">
          ${Object.entries(CHANNEL_LABELS).map(([value, label]) => {
            const disabled = !available.includes(value);
            return `<label class="check" style="${disabled ? 'opacity:.5;cursor:not-allowed' : ''}">
              <input type="checkbox" name="channel" value="${value}" ${selectedChannels.includes(value) ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
              <span><span class="check-title">${label}${value === 'inapp' ? '（必选）' : ''}</span>
              <span class="check-desc">${value === 'system' || value === 'cmd' ? '在本机弹窗，需服务运行' : value === 'browser' ? '需要浏览器授权' : '站内提醒'}</span></span>
            </label>`;
          }).join('')}
        </div>
      </div>
      <p class="tiny muted">重复提醒触发后会自动排到下一次；修改时间会重置提醒状态。</p>
    </form>`;
    openModal({
      title: isEdit ? '编辑提醒' : '新建提醒',
      body,
      footer: `<button class="btn btn-ghost" data-close type="button">取消</button>
        <button class="btn btn-primary" type="button" id="saveTaskBtn">${isEdit ? '保存修改' : '创建提醒'}</button>`,
      onMount: (root, close) => {
        const form = root.querySelector('#taskForm');
        root.querySelector('#saveTaskBtn').addEventListener('click', async () => {
          const title = root.querySelector('#taskTitle').value.trim();
          const notes = root.querySelector('#taskNotes').value.trim();
          const dueLocal = root.querySelector('#taskDue').value;
          const recurrence = root.querySelector('#taskRecurrence').value;
          const checked = Array.from(root.querySelectorAll('input[name=channel]:checked')).map((input) => input.value);
          if (!title) { toast('请填写待办内容', 'warn'); return; }
          const due = fromLocalInput(dueLocal);
          if (!due) { toast('请选择提醒时间', 'warn'); return; }
          if (!checked.includes('inapp')) checked.unshift('inapp');
          const payload = { title, notes, due_at: due, recurrence, channels: checked };
          try {
            if (isEdit) await api.patch(`/api/reminders/${item.id}`, payload);
            else await api.post('/api/reminders', payload);
            close();
            toast(isEdit ? '提醒已更新' : '提醒已创建', 'success');
            await load();
          } catch (error) { toast(error.message, 'error'); }
        });
        form.addEventListener('submit', (event) => { event.preventDefault(); root.querySelector('#saveTaskBtn').click(); });
      }
    });
  }

  await load();
  window.addEventListener('app:reminder', () => { load().catch(() => {}); }, { signal: ctx.signal });
}
