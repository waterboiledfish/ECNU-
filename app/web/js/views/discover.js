import { api } from '../api.js';
import { store, saveLLM } from '../store.js';
import { icon, esc, toast, openModal, loadingBlock, emptyState, timeAgo, safeHttpUrl } from '../ui.js';
import { renderMarkdown, typeset } from '../markdown.js';

function openKeyPrompt(onSaved) {
  const providers = (store.meta && store.meta.providers) || [];
  const defaults = (store.meta && store.meta.defaults) || {};
  const current = { ...store.llm };
  openModal({
    title: '配置模型以使用 AI 功能',
    body: `<div class="stack">
      <div class="notice notice-info">${icon('key')}<div>Key 只保存在当前标签页，不会写入数据库。</div></div>
      <div class="field"><label for="miniProvider">服务商</label>
        <select class="select" id="miniProvider"><option value="">自定义</option>
          ${providers.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}
        </select>
      </div>
      <div class="field"><label for="miniBase">Base URL</label><input class="input" id="miniBase" value="${esc(current.base_url || defaults.base_url || 'https://api.openai.com/v1')}"></div>
      <div class="field"><label for="miniModel">模型 ID</label><input class="input" id="miniModel" value="${esc(current.model || defaults.model || '')}" placeholder="deepseek-chat"></div>
      <div class="field"><label for="miniKey">API Key</label><input class="input" id="miniKey" type="password" value="${esc(current.key || '')}" placeholder="sk-…"></div>
    </div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="miniSave">保存</button>`,
    onMount: (root, close) => {
      const provider = root.querySelector('#miniProvider');
      provider.addEventListener('change', () => {
        const item = providers.find((p) => p.id === provider.value);
        if (item) {
          root.querySelector('#miniBase').value = item.base_url;
          root.querySelector('#miniModel').value = (item.models && item.models[0]) || '';
        }
      });
      root.querySelector('#miniSave').addEventListener('click', () => {
        const key = root.querySelector('#miniKey').value.trim();
        const model = root.querySelector('#miniModel').value.trim();
        const base = root.querySelector('#miniBase').value.trim();
        if (!key || !model) { toast('请填写 Key 与模型 ID', 'warn'); return; }
        saveLLM({ key, model, base_url: base, provider: provider.value });
        close();
        toast('模型已配置', 'success');
        onSaved && onSaved();
      });
    }
  });
}

/* ------------------------------------------------------------ 今日热点 */
export async function renderNews(el, ctx) {
  const categories = (store.meta && store.meta.news_categories) || [
    { key: 'general', label: '综合' }, { key: 'tech', label: '科技' }, { key: 'finance', label: '金融' }
  ];
  const preferred = store.user?.settings?.news_categories || [];
  const myTopics = (store.user?.settings?.news_topics || []).filter(Boolean);
  let active = preferred.find((key) => categories.some((item) => item.key === key)) || categories[0].key;
  let activeTopic = null;
  let feed = null;
  let digest = null;
  let digestLoading = false;

  el.innerHTML = layout();
  bind();
  await load(false);

  function layout() {
    return `<div class="view-page">
      <div class="page-head">
        <div><h2>今日热点</h2><p>聚合当天国内外要闻，按你的偏好分类。新闻来自公开 RSS 与搜索源，标题和链接均指向原媒体。</p></div>
        <div class="page-head-actions">
          <button class="btn btn-ghost" id="newsRefresh" type="button">${icon('refresh')}刷新</button>
          <button class="btn btn-primary" id="newsDigest" type="button">${icon('sparkles')}生成今日摘要</button>
        </div>
      </div>
      <div class="toolbar">
        <div class="tabs" id="newsTabs">
          ${categories.map((item) => `<button class="tab ${item.key === active ? 'active' : ''}" data-cat="${item.key}">${esc(item.label)}</button>`).join('')}
        </div>
        <span class="tiny muted" id="newsMeta"></span>
      </div>
      <div class="toolbar">
        <span class="tiny muted">我的话题</span>
        <div class="chip-row" id="newsTopics">
          ${myTopics.length
            ? myTopics.map((topic) => `<button class="chip" type="button" data-topic="${esc(topic)}">${esc(topic)}</button>`).join('')
            : '<span class="tiny muted">还没有自定义话题，到 <a href="#/me">个人设置</a> 添加，例如「AI」「考研」。</span>'}
        </div>
      </div>
      <div id="digestSlot"></div>
      <div class="card pad-sm" id="newsList">${loadingBlock('正在获取热点…')}</div>
      <p class="tiny muted">热点内容来自第三方媒体，转载与引用请遵循原媒体版权规定；AI 摘要仅作辅助。</p>
    </div>`;
  }

  function bind() {
    el.querySelector('#newsTabs').addEventListener('click', (event) => {
      const button = event.target.closest('[data-cat]');
      if (!button) return;
      active = button.getAttribute('data-cat');
      activeTopic = null;
      digest = null;
      el.querySelectorAll('#newsTabs .tab').forEach((tab) => tab.classList.toggle('active', tab.getAttribute('data-cat') === active));
      el.querySelectorAll('#newsTopics .chip').forEach((chip) => chip.classList.remove('active'));
      renderDigest();
      load(false);
    });
    el.querySelector('#newsTopics').addEventListener('click', (event) => {
      const button = event.target.closest('[data-topic]');
      if (!button) return;
      activeTopic = button.getAttribute('data-topic');
      digest = null;
      el.querySelectorAll('#newsTopics .chip').forEach((chip) => chip.classList.toggle('active', chip === button));
      el.querySelectorAll('#newsTabs .tab').forEach((tab) => tab.classList.remove('active'));
      renderDigest();
      load(false);
    });
    el.querySelector('#newsRefresh').addEventListener('click', () => load(true));
    el.querySelector('#newsDigest').addEventListener('click', () => makeDigest());
  }

  async function load(refresh) {
    const list = el.querySelector('#newsList');
    if (!list) return;
    list.innerHTML = loadingBlock(activeTopic ? `正在查找「${activeTopic}」的话题热点…` : '正在获取热点…');
    const suffix = refresh ? '&refresh=1' : '';
    try {
      feed = activeTopic
        ? await api.get(`/api/news/topic?topic=${encodeURIComponent(activeTopic)}${suffix}`)
        : await api.get(`/api/news?category=${encodeURIComponent(active)}${suffix}`);
      renderList();
    } catch (error) {
      list.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  function renderList() {
    const list = el.querySelector('#newsList');
    if (!list || !feed) return;
    const metaEl = el.querySelector('#newsMeta');
    if (metaEl) metaEl.textContent = `${feed.items.length} 条 · ${feed.cached ? '缓存' : '刚刚更新'} · ${feed.sources.join(' / ')}`;
    if (!feed.items.length) {
      list.innerHTML = emptyState({ iconName: 'news', title: '暂时没有新闻', desc: '稍后再刷新，或换一个分类。' });
      return;
    }
    list.innerHTML = `<div class="list">${feed.items.map((item, index) => {
      const url = safeHttpUrl(item.url);
      return `<div class="news-item">
        <span class="news-rank ${index < 3 ? 'top' : ''}">${index + 1}</span>
        <div class="grow">
          <div class="news-title"><a href="${url}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></div>
          ${item.summary ? `<p class="tiny muted" style="margin-top:4px;line-height:1.6">${esc(item.summary)}</p>` : ''}
          <div class="news-meta"><span>${esc(item.source)}</span><span>·</span><span>${timeAgo(item.published_at)}</span><span class="tag">${esc(feed.label)}</span></div>
        </div>
      </div>`;
    }).join('')}</div>`;
  }

  function renderDigest() {
    const slot = el.querySelector('#digestSlot');
    if (!slot) return;
    if (digestLoading) {
      slot.innerHTML = `<div class="card pad-sm">${loadingBlock('AI 正在阅读今天的新闻…')}</div>`;
      return;
    }
    if (!digest) { slot.innerHTML = ''; return; }
    if (!digest.digest || !String(digest.digest).trim()) {
      slot.innerHTML = `<div class="notice notice-warn">${icon('alert')}<div>模型这次没有返回摘要内容（推理模型容易出现）。请再点一次「生成今日摘要」，或在设置里换成普通对话模型。</div></div>`;
      return;
    }
    slot.innerHTML = `<section class="card pad">
      <div class="section-title">${icon('sparkles')} AI 今日摘要 <span class="spacer"></span><button class="link-btn" id="closeDigest">收起</button></div>
      <div class="digest-box md">${renderMarkdown(digest.digest)}</div>
      <div class="stack-6 mt-16">
        ${digest.sources.map((source) => `<a class="source-chip" href="${safeHttpUrl(source.url)}" target="_blank" rel="noopener noreferrer">
          <span class="n">${source.index}</span><span class="grow"><span class="t">${esc(source.title)}</span><span class="m">${esc(source.source)}</span></span>${icon('external')}
        </a>`).join('')}
      </div>
      <p class="tiny muted mt-10">摘要由模型生成，可能遗漏或误读，请以原文为准。</p>
    </section>`;
    slot.querySelector('#closeDigest').addEventListener('click', () => { digest = null; renderDigest(); });
    typeset(slot);
  }

  async function makeDigest() {
    if (digestLoading) return;
    if (!store.llm.key || !store.llm.model) {
      openKeyPrompt(() => makeDigest());
      return;
    }
    digestLoading = true;
    renderDigest();
    try {
      digest = await api.post('/api/news/digest', activeTopic ? { topic: activeTopic } : { category: active });
      digestLoading = false;
      renderDigest();
    } catch (error) {
      digestLoading = false;
      renderDigest();
      toast(error.message, 'error');
    }
  }
}

/* ------------------------------------------------------------ 论文推荐 */
export async function renderPapers(el, ctx) {
  let direction = (store.user?.directions || [])[0] || '';
  let data = null;
  el.innerHTML = layout();
  bind();
  await load(false);

  function layout() {
    return `<div class="view-page">
      <div class="page-head">
        <div><h2>论文推荐</h2><p>按你的学习方向检索近五年论文，元数据来自 OpenAlex 与 arXiv，链接指向 DOI / 预印本 / 出版商页面。</p></div>
        <div class="page-head-actions">
          <button class="btn btn-ghost" id="paperRefresh" type="button">${icon('refresh')}换一批</button>
        </div>
      </div>
      <div class="card pad-sm">
        <div class="toolbar">
          <input class="input" id="paperDirection" value="${esc(direction)}" placeholder="输入方向，例如：人工智能 / 教育学 / 生态学" maxlength="80">
          <button class="btn btn-primary" id="paperSearch" type="button">${icon('search')}检索</button>
          <span class="tiny muted right">不填则使用个人资料中的学习方向</span>
        </div>
      </div>
      <div id="paperList">${loadingBlock('正在检索论文…')}</div>
      <div class="notice notice-info">${icon('info')}<div>推荐基于公开学术元数据，不保证覆盖所有成果；请通过学校图书馆或 DOI 获取合法全文。点「换一批」可跳过缓存重新检索。</div></div>
    </div>`;
  }

  function bind() {
    el.querySelector('#paperSearch').addEventListener('click', () => {
      direction = el.querySelector('#paperDirection').value.trim();
      load(true);
    });
    el.querySelector('#paperDirection').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { direction = event.currentTarget.value.trim(); load(true); }
    });
    el.querySelector('#paperRefresh').addEventListener('click', () => {
      direction = el.querySelector('#paperDirection').value.trim();
      load(true, true);
    });
  }

  async function load(refresh, force = false) {
    const box = el.querySelector('#paperList');
    if (!box) return;
    box.innerHTML = loadingBlock('正在检索论文…');
    try {
      const query = direction ? `direction=${encodeURIComponent(direction)}` : '';
      data = await api.get(`/api/papers?${query}${refresh ? '&refresh=1' : ''}`);
      render();
    } catch (error) {
      box.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  function render() {
    const box = el.querySelector('#paperList');
    if (!box || !data) return;
    if (!data.papers?.length) {
      box.innerHTML = emptyState({ iconName: 'file', title: '没有找到论文', desc: '换一个更具体的方向词，或在个人资料中补充学习方向。', action: '<a class="btn btn-sm btn-primary" href="#/me">完善学习方向</a>' });
      return;
    }
    box.innerHTML = `<div class="flex-between mb-12">
        <span class="small soft">方向：<strong>${esc(data.direction)}</strong> · 检索词：${esc(data.query)}</span>
        <span class="tag ${data.cached ? '' : 'tag-green'}">${data.cached ? '缓存结果' : '最新检索'}${data.stale ? ' · 离线缓存' : ''}</span>
      </div>
      <div class="stack">
        ${data.papers.map((paper) => {
          const links = [];
          if (paper.doi) links.push(`<a class="btn btn-xs btn-ghost" href="https://doi.org/${encodeURIComponent(paper.doi)}" target="_blank" rel="noopener noreferrer">${icon('external')}DOI</a>`);
          if (paper.oa_url) links.push(`<a class="btn btn-xs btn-ghost" href="${safeHttpUrl(paper.oa_url)}" target="_blank" rel="noopener noreferrer">${icon('file')}开放获取</a>`);
          if (!paper.doi && paper.openalex) links.push(`<a class="btn btn-xs btn-ghost" href="${safeHttpUrl(paper.openalex)}" target="_blank" rel="noopener noreferrer">${icon('external')}OpenAlex</a>`);
          return `<article class="paper-card">
            <div class="paper-title"><a href="${safeHttpUrl(paper.link || paper.oa_url || paper.openalex)}" target="_blank" rel="noopener noreferrer">${esc(paper.title)}</a></div>
            <div class="paper-meta">
              <span>${esc((paper.authors || []).slice(0, 4).join(', ') || '作者未知')}${(paper.authors || []).length > 4 ? ' 等' : ''}</span>
              <span>·</span><span>${esc(paper.year || '')}</span>
              ${paper.venue ? `<span>·</span><span>${esc(paper.venue)}</span>` : ''}
              ${paper.citations ? `<span>·</span><span>被引 ${paper.citations}</span>` : ''}
              <span class="tag">${paper.source === 'arxiv' ? 'arXiv' : 'OpenAlex'}</span>
            </div>
            ${paper.abstract ? `<p class="paper-abstract">${esc(paper.abstract)}</p>` : ''}
            <div class="paper-actions">${links.join('') || '<span class="tiny muted">暂无公开链接</span>'}</div>
          </article>`;
        }).join('')}
      </div>`;
  }
}

/* ------------------------------------------------------------ 学习资料 */
export async function renderStudy(el, ctx) {
  let data = null;
  el.innerHTML = layout();
  bind();
  await load(false);

  function layout() {
    return `<div class="view-page">
      <div class="page-head">
        <div><h2>学习资料</h2><p>根据你的年级、课程和学习方向，推荐 B 站、小红书、抖音、知乎、中国大学 MOOC 与论文。所有内容跳转到平台站内搜索。</p></div>
        <div class="page-head-actions">
          <button class="btn btn-ghost" id="studyRefresh" type="button">${icon('refresh')}换一批</button>
          <button class="btn btn-primary" id="studyAI" type="button">${icon('sparkles')}AI 定制</button>
        </div>
      </div>
      <div id="studyProfile"></div>
      <div id="studyLive"></div>
      <div id="studyList">${skeleton()}</div>      <div id="studyPapers"></div>
      <p class="tiny muted">平台搜索链接由关键词生成，具体内容由平台提供；请遵守各平台规则与版权要求，优先使用正版课程与开放获取论文。</p>
    </div>`;
  }

  function bind() {
    el.querySelector('#studyRefresh').addEventListener('click', () => load(true));
    el.querySelector('#studyAI').addEventListener('click', () => {
      if (!store.llm.key || !store.llm.model) { openKeyPrompt(() => load(true)); return; }
      load(true);
    });
  }

  function skeleton() {
    return `<div class="stack">
      <div class="skeleton" style="height:26px;width:180px"></div>
      <div class="grid grid-2">
        <div class="skeleton" style="height:118px"></div>
        <div class="skeleton" style="height:118px"></div>
        <div class="skeleton" style="height:118px"></div>
        <div class="skeleton" style="height:118px"></div>
      </div>
    </div>`;
  }

  async function load(refresh) {
    const box = el.querySelector('#studyList');
    if (!box) return;
    box.innerHTML = skeleton();
    try {
      data = await api.get(`/api/study?${refresh ? 'refresh=1' : ''}`);
      render();
    } catch (error) {
      box.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  function render() {
    if (!data) return;
    const user = store.user || {};
    const profile = el.querySelector('#studyProfile');
    const missing = !user.grade && !(user.courses || []).length && !(user.directions || []).length;
    profile.innerHTML = missing ? `<div class="notice notice-warn">${icon('alert')}<div>完善年级、课程和学习方向后，推荐会更贴合。当前使用通用推荐。<a href="#/me">去完善资料</a></div></div>` : '';

    // 真实可点的视频 / 图文：按公开播放量、浏览量排序
    const live = data.live || {};
    const liveBox = el.querySelector('#studyLive');
    const rows = [
      { label: '视频', iconName: 'play', items: live.videos || [], hint: '按播放量排序' },
      { label: '图文 / 专栏', iconName: 'note', items: live.docs || [], hint: '按浏览量排序' }
    ].filter((row) => row.items.length);
    if (rows.length) {
      liveBox.innerHTML = `<section class="card pad">
        <div class="section-title">${icon('sparkles')} 直接点开：${esc((data.live.queries || [])[0] || '相关推荐')}
          <span class="spacer"></span><span class="tiny muted">${live.mode === 'live' ? '公开数据实时排序' : '站内检索'}</span></div>
        ${rows.map((row) => `<div class="stack-6">
          <div class="tiny muted" style="margin-top:8px">${icon(row.iconName)} ${row.label} · ${row.hint}</div>
          ${row.items.map((item) => `<a class="live-item" href="${safeHttpUrl(item.url)}" target="_blank" rel="noopener noreferrer">
            <span class="live-title">${esc(item.title)}</span>
            <span class="live-meta">${esc(item.count_label || '')}${item.author ? ` · ${esc(item.author)}` : ''}${icon('external')}</span>
          </a>`).join('')}
        </div>`).join('')}
        ${(live.searches || []).length ? `<div class="flex wrap mt-12" style="gap:8px">
          ${live.searches.map((item) => `<a class="btn btn-xs btn-ghost" href="${safeHttpUrl(item.url)}" target="_blank" rel="noopener noreferrer">${icon('search')}在 B 站搜「${esc(item.query)}」</a>`).join('')}
        </div>` : ''}
        <p class="tiny muted mt-12">${esc(live.note || '链接直达平台，内容由平台提供。')}</p>
        <p class="tiny muted mt-6">如果打开 B 站提示 412，是 B 站的风控（不是应用出错），稍等几分钟或点上面的搜索链接即可。</p>
      </section>`;
    } else {
      liveBox.innerHTML = '';
    }
    const box = el.querySelector('#studyList');
    if (!data.items?.length) {
      box.innerHTML = emptyState({ iconName: 'book', title: '暂时没有推荐', desc: '稍后重试或完善个人资料。' });
    } else {
      box.innerHTML = `<div class="flex-between mb-12">
        <span class="small soft">${data.mode === 'ai' ? '由 AI 根据你的资料定制' : '基于年级与课程生成的通用推荐'}${data.cached ? '（缓存）' : ''}</span>
        <span class="tag">${data.items.length} 条</span>
      </div>
      <div class="grid grid-auto">${data.items.map((item) => `
        <article class="resource-card" style="--tone:${item.tone || '#14a3a0'}">
          <div class="resource-platform"><span class="p-dot"></span>${esc(item.platform_label)}</div>
          <div class="resource-title">${esc(item.title)}</div>
          <div class="resource-reason">${esc(item.reason)}</div>
          <a class="resource-link" href="${safeHttpUrl(item.url)}" target="_blank" rel="noopener noreferrer">去 ${esc(item.platform_label)} 搜索「${esc(item.query)}」${icon('external')}</a>
        </article>`).join('')}</div>`;
    }
    const papersBox = el.querySelector('#studyPapers');
    if (data.papers?.length) {
      papersBox.innerHTML = `<section class="card pad">
        <div class="section-title">${icon('file')} 与你方向相关的论文</div>
        <div class="stack">
          ${data.papers.map((paper) => `<div class="paper-card" style="box-shadow:none">
            <div class="paper-title"><a href="${safeHttpUrl(paper.link || paper.oa_url || paper.openalex)}" target="_blank" rel="noopener noreferrer">${esc(paper.title)}</a></div>
            <div class="paper-meta"><span>${esc((paper.authors || []).slice(0, 3).join(', '))}</span><span>·</span><span>${esc(paper.year || '')}</span><span>·</span><span>${esc(paper.venue || '')}</span></div>
          </div>`).join('')}
        </div>
      </section>`;
    } else {
      papersBox.innerHTML = '';
    }
  }
}
