import { api } from '../api.js';
import { store } from '../store.js';
import { icon, esc, toast, openModal, loadingBlock, emptyState, fmtDateTime, safeHttpUrl } from '../ui.js';

export async function renderSources(el, ctx) {
  el.innerHTML = loadingBlock('正在读取官网目录…');
  let data = null;
  let priorityData = null;
  let selected = new Set();
  let query = '';
  let pollTimer = null;

  const load = async () => {
    const [sources, priorityList] = await Promise.all([
      api.get('/api/sources'),
      api.get('/api/sources/priority?limit=10').catch(() => null)
    ]);
    data = sources;
    priorityData = priorityList;
    render();
    if (data.crawl && data.crawl.running) startPolling();
  };

  function siteRow(site) {
    return `<div class="source-site" data-site="${site.id}">
      <input type="checkbox" data-select="${site.id}" ${selected.has(String(site.id)) ? 'checked' : ''} ${data.can_crawl ? '' : 'disabled'}>
      <div class="grow">
        <div class="site-name">${esc(site.name)}</div>
        <div class="site-url">${esc(site.url.replace('https://', ''))}</div>
      </div>
      <span class="doc-count">${site.doc_count ? `${site.doc_count} 份文件` : '未采集'}</span>
      <a class="icon-btn" href="${safeHttpUrl(site.url)}" target="_blank" rel="noopener noreferrer" title="打开官网">${icon('external')}</a>
      <button class="icon-btn" type="button" data-docs="${site.id}" title="查看已采集文件" ${site.doc_count ? '' : 'disabled'}>${icon('file')}</button>
      <button class="btn btn-xs btn-ghost" type="button" data-crawl="${site.id}" ${data.can_crawl ? '' : 'disabled'}>采集</button>
    </div>`;
  }

  function filteredSites(category) {
    const sites = category.sites || [];
    const q = query.trim().toLowerCase();
    return q ? sites.filter((site) => site.name.toLowerCase().includes(q) || site.url.toLowerCase().includes(q)) : sites;
  }

  function render() {
    const stats = data.index || {};
    const crawl = data.crawl || {};
    el.innerHTML = `<div class="view-page">
      <div class="page-head">
        <div><h2>官网文件</h2><p>采集学校官网公开页面与 PDF，建立本地检索库。回答会附上原文链接、来源站点与发布日期。</p></div>
        <div class="page-head-actions">
          <button class="btn btn-ghost" id="priorityScan" type="button" ${data.can_crawl ? '' : 'disabled'}>${icon('star')}重点扫描</button>
          <button class="btn btn-ghost" id="importDoc" type="button" ${data.can_crawl ? '' : 'disabled'}>${icon('link')}导入链接</button>
          <a class="btn btn-ghost" href="#/ask">${icon('sparkles')}去提问</a>
          <button class="btn btn-primary" id="crawlSelected" type="button" ${data.can_crawl ? '' : 'disabled'}>${icon('download')}采集所选</button>
        </div>
      </div>
      ${data.can_crawl ? '' : `<div class="notice notice-warn">${icon('lock')}<div>当前部署仅管理员可以触发采集。你仍可浏览已采集的文件。</div></div>`}
      <div class="stat-row">
        <div class="stat"><div class="label">已采集文件</div><div class="value">${data.documents}</div><div class="hint">HTML / PDF / DOCX / TXT</div></div>
        <div class="stat"><div class="label">检索片段</div><div class="value">${stats.chunks || 0}</div><div class="hint">平均 ${stats.avg_chunk_tokens || 0} tokens</div></div>
        <div class="stat"><div class="label">官网入口</div><div class="value">${data.sites.length}</div><div class="hint">${data.sites.filter((site) => site.doc_count > 0).length} 个已有内容</div></div>
        <div class="stat"><div class="label">采集状态</div><div class="value" style="font-size:19px">${crawl.running ? '进行中' : '空闲'}</div><div class="hint">${crawl.message || '按需采集，遵守 robots.txt'}</div></div>
      </div>
      ${crawlPanel(crawl)}
      ${priorityPanel(priorityData)}
      ${agePanel(data)}
      ${lastRunPanel(data.last_run)}
      <div class="card pad-sm">
        <div class="toolbar mb-12">
          <input class="input" id="siteSearch" placeholder="搜索学院或部门" value="${esc(query)}">
          <button class="btn btn-sm btn-ghost" id="selectAll" type="button">全选</button>
          <button class="btn btn-sm btn-ghost" id="selectClear" type="button">清空</button>
          <span class="tiny muted right" id="selCount">已选 ${selected.size} 个站点</span>
        </div>
        <div class="stack">
          ${data.categories.map((category) => {
            const sites = filteredSites(category);
            if (!sites.length) return '';
            return `<details ${query ? 'open' : (category.name === '学校门户' || category.name === '教务与培养' ? 'open' : '')}>
              <summary style="cursor:pointer;font-weight:700;font-size:13.5px;padding:8px 2px">${esc(category.name)} <span class="tiny muted">· ${sites.length}</span></summary>
              <div class="stack-6 mt-6">${sites.map(siteRow).join('')}</div>
            </details>`;
          }).join('')}
        </div>
      </div>
      <div class="notice notice-info">${icon('info')}<div>采集只读取公开页面，遵守目标站点 robots.txt 与访问频率限制。部分学院站点会拦截自动化请求（403 / TLS），此时会记录失败并保留官网链接，不会编造内容。没抓到的具体文件，可以用右上角「导入链接」单独补进来。</div></div>
    </div>`;
    bind();
  }

  function priorityPanel(payload) {
    if (!payload) return '';
    const topics = payload.topics || [];
    const items = payload.items || [];
    return `<section class="card pad-sm">
      <div class="flex-between wrap">
        <div class="small strong">${icon('star')} 猜你想看：</div>
        <span class="tiny muted">已入库 ${items.length} 篇</span>
      </div>
      ${items.length
        ? `<div class="stack-6 mt-10">${items.map((doc) => `
          <a class="live-item" href="${safeHttpUrl(doc.url)}" target="_blank" rel="noopener noreferrer">
            <span class="live-title">${esc(doc.title)}</span>
            <span class="live-meta">${esc(doc.site_name)}${doc.published_at ? ` · ${esc(String(doc.published_at).slice(0, 10))}` : ''}${icon('external')}</span>
          </a>`).join('')}</div>`
        : `<p class="tiny muted mt-10">还没有猜到你想要的通知。点右上角「重点扫描」，系统会优先把「${topics.slice(0, 3).map(esc).join(' / ')}」这类内容找出来。</p>`}
    </section>`;
  }

  function crawlPanel(crawl) {
    if (crawl.running) {
      return `<section class="card pad-sm crawl-panel">
        <div class="flex-between"><div class="small strong">${icon('refresh')} ${esc(crawl.message || '正在采集…')}</div>
          ${store.user?.is_admin ? '<button class="btn btn-xs btn-ghost" id="cancelCrawl" type="button">停止</button>' : ''}</div>
        <div class="crawl-progress">成功 ${crawl.pages_ok || 0} 页 · 失败 ${crawl.pages_failed || 0} 页${crawl.pages_priority ? ` · 重点 ${crawl.pages_priority} 篇` : ''} · 队列 ${crawl.queued || 0}</div>
        <div class="progress"><span style="width:${Math.min(95, ((crawl.pages_ok + crawl.pages_failed) / Math.max(1, (crawl.site_total || 1) * 30)) * 100)}%"></span></div>
        ${(crawl.errors || []).length ? `<div class="crawl-error">${crawl.errors.slice(-3).map(esc).join('<br>')}</div>` : ''}
      </section>`;
    }
    return '';
  }

  const AGE_LABELS = { 0: '不限（全部收录）', 365: '最近 1 年', 730: '最近 2 年', 1095: '最近 3 年', 1825: '最近 5 年' };

  function agePanel(payload) {
    const current = Number(payload.max_age_days) || 0;
    const choices = payload.age_choices || [0, 365, 730, 1095, 1825];
    const options = (choices.includes(current) ? choices : [...choices, current].sort((a, b) => a - b))
      .map((days) => `<option value="${days}" ${days === current ? 'selected' : ''}>${AGE_LABELS[days] || `最近 ${Math.round(days / 365)} 年`}</option>`)
      .join('');
    return `<section class="card pad-sm">
      <div class="flex-between wrap">
        <div class="grow">
          <div class="small strong">${icon('clock')} 收录范围</div>
          <div class="tiny muted mt-6">只把这段时间内发布的官网文件加入检索库（页面上没写日期的照常收录）。改完会自动重建索引。</div>
        </div>
        <select class="select" id="ageSelect" style="width:auto;min-width:150px" ${payload.can_crawl ? '' : 'disabled'}>${options}</select>
      </div>
    </section>`;
  }

  function lastRunPanel(lastRun) {
    if (!lastRun) return '';
    const ok = lastRun.pages_ok || 0;
    const bad = lastRun.pages_failed || 0;
    const old = lastRun.skipped_old || 0;
    const fresh = lastRun.skipped_fresh || 0;
    const hits = lastRun.priority_hits || 0;
    const status = lastRun.status === 'running'
      ? '进行中'
      : (lastRun.focus ? '重点扫描完成' : (bad ? '部分失败' : '已完成'));
    const errors = (lastRun.errors || []).filter(Boolean).slice(-3);
    return `<section class="card pad-sm">
      <div class="flex-between"><div class="small strong">${icon('clock')} 最近一次采集 · ${esc(status)}</div>
        <span class="tiny muted">${lastRun.finished_at ? esc(fmtDateTime(lastRun.finished_at)) : ''}</span></div>
      <div class="tiny muted mt-6">成功 ${ok} 页 · 失败 ${bad} 页${hits ? ` · 重点通知 ${hits} 篇` : ''}${old ? ` · 跳过 ${old} 篇超出收录范围` : ''}${fresh ? ` · 跳过 ${fresh} 篇已抓过` : ''}${lastRun.started_at ? ` · 开始于 ${esc(fmtDateTime(lastRun.started_at))}` : ''}</div>
      ${errors.length ? `<div class="crawl-error mt-6">${errors.map(esc).join('<br>')}</div>` : ''}
      ${bad ? '<div class="tiny muted mt-6">失败的站点会保留官网链接，可点「导入链接」单独补充具体文件。</div>' : ''}
      ${fresh ? '<div class="tiny muted mt-6">已抓过的正文不再重复抓，再点一次「采集」会继续往里抓新页面。</div>' : ''}
    </section>`;
  }

  function openImport() {
    if (!data || !data.can_crawl) { toast('当前部署仅管理员可以导入官网文件', 'warn'); return; }
    openModal({
      title: '导入官网文件',
      body: `<div class="stack">
        <div class="notice notice-info">${icon('info')}<div>粘贴学校官网（ecnu.edu.cn）上的公开页面或 PDF 链接。适合爬虫没抓到、需要脚本渲染或想单独补充的通知、规章与培养方案。</div></div>
        <div class="field"><label for="importUrl">文件链接</label>
          <input class="input" id="importUrl" placeholder="https://www.ecnu.edu.cn/xxxx/xxxx.pdf" maxlength="500" autocomplete="off">
          <span class="hint">只接受 http(s) 且域名在 ecnu.edu.cn 白名单内；抓取一次后加入检索库，已存在且内容未变化时会提示。发布日期超出下方「收录范围」的文件会被拒绝。</span>
        </div>
        <div class="tiny muted" id="importStatus"></div>
      </div>`,
      footer: `<button class="btn btn-ghost" type="button" data-close>取消</button>
        <button class="btn btn-primary" type="button" id="importSubmit">${icon('download')}导入</button>`,
      onMount: (root, close) => {
        const input = root.querySelector('#importUrl');
        const button = root.querySelector('#importSubmit');
        const statusEl = root.querySelector('#importStatus');
        const submit = async () => {
          const url = input.value.trim();
          if (!/^https?:\/\/[^\s]+$/i.test(url)) { toast('请输入完整的 http(s) 链接', 'warn'); input.focus(); return; }
          button.disabled = true;
          statusEl.textContent = '正在抓取并解析…';
          try {
            const result = await api.post('/api/sources/import', { url });
            toast(result.message || '已导入', 'success', 4200);
            close();
            await load();
          } catch (error) {
            statusEl.textContent = error.message || '导入失败';
            toast(error.message || '导入失败', 'error', 5200);
          } finally { button.disabled = false; }
        };
        button.addEventListener('click', submit);
        input.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); submit(); } });
      }
    });
  }

  function bind() {
    el.querySelectorAll('[data-select]').forEach((checkbox) => {
      checkbox.addEventListener('change', () => {
        const id = checkbox.getAttribute('data-select');
        if (checkbox.checked) selected.add(id);
        else selected.delete(id);
        const count = el.querySelector('#selCount');
        if (count) count.textContent = `已选 ${selected.size} 个站点`;
      });
    });
    el.querySelector('#siteSearch')?.addEventListener('input', (event) => {
      query = event.target.value;
      render();
      const input = el.querySelector('#siteSearch');
      if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    });
    el.querySelector('#selectAll')?.addEventListener('click', () => {
      data.sites.forEach((site) => selected.add(String(site.id)));
      render();
    });
    el.querySelector('#selectClear')?.addEventListener('click', () => {
      selected.clear();
      render();
    });
    el.querySelectorAll('[data-docs]').forEach((button) => {
      button.addEventListener('click', () => openDocs(button.getAttribute('data-docs')));
    });
    el.querySelectorAll('[data-crawl]').forEach((button) => {
      button.addEventListener('click', () => startCrawl([Number(button.getAttribute('data-crawl'))]));
    });
    el.querySelector('#priorityScan')?.addEventListener('click', () => {
      const ids = selected.size
        ? Array.from(selected).map(Number)
        : (data.sites || []).map((site) => site.id);
      startCrawl(ids, true);
      toast(`正在扫描 ${ids.length} 个站点的重点正文`, 'info', 4000);
    });
    el.querySelector('#importDoc')?.addEventListener('click', openImport);
    el.querySelector('#ageSelect')?.addEventListener('change', async (event) => {
      const days = Number(event.target.value) || 0;
      try {
        await api.patch('/api/sources/settings', { max_age_days: days });
        toast(days ? `已设为只收录最近 ${Math.round(days / 365)} 年的文件` : '已设为不限收录时间', 'success');
        await load();
      } catch (error) {
        toast(error.message, 'error');
      }
    });
    el.querySelector('#crawlSelected')?.addEventListener('click', () => {
      if (!selected.size) { toast('请先选择要采集的站点', 'warn'); return; }
      startCrawl(Array.from(selected).map(Number));
    });
    el.querySelector('#cancelCrawl')?.addEventListener('click', async () => {
      try { await api.post('/api/sources/crawl/cancel'); toast('已请求停止', 'success'); } catch (error) { toast(error.message, 'error'); }
    });
  }

  async function startCrawl(siteIds, focus = false) {
    try {
      await api.post('/api/sources/crawl', { site_ids: siteIds, focus });
      toast(
        focus
          ? '重点扫描已开始：只抓保研 / 推免 / 复试等重点正文，可以离开此页'
          : '采集已开始，可以离开此页，任务会在后台继续',
        'success',
        5000
      );
      await load();
    } catch (error) { toast(error.message, 'error'); }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = window.setInterval(async () => {
      try {
        const result = await api.get('/api/sources/crawl/status');
        const status = result.status;
        if (!status.running) {
          window.clearInterval(pollTimer);
          pollTimer = null;
          toast(status.message || '采集完成', 'success', 5000);
          await load();
          return;
        }
        const panel = el.querySelector('.crawl-panel');
        if (panel) {
          const progress = panel.querySelector('.crawl-progress');
          if (progress) progress.textContent = `${status.site || ''} · 成功 ${status.pages_ok} 页 · 失败 ${status.pages_failed} 页 · 队列 ${status.queued}`;
          const label = panel.querySelector('.small.strong');
          if (label) label.innerHTML = `${icon('refresh')} ${esc(status.message || '正在采集…')}`;
        }
      } catch (error) { /* 继续轮询 */ }
    }, 2500);
  }

  async function openDocs(siteId) {
    const modal = openModal({
      title: '已采集文件',
      body: loadingBlock('正在读取文件列表…'),
      size: 'modal-lg',
      footer: '<button class="btn btn-ghost" data-close>关闭</button>'
    });
    try {
      const result = await api.get(`/api/sources/${siteId}/documents?limit=50`);
      modal.bodyEl.innerHTML = `<div class="small soft mb-12">${esc(result.site.name)} · 共 ${result.total} 份</div>
        ${result.items.length ? `<div class="list">${result.items.map((doc) => `
          <div class="list-item">
            <div class="grow">
              <a class="list-title" href="${safeHttpUrl(doc.url)}" target="_blank" rel="noopener noreferrer">${esc(doc.title)}</a>
              <div class="list-meta">${doc.published_at ? `${esc(doc.published_at)} · ` : ''}${esc(doc.content_type)} · ${doc.char_count} 字</div>
            </div>
            <button class="btn btn-xs btn-ghost" data-doc="${doc.id}" type="button">摘录</button>
          </div>`).join('')}</div>` : emptyState({ iconName: 'file', title: '还没有文件', desc: '点击采集后，公开页面会进入检索库。' })}`;
      modal.bodyEl.querySelectorAll('[data-doc]').forEach((button) => {
        button.addEventListener('click', () => openDoc(button.getAttribute('data-doc')));
      });
    } catch (error) {
      modal.bodyEl.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  async function openDoc(docId) {
    const modal = openModal({
      title: '文件摘录',
      body: loadingBlock('正在读取…'),
      size: 'modal-lg',
      footer: '<button class="btn btn-ghost" data-close>关闭</button>'
    });
    try {
      const doc = await api.get(`/api/sources/documents/${docId}`);
      modal.bodyEl.innerHTML = `<div class="stack">
        <div><div class="strong">${esc(doc.title)}</div>
          <div class="tiny muted mt-6">${esc(doc.site_name)} · ${esc(doc.published_at || '日期未标注')} · ${doc.char_count} 字</div></div>
        <a class="btn btn-sm btn-soft" href="${safeHttpUrl(doc.url)}" target="_blank" rel="noopener noreferrer">${icon('external')}打开原文</a>
        <pre style="white-space:pre-wrap;font-family:var(--font);font-size:12.5px;line-height:1.7;background:var(--surface-2);padding:12px;border-radius:10px;max-height:360px;overflow:auto">${esc(doc.excerpt)}</pre>
      </div>`;
    } catch (error) {
      modal.bodyEl.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  await load();
}
