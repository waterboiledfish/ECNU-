/* MathJax 3 配置：必须在 tex-svg.js 之前加载。
 * 站点的 CSP 是 script-src 'self'，内联脚本会被拦掉，所以配置单独成文件。 */
window.MathJax = {
  startup: { typeset: false },
  tex: {
    /* 只认反斜杠括号分隔符：正文里的 $ 与 $$（金额、美元符号）不会被误当公式。
     * markdown.js 会把 $...$ / $$...$$ 统一改写成这两种形式再交给 MathJax。 */
    inlineMath: [['\\(', '\\)']],
    displayMath: [['\\[', '\\]']],
    processEscapes: true
  },
  svg: { fontCache: 'local' },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
    ignoreHtmlClass: 'tex2jax_ignore'
  }
};
