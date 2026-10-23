import { api } from '../api.js';
import { store } from '../store.js';
import { icon, esc, toast, openModal, loadingBlock, emptyState, fmtDateTime, safeHttpUrl } from '../ui.js';

export async function renderSources(el, ctx) {
  el.innerHTML = loadingBlock('正在读取官网目录…');
  let data = null;
  let selected = new Set();
  let query = '';
  let pollTimer = null;

  const load = async () => {
    data = await api.get('/api/sources');
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
      <div class="notice notice-info">${icon('info')}<div>采集只读取公开页面，遵守目标站点 robots.txt 与访问频率限制。部分学院站点会拦截自动化请求（403 / TLS），此时会记录失败并保留官网链接，不会编造内容。请勿高频重复采集。</div></div>
    </div>`;
    bind();
  }

  function crawlPanel(crawl) {
    if (crawl.running) {
      return `<section class="card pad-sm crawl-panel">
        <div class="flex-between"><div class="small strong">${icon('refresh')} ${esc(crawl.message || '正在采集…')}</div>
          ${store.user?.is_admin ? '<button class="btn btn-xs btn-ghost" id="cancelCrawl" type="button">停止</button>' : ''}</div>
        <div class="crawl-progress">成功 ${crawl.pages_ok || 0} 页 · 失败 ${crawl.pages_failed || 0} 页 · 队列 ${crawl.queued || 0}</div>
        <div class="progress"><span style="width:${Math.min(95, ((crawl.pages_ok + crawl.pages_failed) / Math.max(1, (crawl.site_total || 1) * 30)) * 100)}%"></span></div>
        ${(crawl.errors || []).length ? `<div class="crawl-error">${crawl.errors.slice(-3).map(esc).join('<br>')}</div>` : ''}
      </section>`;
    }
    return '';
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
    el.querySelector('#crawlSelected')?.addEventListener('click', () => {
      if (!selected.size) { toast('请先选择要采集的站点', 'warn'); return; }
      startCrawl(Array.from(selected).map(Number));
    });
    el.querySelector('#cancelCrawl')?.addEventListener('click', async () => {
      try { await api.post('/api/sources/crawl/cancel'); toast('已请求停止', 'success'); } catch (error) { toast(error.message, 'error'); }
    });
  }

  async function startCrawl(siteIds) {
    try {
      await api.post('/api/sources/crawl', { site_ids: siteIds });
      toast('采集已开始，可以离开此页，任务会在后台继续', 'success', 5000);
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
