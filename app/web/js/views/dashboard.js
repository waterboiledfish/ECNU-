import { api } from '../api.js';
import { store } from '../store.js';
import { icon, esc, avatar, fmtDay, timeAgo, loadingBlock, emptyState } from '../ui.js';

function dateText() {
  return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date());
}

function planRow(plan) {
  const percent = Math.min(100, Math.round((plan.done / Math.max(1, plan.target)) * 100));
  return `<div class="list-item" style="align-items:center">
    <div class="grow">
      <div class="flex-between"><a class="list-title" href="#/plans">${esc(plan.title)}</a>
        <span class="tiny muted">${plan.done}/${plan.target} ${esc(plan.unit || '')}</span></div>
      <div class="progress mt-6"><span style="width:${percent}%"></span></div>
    </div>
  </div>`;
}

function reminderRow(item) {
  return `<div class="list-item">
    <div class="grow">
      <div class="list-title">${esc(item.title)}</div>
      <div class="list-meta">${item.overdue ? '<span class="tag tag-red">已到期</span> ' : ''}${esc(item.due_local)}${item.recurrence !== 'once' ? ' · 重复提醒' : ''}</div>
    </div>
    <a class="btn btn-xs btn-ghost" href="#/tasks">查看</a>
  </div>`;
}

export async function renderDashboard(el) {
  el.innerHTML = loadingBlock('正在整理你的工作台…');
  const data = await api.get('/api/dashboard');
  const user = store.user || data.user;
  const unread = (data.unread.notifications || 0) + (data.unread.messages || 0);
  const planDone = data.plans_completed_today || 0;
  const planTotal = data.plans.length || 0;
  const library = data.library || {};
  const portal = (store.meta && store.meta.portal_url) || 'https://portal2023.ecnu.edu.cn/portal/home';

  el.innerHTML = `<div class="view-page">
    <section class="card hero-card">
      <div class="card-body">
        <div class="hero-greeting">${esc(data.greeting)} · ${dateText()}</div>
        <h2>${esc(user.nickname)}，今天想先完成哪一件？</h2>
        <p>${planTotal ? `有 ${planTotal} 个计划正在进行，${planDone} 个今天已经完成。` : '先建立一个小目标：每天 20 个单词，或一件 10 分钟能做完的事。'}${data.reminders.overdue ? ' 另有提醒已到期，记得处理。' : ''}</p>
        <div class="hero-quick">
          <a class="btn btn-sm" href="#/ask">${icon('sparkles')}问官网文件</a>
          <a class="btn btn-sm" href="#/tasks">${icon('plus')}新建提醒</a>
          <a class="btn btn-sm" href="#/plans">${icon('calendar')}今日计划</a>
          <a class="btn btn-sm" href="#/news">${icon('news')}今日热点</a>
        </div>
      </div>
    </section>

    <div class="stat-row">
      <div class="stat"><div class="label">待办提醒</div><div class="value">${data.reminders.total}</div><div class="hint">今天 ${data.reminders.today} 项 · 逾期 ${data.reminders.overdue} 项</div></div>
      <div class="stat"><div class="label">进行中计划</div><div class="value">${planTotal}</div><div class="hint">今日完成 ${planDone} 个</div></div>
      <div class="stat"><div class="label">未读消息</div><div class="value">${unread}</div><div class="hint">通知 ${data.unread.notifications} · 私信 ${data.unread.messages}</div></div>
      <div class="stat"><div class="label">官网文件库</div><div class="value">${library.documents || 0}</div><div class="hint">${library.crawled_sites || 0}/${library.sites || 0} 个站点已有内容</div></div>
    </div>

    <div class="grid grid-main-side">
      <div class="stack">
        <section class="card">
          <div class="card-head"><h3>即将到来的提醒</h3><a class="card-link" href="#/tasks">全部提醒 ${icon('chevronRight')}</a></div>
          <div class="card-body" style="padding-top:6px">
            ${data.reminders.items.length ? `<div class="list">${data.reminders.items.map(reminderRow).join('')}</div>`
              : emptyState({ iconName: 'bell', title: '暂时没有待办', desc: '把「几点提醒我做什么」交给它，到点会主动提醒你。', action: '<a class="btn btn-sm btn-primary" href="#/tasks">新建提醒</a>' })}
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h3>进行中的计划</h3><a class="card-link" href="#/plans">管理计划 ${icon('chevronRight')}</a></div>
          <div class="card-body" style="padding-top:6px">
            ${planTotal ? `<div class="list">${data.plans.map(planRow).join('')}</div>`
              : emptyState({ iconName: 'calendar', title: '还没有定期计划', desc: '例如「每天背 20 个六级单词」，让小助手每天陪你完成。', action: '<a class="btn btn-sm btn-primary" href="#/plans">创建计划</a>' })}
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h3>校园动态</h3><a class="card-link" href="#/forum">去论坛 ${icon('chevronRight')}</a></div>
          <div class="card-body" style="padding-top:6px">
            ${data.forum.length ? `<div class="list">${data.forum.map((post) => `
              <div class="list-item">
                ${avatar(post.author, 'sm')}
                <div class="grow">
                  <a class="list-title" href="#/forum/${post.id}">${esc(post.title)}</a>
                  <div class="list-meta">${esc(post.author.nickname)} · ${timeAgo(post.created_at)} · ${post.comments} 条评论</div>
                </div>
              </div>`).join('')}</div>`
              : emptyState({ iconName: 'users', title: '论坛刚开张', desc: '发第一条帖子，分享学习经验或生活片段。', action: '<a class="btn btn-sm btn-primary" href="#/forum/new">去发帖</a>' })}
          </div>
        </section>
      </div>

      <div class="stack">
        <section class="card pad">
          <div class="section-title">${icon('database')} 学校公开信息库</div>
          ${library.documents ? `
            <p class="small soft" style="line-height:1.7">已从 ${library.crawled_sites} 个官网采集 ${library.documents} 份文件，可回答带原文链接的校内问题。</p>
            <div class="stack-6 mt-10">
              ${(library.top_sites || []).map((site) => `<div class="kv"><span class="k">${esc(site.name)}</span><span class="v">${site.doc_count} 份</span></div>`).join('')}
            </div>
            <a class="btn btn-sm btn-soft btn-block mt-16" href="#/ask">${icon('sparkles')}开始提问</a>
          ` : `
            <p class="small soft" style="line-height:1.7">还没有采集官网文件。选择学院或部门采集后，问答会给出原文链接与发布日期。</p>
            <a class="btn btn-sm btn-primary btn-block mt-16" href="#/sources">${icon('download')}去采集官网</a>
          `}
        </section>

        <section class="card pad">
          <div class="section-title">${icon('sparkles')} 快捷入口</div>
          <div class="stack-6">
            <a class="list-item" href="${esc(portal)}" target="_blank" rel="noopener noreferrer">
              <span class="plan-icon" style="width:34px;height:34px;font-size:14px;background:var(--amber-100);color:#96620f">DB</span>
              <div class="grow"><div class="list-title">公共数据库</div><div class="list-meta">学校一站式门户</div></div>
              ${icon('external')}
            </a>
            <a class="list-item" href="#/papers">
              <span class="plan-icon" style="width:34px;height:34px;font-size:14px">${icon('file')}</span>
              <div class="grow"><div class="list-title">论文推荐</div><div class="list-meta">按学习方向找近五年论文</div></div>
              ${icon('chevronRight')}
            </a>
            <a class="list-item" href="#/study">
              <span class="plan-icon" style="width:34px;height:34px;font-size:14px">${icon('book')}</span>
              <div class="grow"><div class="list-title">学习资料</div><div class="list-meta">B站 / 小红书 / 知乎 / 论文</div></div>
              ${icon('chevronRight')}
            </a>
            <a class="list-item" href="#/messages">
              <span class="plan-icon" style="width:34px;height:34px;font-size:14px">${icon('message')}</span>
              <div class="grow"><div class="list-title">私信与通知</div><div class="list-meta">${unread ? `${unread} 条未读` : '暂无未读'}</div></div>
              ${icon('chevronRight')}
            </a>
          </div>
        </section>

        <section class="card pad">
          <div class="section-title">${icon('info')} 使用提示</div>
          <p class="tiny muted" style="line-height:1.75">AI 回答可能出错，学校政策请以原文链接为准。你的模型 API Key 只保存在当前浏览器会话中。</p>
        </section>
      </div>
    </div>
  </div>`;
}
