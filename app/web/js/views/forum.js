import { api } from '../api.js';
import { store } from '../store.js';
import {
  icon, esc, avatar, toast, openModal, confirmDialog, loadingBlock, emptyState,
  statusBadge, timeAgo, fmtDateTime, safeHttpUrl
} from '../ui.js';

const TAGS_FALLBACK = [
  { key: '经验分享', desc: '选课、竞赛、保研与实习经验' },
  { key: '生活分享', desc: '食堂、宿舍、社团与日常' },
  { key: '寻物启事', desc: '失物招领与寻物' },
  { key: '学习交流', desc: '课程、作业与学术讨论' }
];

function tagMeta(key) {
  const list = (store.meta && store.meta.forum_tags) || TAGS_FALLBACK;
  return list.find((item) => item.key === key) || { key, desc: '' };
}

function authorHtml(author, mine = false) {
  const nickname = author?.nickname || '已注销用户';
  const anon = author?.is_anonymous && !nickname.startsWith('匿名') ? '<span class="tag">匿名</span>' : '';
  const mineTag = mine ? '<span class="tag tag-teal">我的</span>' : '';
  return `<span class="post-author">${avatar(author || { nickname: '已注销用户', avatar: 'preset:ghost' }, 'xs')}
    <strong>${esc(nickname)}</strong>${anon}${mineTag}</span>`;
}

function postCard(post) {
  const tags = (post.tags || []).map((tag) => `<a class="tag tag-navy" href="#/forum?tag=${encodeURIComponent(tag)}">${esc(tag)}</a>`).join('');
  return `<article class="post-card" data-post="${post.id}">
    <div class="post-top">
      ${authorHtml(post.author, post.mine)}
      <span>·</span><span>${timeAgo(post.created_at)}</span>
      ${post.status !== 'visible' ? statusBadge(post.status) : ''}
      <span class="right"></span>
      ${tags}
    </div>
    <h3 class="post-title"><a href="#/forum/${post.id}">${esc(post.title)}</a></h3>
    <p class="post-excerpt">${esc(post.body).replace(/\n/g, ' ')}</p>
    <div class="post-foot">
      <button class="link-btn ${post.liked ? 'link-danger' : ''}" type="button" data-like="${post.id}">${icon('heart')} <span data-like-count="${post.id}">${post.likes}</span></button>
      <a class="stat-link" href="#/forum/${post.id}">${icon('message')} ${post.comments}</a>
      <span>${icon('eye')} ${post.views}</span>
      <button class="link-btn ${post.bookmarked ? 'link-danger' : ''}" type="button" data-bookmark="${post.id}">${icon('bookmark')} ${post.bookmarked ? '已收藏' : '收藏'}</button>
      ${post.mine ? `<a class="link-btn" href="#/forum/${post.id}">管理</a>` : ''}
    </div>
  </article>`;
}

function guidelinesCard() {
  return `<div class="card pad-sm">
    <div class="section-title">${icon('shield')} 社区规范</div>
    <ul class="tiny muted" style="padding-left:16px;line-height:1.9;margin:0">
      <li>友善交流，不发布色情低俗、暴力、诈骗或违法内容。</li>
      <li>匿名发帖只对其他同学隐藏身份，管理员仍可追溯违规。</li>
      <li>发现不良内容请举报；被误判可提交申诉。</li>
      <li>请勿公开他人手机号、身份证号等隐私信息。</li>
    </ul>
  </div>`;
}

function reportDialog(targetType, targetId, label) {
  const reasons = (store.meta && store.meta.report_reasons) || ['色情低俗', '暴力血腥', '违法违规', '诈骗广告', '人身攻击', '隐私泄露', '其他'];
  openModal({
    title: `举报${label}`,
    body: `<div class="stack">
      <div class="field"><label for="reportReason">原因</label>
        <select class="select" id="reportReason">${reasons.map((reason) => `<option value="${reason}">${reason}</option>`).join('')}</select>
      </div>
      <div class="field"><label for="reportDetail">补充说明（可选）</label>
        <textarea class="textarea" id="reportDetail" maxlength="500" rows="3" placeholder="请描述具体问题，帮助管理员判断。"></textarea>
      </div>
      <div class="notice notice-warn">${icon('alert')}<div>恶意举报可能影响你的账号。举报会提交给管理员审核。</div></div>
    </div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger" id="submitReport">提交举报</button>`,
    onMount: (root, close) => {
      root.querySelector('#submitReport').addEventListener('click', async () => {
        try {
          await api.post('/api/forum/reports', {
            target_type: targetType,
            target_id: Number(targetId),
            reason: root.querySelector('#reportReason').value,
            detail: root.querySelector('#reportDetail').value.trim()
          });
          close();
          toast('举报已提交，管理员会尽快处理', 'success');
        } catch (error) { toast(error.message, 'error'); }
      });
    }
  });
}

function appealDialog(targetType, targetId) {
  openModal({
    title: '提交申诉',
    body: `<div class="field"><label for="appealReason">说明情况</label>
      <textarea class="textarea" id="appealReason" maxlength="500" rows="4" placeholder="请说明内容为什么应当恢复，至少 5 个字。"></textarea></div>
      <div class="notice notice-info mt-10">${icon('info')}<div>申诉会由管理员人工处理。处理结果会通过站内通知告知。</div></div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="submitAppeal">提交申诉</button>`,
    onMount: (root, close) => {
      root.querySelector('#submitAppeal').addEventListener('click', async () => {
        const reason = root.querySelector('#appealReason').value.trim();
        if (reason.length < 5) { toast('请至少写 5 个字说明情况', 'warn'); return; }
        try {
          await api.post('/api/forum/appeals', { target_type: targetType, target_id: Number(targetId), reason });
          close();
          toast('申诉已提交', 'success');
        } catch (error) { toast(error.message, 'error'); }
      });
    }
  });
}

/* ------------------------------------------------------------ 列表 */
export async function renderForumList(el, ctx) {
  const state = { tag: ctx.query?.get('tag') || '', sort: 'new', q: '', page: 1, size: 10, data: null };
  el.innerHTML = loadingBlock('正在打开论坛…');
  await load(true);

  async function load(reset = false) {
    if (reset) state.page = 1;
    const params = new URLSearchParams({
      sort: state.sort,
      page: String(state.page),
      size: String(state.size)
    });
    if (state.tag) params.set('tag', state.tag);
    if (state.q) params.set('q', state.q);
    const data = await api.get(`/api/forum/posts?${params.toString()}`);
    if (reset) state.data = data;
    else {
      state.data.items = [...state.data.items, ...data.items];
      state.data.has_more = data.has_more;
      state.data.total = data.total;
      state.data.tags = data.tags;
    }
    render();
  }

  function postsHtml() {
    if (!state.data.items.length) {
      return emptyState({
        iconName: 'users', title: '这里还没有帖子',
        desc: state.tag || state.q ? '换个关键词或标签试试，也可以发第一条帖子。' : '分享一条经验、一则生活片段，或者发个寻物启事。',
        action: '<a class="btn btn-primary" href="#/forum/new">发布帖子</a>'
      });
    }
    return `<div class="stack">${state.data.items.map(postCard).join('')}</div>
      ${state.data.has_more ? `<div class="text-center mt-16"><button class="btn btn-ghost" id="loadMore" type="button">加载更多</button></div>` : ''}`;
  }

  function render() {
    const tags = (store.meta?.forum_tags) || TAGS_FALLBACK;
    el.innerHTML = `<div class="view-page">
      <div class="page-head">
        <div><h2>校园论坛</h2><p>经验、生活、寻物与学习交流。支持匿名发帖、评论、私信与关注；内容会经过规则与 AI 预审。</p></div>
        <div class="page-head-actions"><a class="btn btn-primary" href="#/forum/new">${icon('plus')}发布帖子</a></div>
      </div>
      <div class="forum-layout">
        <div class="stack">
          <div class="toolbar">
            <div class="segmented" id="forumSort">
              <button data-sort="new" class="${state.sort === 'new' ? 'active' : ''}">最新</button>
              <button data-sort="hot" class="${state.sort === 'hot' ? 'active' : ''}">热门</button>
              <button data-sort="following" class="${state.sort === 'following' ? 'active' : ''}">关注</button>
            </div>
            <input class="input input-sm" id="forumSearch" placeholder="搜索帖子标题或内容" value="${esc(state.q)}" style="max-width:260px">
            <span class="tiny muted right">${state.data.total} 条帖子</span>
          </div>
          <div class="chip-row">
            <button class="chip ${!state.tag ? 'active' : ''}" data-tag="">全部</button>
            ${tags.map((tag) => {
              const count = (state.data.tags || []).find((item) => item.key === tag.key)?.count || 0;
              return `<button class="chip ${state.tag === tag.key ? 'active' : ''}" data-tag="${esc(tag.key)}">${esc(tag.key)} <span class="count">${count}</span></button>`;
            }).join('')}
          </div>
          ${postsHtml()}
        </div>
        <aside class="forum-side">
          <div class="card pad-sm">
            <div class="section-title">${icon('users')} 版块</div>
            <div class="tag-list">
              ${tags.map((tag) => {
                const count = (state.data.tags || []).find((item) => item.key === tag.key)?.count || 0;
                return `<button class="tag-row" data-tag="${esc(tag.key)}"><span>${esc(tag.key)}<span class="tiny muted" style="display:block;font-weight:400">${esc(tag.desc || '')}</span></span><span class="count">${count}</span></button>`;
              }).join('')}
            </div>
          </div>
          ${guidelinesCard()}
          <div class="card pad-sm">
            <div class="section-title">${icon('user')} 我的社区</div>
            <a class="btn btn-sm btn-ghost btn-block" href="#/forum/user/${store.user.id}">查看我的主页</a>
            <a class="btn btn-sm btn-ghost btn-block mt-6" href="#/messages">私信</a>
          </div>
        </aside>
      </div>
    </div>`;
    bind();
  }

  function bind() {
    el.querySelectorAll('#forumSort [data-sort]').forEach((button) => {
      button.addEventListener('click', () => {
        state.sort = button.getAttribute('data-sort');
        load(true).catch((error) => toast(error.message, 'error'));
      });
    });
    el.querySelectorAll('[data-tag]').forEach((button) => {
      button.addEventListener('click', () => {
        state.tag = button.getAttribute('data-tag');
        load(true).catch((error) => toast(error.message, 'error'));
      });
    });
    const input = el.querySelector('#forumSearch');
    input?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        state.q = event.currentTarget.value.trim();
        load(true).catch((error) => toast(error.message, 'error'));
      }
    });
    el.querySelector('#loadMore')?.addEventListener('click', () => {
      state.page += 1;
      load(false).catch((error) => toast(error.message, 'error'));
    });
    bindQuickActions(el);
  }

  function bindQuickActions(root) {
    root.querySelectorAll('[data-like]').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          const result = await api.post(`/api/forum/posts/${button.getAttribute('data-like')}/like`);
          button.classList.toggle('link-danger', result.liked);
          const counter = root.querySelector(`[data-like-count="${button.getAttribute('data-like')}"]`);
          if (counter) counter.textContent = result.count;
          const post = state.data.items.find((item) => String(item.id) === button.getAttribute('data-like'));
          if (post) { post.liked = result.liked; post.likes = result.count; }
        } catch (error) { toast(error.message, 'error'); }
      });
    });
    root.querySelectorAll('[data-bookmark]').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          const result = await api.post(`/api/forum/posts/${button.getAttribute('data-bookmark')}/bookmark`);
          button.classList.toggle('link-danger', result.bookmarked);
          button.lastChild.textContent = result.bookmarked ? ' 已收藏' : ' 收藏';
          const post = state.data.items.find((item) => String(item.id) === button.getAttribute('data-bookmark'));
          if (post) post.bookmarked = result.bookmarked;
        } catch (error) { toast(error.message, 'error'); }
      });
    });
  }
}

/* ------------------------------------------------------------ 详情 */
export async function renderForumPost(el, ctx) {
  const postId = Number(ctx.params[0]);
  el.innerHTML = loadingBlock('正在加载帖子…');
  let post = null;
  let comments = [];
  let replyTo = null;

  const load = async () => {
    const data = await api.get(`/api/forum/posts/${postId}`);
    post = data.post;
    comments = data.comments || [];
    render();
  };

  function commentHtml(comment) {
    const parent = comment.parent_id ? comments.find((item) => item.id === comment.parent_id) : null;
    const isReply = !!comment.parent_id;
    return `<div class="comment ${isReply ? 'comment-reply' : ''}" data-comment="${comment.id}">
      ${avatar(comment.author, 'sm')}
      <div class="comment-body">
        <div class="comment-meta">
          <strong>${esc(comment.author?.nickname || '已注销用户')}</strong>
          ${comment.author?.is_anonymous ? '<span class="tag">匿名</span>' : ''}
          ${comment.mine ? '<span class="tag tag-teal">我的</span>' : ''}
          <span>${timeAgo(comment.created_at)}</span>
          ${isReply && parent ? `<span>回复 ${esc(parent.author?.nickname || '')}</span>` : ''}
          ${comment.status !== 'visible' ? statusBadge(comment.status) : ''}
        </div>
        <div class="comment-text">${esc(comment.body)}</div>
        <div class="comment-actions">
          <button type="button" data-like-comment="${comment.id}">${icon('heart')} ${comment.likes}</button>
          ${post.status === 'visible' ? `<button type="button" data-reply="${comment.id}">回复</button>` : ''}
          ${comment.mine || store.user.is_admin ? `<button type="button" data-delete-comment="${comment.id}">删除</button>` : ''}
          ${!comment.mine ? `<button type="button" data-report-comment="${comment.id}">举报</button>` : ''}
        </div>
      </div>
    </div>`;
  }

  function render() {
    const tags = (post.tags || []).map((tag) => `<span class="tag tag-navy">${esc(tag)}</span>`).join('');
    const isMine = post.mine;
    el.innerHTML = `<div class="view-page">
      <div class="flex"><a class="btn btn-sm btn-ghost" href="#/forum">${icon('arrowLeft')}返回论坛</a>
        <span class="right tiny muted">${timeAgo(post.created_at)}发布 · ${post.views} 次浏览</span></div>
      <div class="forum-layout">
        <div class="stack">
          <article class="card pad post-detail">
            <div class="flex-between wrap">
              <div class="post-author">${avatar(post.author, 'md')}
                <div><strong>${esc(post.author?.nickname || '已注销用户')}</strong>
                  <div class="tiny muted">${fmtDateTime(post.created_at, true)} · ${post.author?.is_anonymous ? '匿名发布' : '发布于校园论坛'}</div>
                </div>
              </div>
              <div class="chip-row">${tags}${post.status !== 'visible' ? statusBadge(post.status) : ''}</div>
            </div>
            <h2 style="font-size:23px;letter-spacing:-.02em">${esc(post.title)}</h2>
            <div class="post-detail-body">${esc(post.body)}</div>
            ${post.status !== 'visible' ? `<div class="notice notice-warn">${icon('alert')}<div>这篇帖子正在审核或被限制展示。只有你和管理员可以看到。${post.status !== 'removed' ? '<button class="link-btn" id="appealBtn">提交申诉</button>' : ''}</div></div>` : ''}
            <div class="flex wrap" style="gap:8px">
              <button class="btn btn-sm ${post.liked ? 'btn-soft' : 'btn-ghost'}" id="likePost" type="button">${icon('heart')} ${post.liked ? '已赞' : '点赞'} <span id="likeCount">${post.likes}</span></button>
              <button class="btn btn-sm ${post.bookmarked ? 'btn-soft' : 'btn-ghost'}" id="bookmarkPost" type="button">${icon('bookmark')} ${post.bookmarked ? '已收藏' : '收藏'}</button>
              ${!isMine && post.author?.id ? `<a class="btn btn-sm btn-ghost" href="#/messages/${post.author.id}">${icon('message')}私信作者</a>` : ''}
              ${!isMine ? `<button class="btn btn-sm btn-ghost" id="reportPost" type="button">${icon('flag')}举报</button>` : ''}
              ${isMine ? `<button class="btn btn-sm btn-ghost" id="editPost" type="button">${icon('edit')}编辑</button>
                <button class="btn btn-sm btn-ghost link-danger" id="deletePost" type="button">${icon('trash')}删除</button>` : ''}
            </div>
          </article>

          <section class="card pad">
            <div class="section-title">${icon('message')} 评论 <span class="spacer"></span><span class="tiny muted">${comments.filter((c) => c.status === 'visible').length} 条</span></div>
            ${post.status === 'visible' ? `<div class="stack mb-16">
              <textarea class="textarea" id="commentBody" maxlength="2000" rows="3" placeholder="友善交流，写下你的想法…"></textarea>
              <div class="flex-between wrap">
                <label class="check" style="padding:6px 10px"><input type="checkbox" id="commentAnonymous"><span class="small">匿名评论</span></label>
                <div class="flex"><span class="tiny muted" id="replyHint"></span><button class="btn btn-primary" id="submitComment" type="button">发布评论</button></div>
              </div>
            </div>` : `<div class="notice notice-warn mb-16">${icon('alert')}<div>帖子审核期间暂不能评论。</div></div>`}
            <div id="commentsList">${comments.length ? comments.map(commentHtml).join('') : emptyState({ iconName: 'message', title: '还没有评论', desc: '做第一个回复的人。' })}</div>
          </section>
        </div>
        <aside class="forum-side">
          <div class="card pad-sm">
            <div class="section-title">${icon('user')} 作者</div>
            <div class="flex">${avatar(post.author, 'md')}
              <div><strong>${esc(post.author?.nickname || '已注销用户')}</strong>
                <div class="tiny muted">${post.author?.is_anonymous ? '匿名发布者' : (post.author?.id ? '校园成员' : '已注销')}</div></div>
            </div>
            ${post.author?.id ? `<a class="btn btn-sm btn-ghost btn-block mt-10" href="#/forum/user/${post.author.id}">查看主页</a>` : ''}
          </div>
          ${guidelinesCard()}
        </aside>
      </div>
    </div>`;
    bind();
  }

  function bind() {
    el.querySelector('#likePost')?.addEventListener('click', async () => {
      try {
        const result = await api.post(`/api/forum/posts/${postId}/like`);
        post.liked = result.liked; post.likes = result.count;
        el.querySelector('#likeCount').textContent = result.count;
        el.querySelector('#likePost').classList.toggle('btn-soft', result.liked);
        el.querySelector('#likePost').innerHTML = `${icon('heart')} ${result.liked ? '已赞' : '点赞'} <span id="likeCount">${result.count}</span>`;
      } catch (error) { toast(error.message, 'error'); }
    });
    el.querySelector('#bookmarkPost')?.addEventListener('click', async () => {
      try {
        const result = await api.post(`/api/forum/posts/${postId}/bookmark`);
        post.bookmarked = result.bookmarked;
        const button = el.querySelector('#bookmarkPost');
        button.classList.toggle('btn-soft', result.bookmarked);
        button.innerHTML = `${icon('bookmark')} ${result.bookmarked ? '已收藏' : '收藏'}`;
      } catch (error) { toast(error.message, 'error'); }
    });
    el.querySelector('#reportPost')?.addEventListener('click', () => reportDialog('post', postId, '帖子'));
    el.querySelector('#appealBtn')?.addEventListener('click', () => appealDialog('post', postId));
    el.querySelector('#deletePost')?.addEventListener('click', async () => {
      const ok = await confirmDialog('删除帖子', '确定删除这篇帖子吗？删除后不可恢复。', { danger: true, confirmText: '删除' });
      if (!ok) return;
      try {
        await api.del(`/api/forum/posts/${postId}`);
        toast('帖子已删除', 'success');
        window.location.hash = '#/forum';
      } catch (error) { toast(error.message, 'error'); }
    });
    el.querySelector('#editPost')?.addEventListener('click', openEdit);
    el.querySelector('#submitComment')?.addEventListener('click', submitComment);
    el.querySelectorAll('[data-like-comment]').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          const result = await api.post(`/api/forum/comments/${button.getAttribute('data-like-comment')}/like`);
          const comment = comments.find((item) => String(item.id) === button.getAttribute('data-like-comment'));
          if (comment) comment.likes = result.count;
          button.innerHTML = `${icon('heart')} ${result.count}`;
          button.classList.toggle('link-danger', result.liked);
        } catch (error) { toast(error.message, 'error'); }
      });
    });
    el.querySelectorAll('[data-reply]').forEach((button) => {
      button.addEventListener('click', () => {
        const comment = comments.find((item) => String(item.id) === button.getAttribute('data-reply'));
        replyTo = comment ? { id: comment.id, name: comment.author?.nickname || '匿名同学' } : null;
        const hint = el.querySelector('#replyHint');
        if (hint) hint.textContent = replyTo ? `正在回复 ${replyTo.name}` : '';
        el.querySelector('#commentBody')?.focus();
      });
    });
    el.querySelectorAll('[data-delete-comment]').forEach((button) => {
      button.addEventListener('click', async () => {
        const ok = await confirmDialog('删除评论', '确定删除这条评论吗？', { danger: true, confirmText: '删除' });
        if (!ok) return;
        try {
          await api.del(`/api/forum/comments/${button.getAttribute('data-delete-comment')}`);
          toast('评论已删除', 'success');
          await load();
        } catch (error) { toast(error.message, 'error'); }
      });
    });
    el.querySelectorAll('[data-report-comment]').forEach((button) => {
      button.addEventListener('click', () => reportDialog('comment', button.getAttribute('data-report-comment'), '评论'));
    });
  }

  async function submitComment() {
    const body = el.querySelector('#commentBody').value.trim();
    if (!body) { toast('评论不能为空', 'warn'); return; }
    const anonymous = el.querySelector('#commentAnonymous').checked;
    try {
      const result = await api.post(`/api/forum/posts/${postId}/comments`, {
        body, anonymous, parent_id: replyTo?.id || null
      });
      toast(result.message || '评论已发布', result.comment?.status === 'visible' ? 'success' : 'warn', 4500);
      replyTo = null;
      await load();
    } catch (error) { toast(error.message, 'error'); }
  }

  function openEdit() {
    const tags = (store.meta?.forum_tags) || TAGS_FALLBACK;
    openModal({
      title: '编辑帖子',
      body: `<div class="stack">
        <div class="field"><label for="editTitle">标题</label><input class="input" id="editTitle" maxlength="80" value="${esc(post.title)}"></div>
        <div class="field"><span class="field-label">标签</span><div class="chip-row">${tags.map((tag) => `<label class="chip" style="cursor:pointer"><input type="checkbox" name="editTag" value="${esc(tag.key)}" ${post.tags.includes(tag.key) ? 'checked' : ''} style="accent-color:var(--teal-500)"> ${esc(tag.key)}</label>`).join('')}</div></div>
        <div class="field"><label for="editBody">正文</label><textarea class="textarea" id="editBody" rows="8" maxlength="8000">${esc(post.body)}</textarea></div>
        <label class="check"><input type="checkbox" id="editAnonymous" ${post.anonymous ? 'checked' : ''}><span><span class="check-title">匿名显示</span><span class="check-desc">其他用户将看到匿名昵称</span></span></label>
      </div>`,
      footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="saveEdit">保存</button>`,
      onMount: (root, close) => {
        root.querySelector('#saveEdit').addEventListener('click', async () => {
          const selected = Array.from(root.querySelectorAll('input[name=editTag]:checked')).map((input) => input.value);
          if (!selected.length) { toast('请至少选择一个标签', 'warn'); return; }
          try {
            const result = await api.patch(`/api/forum/posts/${postId}`, {
              title: root.querySelector('#editTitle').value.trim(),
              body: root.querySelector('#editBody').value.trim(),
              tags: selected,
              anonymous: root.querySelector('#editAnonymous').checked
            });
            close();
            toast(result.message || '已保存', 'success');
            await load();
          } catch (error) { toast(error.message, 'error'); }
        });
      }
    });
  }

  await load();
}

/* ------------------------------------------------------------ 发帖 */
export async function renderForumNew(el, ctx) {
  const tags = (store.meta?.forum_tags) || TAGS_FALLBACK;
  el.innerHTML = `<div class="view-page">
    <div class="flex"><a class="btn btn-sm btn-ghost" href="#/forum">${icon('arrowLeft')}返回论坛</a></div>
    <div class="grid grid-main-side">
      <section class="card pad">
        <div class="page-head" style="margin-bottom:18px"><div><h2>发布帖子</h2><p>分享经验、生活、寻物或学习问题。发布后可能需要短暂审核。</p></div></div>
        <form id="postForm" class="stack">
          <div class="field"><label for="postTitle">标题</label><input class="input" id="postTitle" maxlength="80" required placeholder="一句话说明你想聊什么"></div>
          <div class="field"><span class="field-label">选择标签（1-3 个）</span>
            <div class="chip-row">${tags.map((tag) => `<label class="chip" style="cursor:pointer"><input type="checkbox" name="tag" value="${esc(tag.key)}" style="accent-color:var(--teal-500)"> ${esc(tag.key)}</label>`).join('')}</div>
            <span class="hint">${esc(tags.map((tag) => `${tag.key}：${tag.desc}`).join('；'))}</span>
          </div>
          <div class="field"><label for="postBody">正文</label><textarea class="textarea" id="postBody" rows="10" maxlength="8000" required placeholder="把话说清楚：背景、你的问题或想分享的内容。"></textarea></div>
          <label class="check"><input type="checkbox" id="postAnonymous"><span><span class="check-title">匿名发布</span><span class="check-desc">其他同学只会看到「匿名同学·编号」；管理员仍可追溯违规内容。</span></span></label>
          <div class="flex"><span class="tiny muted">发布前请阅读社区规范，不要包含手机号、身份证号等隐私。</span>
            <button class="btn btn-primary right" type="submit" id="publishBtn">${icon('send')}发布</button></div>
        </form>
      </section>
      <aside class="stack">${guidelinesCard()}
        <div class="card pad-sm"><div class="section-title">${icon('info')} 审核说明</div>
          <p class="tiny muted" style="line-height:1.8">系统会先做规则筛查，配置了 AI 审核时再做一次语义复核。命中风险的内容会进入人工审核队列；如判断有误，可提交申诉。</p>
        </div>
      </aside>
    </div>
  </div>`;
  el.querySelector('#postForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const selected = Array.from(el.querySelectorAll('input[name=tag]:checked')).map((input) => input.value);
    if (!selected.length) { toast('请至少选择一个标签', 'warn'); return; }
    const title = el.querySelector('#postTitle').value.trim();
    const body = el.querySelector('#postBody').value.trim();
    if (title.length < 4) { toast('标题至少 4 个字', 'warn'); return; }
    if (!body) { toast('正文不能为空', 'warn'); return; }
    const button = el.querySelector('#publishBtn');
    button.disabled = true;
    try {
      const result = await api.post('/api/forum/posts', {
        title,
        body,
        tags: selected,
        anonymous: el.querySelector('#postAnonymous').checked
      });
      toast(result.message || '发布成功', 'success', 4500);
      window.location.hash = `#/forum/${result.post.id}`;
    } catch (error) {
      toast(error.message, 'error');
      button.disabled = false;
    }
  });
  el.querySelector('#postTitle').focus();
}

/* ------------------------------------------------------------ 用户主页 */
export async function renderForumUser(el, ctx) {
  const userId = Number(ctx.params[0]);
  el.innerHTML = loadingBlock('正在打开主页…');
  let data = null;

  const load = async () => {
    data = await api.get(`/api/forum/users/${userId}`);
    render();
  };

  function render() {
    const user = data.user;
    const stats = data.stats;
    el.innerHTML = `<div class="view-page">
      <div class="flex"><a class="btn btn-sm btn-ghost" href="#/forum">${icon('arrowLeft')}返回论坛</a></div>
      <section class="user-hero">
        ${avatar(user, 'xl', 'avatar-ring')}
        <div class="grow">
          <div class="user-name">${esc(user.nickname)}${user.role === 'admin' ? ' <span class="tag tag-amber">管理员</span>' : ''}</div>
          <div class="user-bio">${esc(user.bio || '这位同学还没有写简介。')}</div>
          <div class="flex wrap mt-10 tiny muted">
            ${user.department ? `<span class="tag">${esc(user.department)}</span>` : ''}
            ${user.major ? `<span class="tag">${esc(user.major)}</span>` : ''}
            ${user.grade ? `<span class="tag">${esc(user.grade)}</span>` : ''}
            ${(user.directions || []).map((direction) => `<span class="tag tag-teal">${esc(direction)}</span>`).join('')}
            <span>加入于 ${esc((user.created_at || '').slice(0, 10))}</span>
          </div>
          <div class="user-stats">
            <div><strong>${stats.posts}</strong><span>帖子</span></div>
            <div><strong>${stats.followers}</strong><span>关注者</span></div>
            <div><strong>${stats.following}</strong><span>正在关注</span></div>
          </div>
        </div>
        <div class="stack">
          ${!user.is_self ? `<button class="btn ${user.is_following ? 'btn-ghost' : 'btn-primary'}" id="followBtn" type="button">${user.is_following ? '已关注' : icon('plus') + '关注'}</button>
            <a class="btn btn-ghost" href="#/messages/${user.id}">${icon('message')}发私信</a>` : `<a class="btn btn-primary" href="#/me">${icon('settings')}编辑资料</a>`}
        </div>
      </section>
      <div class="grid grid-main-side">
        <section class="card pad">
          <div class="section-title">${icon('note')} 公开帖子</div>
          ${data.posts.length ? `<div class="stack">${data.posts.map(postCard).join('')}</div>` : emptyState({ iconName: 'note', title: '还没有公开帖子', desc: '发一条帖子，让同学认识你。', action: user.is_self ? '<a class="btn btn-primary" href="#/forum/new">去发帖</a>' : '' })}
        </section>
        <aside class="stack">
          <div class="card pad-sm">
            <div class="section-title">${icon('users')} 关注者</div>
            <button class="btn btn-sm btn-ghost btn-block" id="followersBtn" type="button">查看关注者（${stats.followers}）</button>
            <button class="btn btn-sm btn-ghost btn-block mt-6" id="followingBtn" type="button">查看正在关注（${stats.following}）</button>
          </div>
          ${guidelinesCard()}
        </aside>
      </div>
    </div>`;
    bind();
  }

  function bind() {
    el.querySelector('#followBtn')?.addEventListener('click', async () => {
      try {
        const result = await api.post(`/api/forum/users/${userId}/follow`);
        toast(result.following ? '已关注' : '已取消关注', 'success');
        await load();
      } catch (error) { toast(error.message, 'error'); }
    });
    el.querySelector('#followersBtn')?.addEventListener('click', () => openPeople('关注者'));
    el.querySelector('#followingBtn')?.addEventListener('click', () => openPeople('正在关注'));
    bindPostActions();
  }

  function bindPostActions() {
    el.querySelectorAll('[data-like]').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          const result = await api.post(`/api/forum/posts/${button.getAttribute('data-like')}/like`);
          button.classList.toggle('link-danger', result.liked);
          const counter = el.querySelector(`[data-like-count="${button.getAttribute('data-like')}"]`);
          if (counter) counter.textContent = result.count;
        } catch (error) { toast(error.message, 'error'); }
      });
    });
    el.querySelectorAll('[data-bookmark]').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          const result = await api.post(`/api/forum/posts/${button.getAttribute('data-bookmark')}/bookmark`);
          button.classList.toggle('link-danger', result.bookmarked);
        } catch (error) { toast(error.message, 'error'); }
      });
    });
  }

  async function openPeople(kind) {
    const endpoint = kind === '关注者' ? 'followers' : 'following';
    const modal = openModal({
      title: `${kind} · ${data.user.nickname}`,
      body: loadingBlock('正在加载…'),
      footer: '<button class="btn btn-ghost" data-close>关闭</button>'
    });
    try {
      const result = await api.get(`/api/forum/users/${userId}/${endpoint}`);
      modal.bodyEl.innerHTML = result.items.length ? `<div class="list">${result.items.map((item) => `
        <a class="list-item" href="#/forum/user/${item.id}" data-close style="align-items:center">
          ${avatar(item, 'sm')}<div class="grow"><div class="list-title">${esc(item.nickname)}</div>
          <div class="list-meta">${esc(item.major || '华东师范大学')}${item.grade ? ` · ${esc(item.grade)}` : ''}</div></div>
          ${icon('chevronRight')}
        </a>`).join('')}</div>` : emptyState({ iconName: 'users', title: '暂时没有人', desc: '' });
    } catch (error) {
      modal.bodyEl.innerHTML = `<div class="notice notice-danger">${icon('alert')}<div>${esc(error.message)}</div></div>`;
    }
  }

  await load();
}
