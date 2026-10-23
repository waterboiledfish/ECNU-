import { api } from '../api.js';
import { store } from '../store.js';
import {
  icon, esc, toast, openModal, confirmDialog, loadingBlock, emptyState
} from '../ui.js';
import { renderMarkdown, typeset } from '../markdown.js';

const CATEGORY = {
  vocab: { label: '词汇', emoji: '📚', unit: '个', target: 20 },
  reading: { label: '阅读', emoji: '📖', unit: '页', target: 20 },
  exercise: { label: '运动', emoji: '🏃', unit: '分钟', target: 30 },
  skill: { label: '技能', emoji: '🛠️', unit: '次', target: 1 },
  custom: { label: '自定义', emoji: '✨', unit: '次', target: 1 }
};

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

function cadenceText(plan) {
  if (plan.cadence === 'weekly') {
    const days = (plan.weekdays || []).map((day) => `周${WEEKDAYS[day - 1]}`).join('、');
    return `每周 ${days || '未设置'}`;
  }
  return '每天';
}

function progressPercent(plan) {
  const target = Number(plan.today.target) || 0;
  if (target <= 0) return plan.today.completed ? 100 : 0;
  return Math.min(100, Math.round((plan.today.done / target) * 100));
}

function targetText(plan) {
  const target = Number(plan.target_count) || 0;
  if (target <= 0) return '不设数量目标';
  return `${target} ${plan.unit}`;
}

export async function renderPlans(el, ctx) {
  el.innerHTML = loadingBlock('正在读取计划…');
  let data;
  let vocabInfo = {};

  const load = async () => {
    data = await api.get('/api/plans');
    const vocabPlans = (data.plans || []).filter((plan) => plan.category === 'vocab' && plan.active);
    vocabInfo = {};
    await Promise.all(vocabPlans.map(async (plan) => {
      try { vocabInfo[plan.id] = await api.get(`/api/plans/${plan.id}/vocab/overview`); } catch (e) { /* 忽略 */ }
    }));
    render();
  };

  function planCard(plan) {
    const meta = CATEGORY[plan.category] || CATEGORY.custom;
    const label = plan.category_label || meta.label;
    const percent = progressPercent(plan);
    const countGoal = (Number(plan.target_count) || 0) > 0;
    const dots = (plan.history || []).map((item) => {
      const today = item.day === plan.today.day;
      return `<span class="week-dot ${item.completed ? 'done' : ''} ${today ? 'today' : ''}" data-label="${item.label}"></span>`;
    }).join('');
    const info = vocabInfo[plan.id];
    const vocabBadge = plan.category === 'vocab' && info
      ? `<span class="tag ${info.due ? 'tag-amber' : 'tag-teal'}">${info.due ? `待复习 ${info.due}` : `已学 ${info.learned}`}</span>`
      : '';
    return `<article class="plan-card" data-id="${plan.id}">
      <div class="plan-top">
        <div class="plan-icon">${meta.emoji}</div>
        <div class="grow">
          <div class="plan-title">${esc(plan.title)}</div>
          <div class="plan-sub"><span class="tag">${esc(label)}</span> ${cadenceText(plan)} · ${targetText(plan)}${plan.reminder_time ? ` · ${plan.reminder_time} 提醒` : ''}</div>
        </div>
        ${plan.active ? '' : '<span class="tag">已暂停</span>'}
        <div class="task-actions">
          <button class="icon-btn" data-action="edit" title="编辑">${icon('edit')}</button>
          <button class="icon-btn" data-action="delete" title="删除">${icon('trash')}</button>
        </div>
      </div>
      <div class="plan-progress-row">
        <div class="ring" style="--val:${percent}"><span>${percent}%</span></div>
        <div class="grow">
          <div class="flex-between tiny muted"><span>今日进度</span><span>${plan.today.done}${countGoal ? `/${plan.today.target}` : ''} ${countGoal ? esc(plan.unit) : '次'}</span></div>
          <div class="progress mt-6"><span style="width:${percent}%"></span></div>
          <div class="flex mt-10"><span class="tiny muted">连续 ${plan.streak} 天</span><div class="week-dots right">${dots}</div></div>
        </div>
      </div>
      <div class="plan-foot">
        ${vocabBadge}
        ${plan.category === 'vocab'
          ? `<button class="btn btn-sm btn-accent" data-action="vocab">${icon('play')}开始背诵</button>`
          : `<button class="btn btn-sm btn-primary" data-action="plus" ${countGoal && plan.today.completed ? 'disabled' : ''}>${icon('plus')}${countGoal ? '记一次' : '打卡'}</button>`}
        ${plan.today.done > 0 ? `<button class="btn btn-sm btn-ghost" data-action="minus" title="撤销一次" style="padding:0 10px">${icon('undo')}</button>` : ''}
        <button class="btn btn-sm btn-ghost" data-action="coach">${icon('sparkles')}AI 教练</button>
      </div>
      ${plan.note ? `<p class="tiny muted">${esc(plan.note)}</p>` : ''}
    </article>`;
  }

  function render() {
    const plans = data.plans || [];
    const active = plans.filter((plan) => plan.active);
    el.innerHTML = `<div class="view-page">
      <div class="page-head">
        <div><h2>定期计划</h2><p>把大目标拆成每天的一小步：打卡、连续记录，由小助手帮你记着。</p></div>
        <div class="page-head-actions"><button class="btn btn-primary" id="newPlanBtn" type="button">${icon('plus')}新建计划</button></div>
      </div>
      <div class="stat-row">
        <div class="stat"><div class="label">进行中</div><div class="value">${active.length}</div><div class="hint">共 ${plans.length} 个计划</div></div>
        <div class="stat"><div class="label">今日完成</div><div class="value">${data.summary.completed_today}</div><div class="hint">${data.summary.day}</div></div>
        <div class="stat"><div class="label">最长连续</div><div class="value">${Math.max(0, ...plans.map((plan) => plan.streak || 0))}</div><div class="hint">天</div></div>
      </div>
      ${plans.length ? `<div class="grid grid-auto">${plans.map(planCard).join('')}</div>` : emptyState({
        iconName: 'calendar', title: '还没有计划',
        desc: '从一个简单描述开始：「每天晚上练 30 分钟吉他」「每周读一本书」。目标数量可以不填，打卡就算完成。',
        action: '<button class="btn btn-primary" id="emptyPlanBtn" type="button">创建第一个计划</button>'
      })}
      <div class="notice notice-info">${icon('info')}<div>设置提醒时间后，到点会收到应用内通知与浏览器通知；勾选系统弹窗还会在本机弹出提醒。类别选「词汇」时，还可以用内置六级词库做间隔复习。</div></div>
    </div>`;
    bind();
  }

  function findPlan(id) {
    return (data.plans || []).find((plan) => String(plan.id) === String(id));
  }

  function bind() {
    el.querySelectorAll('[data-action]').forEach((button) => {
      button.addEventListener('click', async () => {
        const card = button.closest('[data-id]');
        if (!card) return;
        const plan = findPlan(card.getAttribute('data-id'));
        if (!plan) return;
        const action = button.getAttribute('data-action');
        if (action === 'plus') return progress(plan, 1);
        if (action === 'minus') return progress(plan, -1);
        if (action === 'vocab') return openVocabStart(plan);
        if (action === 'coach') return openCoach(plan);
        if (action === 'edit') return openForm(plan);
        if (action === 'delete') return remove(plan);
      });
    });
    el.querySelectorAll('#newPlanBtn, #emptyPlanBtn').forEach((button) => {
      button.addEventListener('click', () => openForm(null));
    });
  }

  async function progress(plan, delta) {
    try {
      const result = await api.post(`/api/plans/${plan.id}/progress`, { delta });
      if (result.today.completed) toast('今日目标完成，真不错 🎉', 'success');
      else if (delta < 0) toast('已撤销一次', 'success', 1500);
      await load();
    } catch (error) { toast(error.message, 'error'); }
  }

  async function remove(plan) {
    const ok = await confirmDialog('删除计划', `确定删除「${plan.title}」吗？打卡记录也会一起删除。`, { danger: true, confirmText: '删除' });
    if (!ok) return;
    try {
      await api.del(`/api/plans/${plan.id}`);
      toast('计划已删除', 'success');
      await load();
    } catch (error) { toast(error.message, 'error'); }
  }

  function openForm(plan) {
    const isEdit = !!plan;
    const initial = plan || {
      title: '', category: 'custom', category_label: '', cadence: 'daily', weekdays: [],
      target_count: 0, unit: '次', reminder_time: '21:00', note: '', active: true
    };
    const hasTarget = (Number(initial.target_count) || 0) > 0;
    const body = `<form id="planForm" class="stack">
      <div class="field"><label for="planTitle">计划名称</label>
        <input class="input" id="planTitle" maxlength="60" required value="${esc(initial.title)}" placeholder="例如：复习线性代数">
      </div>
      <div class="field"><label for="planNote">具体做什么（可选）</label>
        <textarea class="textarea" id="planNote" maxlength="500" rows="2" style="min-height:70px" placeholder="简单描述一下，例如：每天看一章笔记，做 5 道课后题">${esc(initial.note || '')}</textarea>
        <span class="hint">写清楚要做的事，AI 教练与提醒文案会参考这段描述。</span>
      </div>
      <div class="form-grid">
        <div class="field"><label for="planCategory">类别</label>
          <select class="select" id="planCategory">
            ${Object.entries(CATEGORY).map(([key, meta]) => `<option value="${key}" ${initial.category === key ? 'selected' : ''}>${meta.emoji} ${meta.label}</option>`).join('')}
          </select>
        </div>
        <div class="field" id="categoryLabelField" style="${initial.category === 'custom' ? '' : 'display:none'}">
          <label for="planCategoryLabel">自定义类型名称</label>
          <input class="input" id="planCategoryLabel" maxlength="20" value="${esc(initial.category_label || '')}" placeholder="例如：吉他练习 / 书法">
        </div>
        <div class="field"><label for="planCadence">频率</label>
          <select class="select" id="planCadence">
            <option value="daily" ${initial.cadence === 'daily' ? 'selected' : ''}>每天</option>
            <option value="weekly" ${initial.cadence === 'weekly' ? 'selected' : ''}>每周</option>
          </select>
        </div>
        <div class="field"><label for="planTime">提醒时间（可选）</label>
          <input class="input" id="planTime" type="time" value="${esc(initial.reminder_time || '')}">
        </div>
        <div class="field" id="weekdayField" style="${initial.cadence === 'weekly' ? '' : 'display:none'}">
          <span class="field-label">星期几</span>
          <div class="chip-row">
            ${WEEKDAYS.map((label, index) => `<label class="chip" style="cursor:pointer">
              <input type="checkbox" name="weekday" value="${index + 1}" ${(initial.weekdays || []).includes(index + 1) ? 'checked' : ''} style="accent-color:var(--teal-500)"> 周${label}
            </label>`).join('')}
          </div>
        </div>
      </div>
      <label class="check"><input type="checkbox" id="planUseTarget" ${hasTarget ? 'checked' : ''}>
        <span><span class="check-title">设置数量目标（可选）</span><span class="check-desc">不勾选时，每天打卡一次就算完成，适合「练琴」「读一章」这类没有固定数量的计划。</span></span>
      </label>
      <div class="form-grid" id="targetFields" style="${hasTarget ? '' : 'display:none'}">
        <div class="field"><label for="planTarget">目标数量</label>
          <input class="input" id="planTarget" type="number" min="1" max="999" value="${hasTarget ? initial.target_count : 1}">
        </div>
        <div class="field"><label for="planUnit">单位</label>
          <input class="input" id="planUnit" maxlength="8" value="${esc(initial.unit || '次')}" placeholder="个 / 页 / 分钟">
        </div>
      </div>
    </form>`;
    openModal({
      title: isEdit ? '编辑计划' : '新建定期计划',
      body,
      footer: `<button class="btn btn-ghost" data-close type="button">取消</button>
        <button class="btn btn-primary" type="button" id="savePlanBtn">${isEdit ? '保存修改' : '创建计划'}</button>`,
      onMount: (root, close) => {
        const category = root.querySelector('#planCategory');
        const labelField = root.querySelector('#categoryLabelField');
        const useTarget = root.querySelector('#planUseTarget');
        const targetFields = root.querySelector('#targetFields');
        const target = root.querySelector('#planTarget');
        const unit = root.querySelector('#planUnit');
        category.addEventListener('change', () => {
          labelField.style.display = category.value === 'custom' ? '' : 'none';
          const meta = CATEGORY[category.value];
          if (!isEdit && meta && useTarget.checked) { target.value = meta.target; unit.value = meta.unit; }
        });
        useTarget.addEventListener('change', () => {
          targetFields.style.display = useTarget.checked ? '' : 'none';
        });
        const cadence = root.querySelector('#planCadence');
        cadence.addEventListener('change', () => {
          root.querySelector('#weekdayField').style.display = cadence.value === 'weekly' ? '' : 'none';
        });
        root.querySelector('#savePlanBtn').addEventListener('click', async () => {
          const title = root.querySelector('#planTitle').value.trim();
          if (!title) { toast('请填写计划名称', 'warn'); return; }
          const categoryLabel = root.querySelector('#planCategoryLabel').value.trim();
          if (category.value === 'custom' && !categoryLabel) { toast('请填写自定义类型名称', 'warn'); return; }
          const weekdays = Array.from(root.querySelectorAll('input[name=weekday]:checked')).map((input) => Number(input.value));
          if (cadence.value === 'weekly' && !weekdays.length) { toast('每周计划请选择至少一天', 'warn'); return; }
          const payload = {
            title,
            category: category.value,
            category_label: categoryLabel,
            cadence: cadence.value,
            weekdays,
            target_count: useTarget.checked ? (Number(target.value) || 1) : 0,
            unit: unit.value.trim() || '次',
            reminder_time: root.querySelector('#planTime').value || '',
            note: root.querySelector('#planNote').value.trim(),
            active: true
          };
          try {
            if (isEdit) await api.patch(`/api/plans/${plan.id}`, payload);
            else await api.post('/api/plans', payload);
            close();
            toast(isEdit ? '计划已更新' : '计划已创建', 'success');
            await load();
          } catch (error) { toast(error.message, 'error'); }
        });
      }
    });
  }

  async function openCoach(plan) {
    const modal = openModal({
      title: 'AI 学习教练',
      body: '<div class="loading-overlay"><div class="spinner"></div><span>正在根据最近 7 天记录准备建议…</span></div>',
      footer: '<button class="btn btn-ghost" data-close>关闭</button>'
    });
    try {
      const result = await api.post(`/api/plans/${plan.id}/coach`, {});
      modal.bodyEl.innerHTML = `<div class="md">${renderMarkdown(result.advice)}</div>
        <p class="tiny muted mt-16">${result.mode === 'ai' ? '由你配置的模型生成，建议仅供参考。' : '本地建议模板（未配置模型 Key 时使用）。'}</p>`;
      typeset(modal.bodyEl);
    } catch (error) {
      modal.bodyEl.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  async function openVocabStart(plan) {
    const info = vocabInfo[plan.id] || {};
    const size = Math.min(30, Math.max(5, plan.target_count || 20));
    const modal = openModal({
      title: `开始背诵 · ${plan.title}`,
      body: `<div class="stack">
        <p class="small soft" style="line-height:1.7">今天有 <strong>${info.due || 0}</strong> 个到期复习词，已学 <strong>${info.learned || 0}</strong> 个。未填 API Key 时使用内置六级词库。</p>
        <div class="form-grid">
          <div class="field"><label for="vocabSize">本轮单词数</label><input class="input" id="vocabSize" type="number" min="5" max="30" value="${size}"></div>
          <div class="field"><label class="check" style="margin-top:22px"><input type="checkbox" id="vocabAI" ${store.llm.key ? '' : 'disabled'}><span><span class="check-title">AI 生成新词</span><span class="check-desc">${store.llm.key ? '会消耗你的 API 额度' : '需先配置 API Key'}</span></span></label></div>
        </div>
        <div class="notice notice-info">${icon('info')}<div>先回忆，再翻面确认；不认识的词会进入明天的复习队列。</div></div>
      </div>`,
      footer: `<button class="btn btn-ghost" data-close type="button">取消</button>
        <button class="btn btn-primary" type="button" id="startVocabBtn">开始</button>`,
      onMount: (root, close) => {
        root.querySelector('#startVocabBtn').addEventListener('click', async () => {
          const count = Number(root.querySelector('#vocabSize').value) || size;
          const useAI = root.querySelector('#vocabAI').checked;
          close();
          try {
            const session = await api.post(`/api/plans/${plan.id}/vocab/start`, {
              size: count,
              mode: useAI ? 'ai' : 'mixed'
            });
            if (!session.items || !session.items.length) { toast('没有可学习的单词', 'warn'); return; }
            if (session.warning) toast(session.warning, 'warn', 5000);
            openVocabSession(plan, session);
          } catch (error) { toast(error.message, 'error'); }
        });
      }
    });
    return modal;
  }

  function openVocabSession(plan, session) {
    const items = session.items;
    const results = [];
    let index = 0;
    const modal = openModal({
      title: '单词背诵',
      body: '<div id="vocabStage"></div>',
      footer: '<button class="btn btn-ghost" type="button" data-close>退出</button>',
      size: '',
      onMount: (root) => {
        const stage = root.querySelector('#vocabStage');
        const renderWord = () => {
          const item = items[index];
          stage.innerHTML = `<div class="vocab-stage">
            <div class="vocab-top"><span class="tag tag-teal">${index + 1} / ${items.length}</span><span class="tag">${item.source === 'review' ? '复习' : item.source === 'ai' ? 'AI 新词' : '新词'}</span></div>
            <div class="progress"><span style="width:${Math.round((index / items.length) * 100)}%"></span></div>
            <div class="vocab-word">${esc(item.word)}</div>
            <div class="vocab-phonetic">${esc(item.phonetic || '')}</div>
            <div class="vocab-hidden" id="vocabMeaning">先在心里回想意思，再点击下方按钮</div>
            <button class="btn btn-ghost btn-block" type="button" id="revealBtn">${icon('eye')}显示释义</button>
            <div class="vocab-actions" id="vocabChoices" hidden>
              <button class="btn btn-danger" type="button" data-known="0">不认识</button>
              <button class="btn btn-accent" type="button" data-known="1">认识</button>
            </div>
          </div>`;
          stage.querySelector('#revealBtn').addEventListener('click', () => {
            stage.querySelector('#revealBtn').hidden = true;
            const meaning = stage.querySelector('#vocabMeaning');
            meaning.className = 'vocab-meaning';
            meaning.innerHTML = `${esc(item.meaning)}${item.example ? `<div class="vocab-example">${esc(item.example)}${item.example_cn ? `<br>${esc(item.example_cn)}` : ''}</div>` : ''}`;
            stage.querySelector('#vocabChoices').hidden = false;
          });
          stage.querySelectorAll('[data-known]').forEach((button) => {
            button.addEventListener('click', () => {
              const known = button.getAttribute('data-known') === '1';
              results.push({ ...item, known });
              index += 1;
              if (index >= items.length) finish();
              else renderWord();
            });
          });
        };
        const finish = async () => {
          stage.innerHTML = `<div class="vocab-score"><div class="spinner" style="margin:0 auto 12px"></div><p class="muted">正在保存进度…</p></div>`;
          try {
            const result = await api.post(`/api/plans/${plan.id}/vocab/grade`, {
              session_id: session.session_id,
              results: results.map((item) => ({
                word: item.word,
                known: item.known,
                meaning: item.meaning || '',
                example: item.example || '',
                example_cn: item.example_cn || ''
              }))
            });
            stage.innerHTML = `<div class="vocab-score">
              <div class="big">${result.accuracy}%</div>
              <p class="soft">记住了 ${result.score} / ${result.total} 个</p>
              <p class="tiny muted mt-10">今日计划：${result.today.done}/${result.today.target}；${result.due_tomorrow} 个单词将在之后复习。</p>
              <a class="btn btn-primary mt-16" href="#/plans" data-finish>回到计划</a>
            </div>`;
            stage.querySelector('[data-finish]')?.addEventListener('click', () => modal.close());
            await load();
          } catch (error) {
            stage.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>
              <button class="btn btn-ghost btn-block mt-16" type="button" data-close>关闭</button>`;
          }
        };
        renderWord();
      }
    });
    return modal;
  }

  await load();
  window.addEventListener('app:notification', (event) => {
    if (event.detail && event.detail.kind === 'plan') load().catch(() => {});
  }, { signal: ctx.signal });
}
