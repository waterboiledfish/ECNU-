/* 极简安全 Markdown：先转义 HTML，再做有限的行内/块级渲染。 */
const MATH_TOKEN = /\uE000(\d+)\uE001/g;
const INLINE_MATH = /\$(?!\s)([^$\n\r]{1,400}?)(?<!\s)\$/g;
const MATH_PATTERNS = [
  /\$\$([\s\S]{1,1200}?)\$\$/g,
  /\\\[([\s\S]{1,1200}?)\\\]/g,
  /\\\(([\s\S]{1,600}?)\\\)/g,
  INLINE_MATH
];

/* MathJax 读的是 textContent，所以只转义会破坏 HTML 的 & < >，保留反斜杠与 $ 分隔符。 */
function escapeMath(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* 先把 LaTeX 换成占位符，避免 **加粗**、[1] 引用与 HTML 转义把公式拆坏。 */
function extractMath(source) {
  const formulas = [];
  let text = source;
  for (const pattern of MATH_PATTERNS) {
    text = text.replace(pattern, (match, inner) => {
      const cjk = /[\u4e00-\u9fff，。；：！？]/.test(inner);
      if (cjk && !inner.includes('\\')) return match; // 「$5，$10」这类金额/正文不当公式
      formulas.push(match);
      return `\uE000${formulas.length - 1}\uE001`;
    });
  }
  return { text, formulas };
}

function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function inline(text) {
  let out = esc(text);
  out = out.replace(/`([^`\n]+)`/g, (m, code) => `<code>${code}</code>`);
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[\s(（])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  out = out.replace(/\[([^\]]{1,120})\]\((https?:\/\/[^\s)]+)\)/g, (m, label, url) => {
    return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  out = out.replace(/(?<![\w\]"])\[(\d{1,2})\](?!\()/g, '<span class="cite">$1</span>');
  return out;
}

export function renderMarkdown(source) {
  const { text: guarded, formulas } = extractMath(String(source || '').replace(/\r\n/g, '\n'));
  const lines = guarded.split('\n');
  const html = [];
  let paragraph = [];
  let listType = null;
  let listItems = [];
  let code = null;
  let quote = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (listType && listItems.length) {
      html.push(`<${listType}>${listItems.map((item) => `<li>${inline(item)}</li>`).join('')}</${listType}>`);
    }
    listType = null;
    listItems = [];
  };
  const flushQuote = () => {
    if (quote.length) {
      html.push(`<blockquote>${quote.map(inline).join('<br>')}</blockquote>`);
      quote = [];
    }
  };
  const flushAll = () => { flushParagraph(); flushList(); flushQuote(); };

  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, '');
    if (code !== null) {
      if (/^```/.test(line.trim())) {
        html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
        code = null;
      } else {
        code.push(rawLine);
      }
      continue;
    }
    const fence = line.trim().match(/^```([\w+-]*)\s*$/);
    if (fence) {
      flushAll();
      code = [];
      continue;
    }
    if (!line.trim()) {
      flushAll();
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushAll();
      const level = Math.min(4, heading[1].length);
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    if (/^\s*([-*_])\s*\1\s*\1[\s\S]*$/.test(line) && line.replace(/[\s-*_]/g, '') === '') {
      flushAll();
      html.push('<hr>');
      continue;
    }
    const quoteLine = line.match(/^>\s?(.*)$/);
    if (quoteLine) {
      flushParagraph(); flushList();
      quote.push(quoteLine[1]);
      continue;
    }
    flushQuote();
    const ul = line.match(/^\s*[-*+]\s+(.+)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ul || ol) {
      flushParagraph();
      const type = ul ? 'ul' : 'ol';
      if (listType && listType !== type) flushList();
      listType = type;
      listItems.push((ul || ol)[1]);
      continue;
    }
    flushList();
    paragraph.push(line);
  }
  if (code !== null) html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
  flushAll();
  return restoreMath(html.join(''), formulas);
}

/* 把占位符换回公式；代码块里的占位符保持原样，避免往 <pre> 里插 HTML 结构。
 * MathJax 只认 \(...\) 与 \[...\]，所以这里把 $...$ / $$...$$ 统一改写，
 * 正文中剩下的 $ 就不会被当成公式。 */
function restoreMath(html, formulas) {
  if (!formulas.length) return html;
  return html.split(/(<pre><code>[\s\S]*?<\/code><\/pre>)/).map((part, index) => {
    if (index % 2 === 1) return part;
    return part.replace(MATH_TOKEN, (match, id) => {
      const formula = formulas[Number(id)];
      if (formula === undefined) return match;
      let tex = formula;
      let display = false;
      if (formula.startsWith('$$')) {
        tex = `\\[${formula.slice(2, -2)}\\]`;
        display = true;
      } else if (formula.startsWith('\\[')) {
        display = true;
      } else if (!formula.startsWith('\\(')) {
        tex = `\\(${formula.slice(1, -1)}\\)`;
      }
      return `<span class="math${display ? ' math-block' : ''}">${escapeMath(tex)}</span>`;
    });
  }).join('');
}

/* 渲染后交给 MathJax 排版；MathJax 还没加载好就短暂重试，没有公式时不做事。 */
export function typeset(root) {
  if (!root || !root.querySelectorAll || !root.querySelector('.math')) return;
  const run = () => {
    const mj = window.MathJax;
    if (!mj || typeof mj.typesetPromise !== 'function') return false;
    mj.typesetPromise([root]).catch(() => {});
    return true;
  };
  if (run()) return;
  let tries = 0;
  const timer = window.setInterval(() => {
    tries += 1;
    if (run() || tries > 40) window.clearInterval(timer);
  }, 150);
}

export function stripMarkdown(source, limit = 200) {
  const text = String(source || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#>*_`~\[\]()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export { esc };
