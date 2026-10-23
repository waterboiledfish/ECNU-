import { api } from '../api.js';
import { icon, esc, toast } from '../ui.js';

export function renderLogin(auth = {}, message = '') {
  const mode = auth.mode || 'dev';
  const dev = mode === 'dev' && auth.dev_login;
  const configured = auth.configured;
  const html = `
  <div class="login-hero">
    <div class="login-brand">
      <span class="brand-mark">E</span>
      <div class="brand-text"><strong>ECNU 小助手</strong><small>华东师范大学 · 学生工作台</small></div>
    </div>
    <div>
      <h1>把校园信息<br>变成你的<em>下一步行动</em></h1>
      <p class="lead">查官网文件、安排提醒、背单词、找论文、逛论坛。一个本地优先的校园助手，模型用你自己的 API Key。</p>
      <div class="login-features">
        <div class="login-feature">${icon('sparkles')}<span>官网文件问答，回答附原文链接</span></div>
        <div class="login-feature">${icon('bell')}<span>到点主动提醒，可弹窗或系统通知</span></div>
        <div class="login-feature">${icon('calendar')}<span>每日计划、单词背诵与连续记录</span></div>
        <div class="login-feature">${icon('users')}<span>校园论坛：匿名、举报与 AI 预审</span></div>
      </div>
    </div>
    <div class="login-foot">本项目为开源学生作品，与华东师范大学无官方隶属关系。请遵守学校网络与信息安全规定。</div>
  </div>
  <div class="login-panel">
    <div class="login-card">
      <h2>${dev ? '本地演示登录' : '登录 ECNU 小助手'}</h2>
      <p class="sub">${dev
        ? '当前未连接学校统一身份认证。演示登录仅用于本地体验，数据保存在这台电脑上。'
        : '登录由学校统一身份认证完成。本应用不会获取、保存你的学号和密码。'}</p>
      ${message ? `<div class="notice notice-danger mt-16">${icon('alert')}<div>${esc(message)}</div></div>` : ''}
      ${!configured ? `<div class="notice notice-warn mt-16">${icon('alert')}<div>登录方式尚未配置。请在 .env 中设置 <code>ECNU_AUTH_MODE</code> 与对应 SSO 参数，或使用 dev 模式本地体验。</div></div>` : ''}
      ${dev ? `
        <form id="devLoginForm" class="mt-16">
          <div class="field">
            <label for="devNickname">给自己起个昵称（可稍后修改）</label>
            <input class="input" id="devNickname" maxlength="12" placeholder="例如：樱桃河边的同学" autocomplete="nickname">
          </div>
          <div class="login-actions">
            <button class="btn btn-primary btn-lg btn-block" type="submit" id="devLoginBtn">${icon('arrowRight')}<span>进入演示空间</span></button>
          </div>
        </form>
        <div class="divider-text">演示模式</div>
        <div class="notice notice-info">${icon('info')}<div>演示账号按浏览器绑定；不连接学校 SSO，也不会上传任何学号信息。正式部署请切换为 CAS / OIDC。</div></div>
      ` : `
        <div class="login-actions">
          ${configured ? `<a class="sso-button" href="/api/auth/${mode}/login">${icon('lock')}<span>使用${mode === 'cas' ? '学校统一身份认证' : '学校 OIDC'}登录</span></a>`
            : `<button class="btn btn-lg btn-block" disabled>统一身份认证未配置</button>`}
        </div>
        <div class="divider-text">安全说明</div>
        <ul class="trust-list">
          <li>${icon('shield')}<span>登录跳转到学校认证页面，本应用不接触密码。</span></li>
          <li>${icon('key')}<span>第三方模型 API Key 只随请求发送，不写入数据库。</span></li>
          <li>${icon('database')}<span>待办、计划与论坛数据保存在本地 SQLite。</span></li>
        </ul>
      `}
      ${dev ? '' : `<div class="mt-16 small muted">登录即表示你同意遵守校园社区规范。论坛内容会经过规则与 AI 预审，可申诉。</div>`}
      <p class="tiny muted mt-16" style="line-height:1.6">项目主页：<a href="https://github.com/waterboiledfish/ECNU-" target="_blank" rel="noopener noreferrer">github.com/waterboiledfish/ECNU-</a></p>
    </div>
  </div>`;
  return {
    html,
    bind(root) {
      const form = root.querySelector('#devLoginForm');
      if (!form) return;
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const btn = root.querySelector('#devLoginBtn');
        const nickname = root.querySelector('#devNickname').value.trim();
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px"></span><span>正在进入…</span>';
        try {
          await api.post('/api/auth/dev-login', { nickname });
          window.location.reload();
        } catch (error) {
          toast(error.message || '登录失败', 'error');
          btn.disabled = false;
          btn.innerHTML = `${icon('arrowRight')}<span>进入演示空间</span>`;
        }
      });
    }
  };
}
