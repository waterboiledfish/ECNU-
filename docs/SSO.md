# 学校统一身份认证（SSO）接入

本应用**不模拟、不代理**学校登录页，也不接收学号密码。所有凭据只在学校自己的认证页面输入。

## 三种模式

| `ECNU_AUTH_MODE` | 用途 | 是否可用于生产 |
| --- | --- | --- |
| `dev` | 本地演示：按浏览器设备 Cookie 创建一个本地账号 | 否 |
| `cas` | 学校统一身份认证 CAS | 需学校审批/登记 |
| `oidc` | 学校 OIDC | 需学校审批/登记 |

默认是 `dev`。界面上会明确提示「本地演示登录，未连接学校统一身份认证」。

## CAS

### 配置

```dotenv
ECNU_AUTH_MODE=cas
ECNU_CAS_BASE_URL=https://<学校 cas 地址>
ECNU_CAS_LOGIN_PATH=/cas/login
ECNU_CAS_VALIDATE_PATH=/cas/serviceValidate
# 可选：登记的回调地址；不填则用 PUBLIC_BASE_URL + /api/auth/cas/callback
ECNU_CAS_SERVICE_URL=https://your-host/api/auth/cas/callback
ECNU_PUBLIC_BASE_URL=https://your-host
```

### 流程

1. 用户点击登录，访问 `/api/auth/cas/login`。
2. 生成一次性 `state`，写入 HttpOnly、10 分钟有效的 Cookie。
3. 302 到 `CAS_BASE + LOGIN_PATH?service=<回调地址?state=...>`。
4. 学校认证完成后带 `ticket` 回到 `/api/auth/cas/callback`。
5. 服务端校验 Cookie 中的 `state`，再向 `serviceValidate` 校验 ticket。
6. 成功后用 CAS principal 生成 `cas:<principal>` 作为稳定标识，创建本地账号与会话。

**注意**：`service` 参数必须与学校登记的地址一致。部分 CAS 部署要求 service 完全固定，此时需要学校允许携带 `state` 查询参数，或由部署者在反向代理层处理；请与学校信息化部门确认。应用会把 `state` 拼在 service 后，用于防登录 CSRF。

## OIDC

### 配置

```dotenv
ECNU_AUTH_MODE=oidc
ECNU_OIDC_ISSUER=https://<学校 issuer>
ECNU_OIDC_CLIENT_ID=...
ECNU_OIDC_CLIENT_SECRET=...
ECNU_OIDC_REDIRECT_URI=https://your-host/api/auth/oidc/callback
ECNU_OIDC_SCOPE=openid profile
```

### 流程

1. `/api/auth/oidc/login` 读取 `/.well-known/openid-configuration`。
2. 生成 state 与 PKCE verifier，state 写入数据库（10 分钟），跳转授权端点。
3. 回调校验 state，使用授权码 + PKCE 换 access token。
4. 调用 `userinfo_endpoint` 获取 `sub` 与昵称。
5. 成功后生成 `oidc:<sub>` 作为稳定标识。

服务端不解析、不信任未经验证的 id_token；身份信息以 TLS 下的 token 端点 + userinfo 端点为来源。生产环境请使用 HTTPS，并确认学校 OIDC 客户端配置了正确回调。

## 管理员

管理员由环境变量指定：

```dotenv
ECNU_ADMIN_SUBJECTS=1021xxxx,1022xxxx
```

首次登录时匹配完整 subject 或 principal，授予 `admin` 角色。管理员可访问 `/api/admin/*` 与前端「管理后台」。

> 不要在数据库中手工提升陌生账号为管理员；管理员权限可删除内容、处理申诉。

## 数据与隐私

- 只有认证系统返回的稳定标识（`cas:<principal>` / `oidc:<sub>`）写入 `users.sso_subject`。
- 不存储学号密码、不存储 ticket、不存储 access token。
- 昵称默认由本地生成，不把学号展示给其他用户。
- 头像、简介、专业、年级、学习方向由用户自行填写。
- 删除账号会级联删除会话、待办、计划、私信、通知等个人数据；公开帖子转为「已注销用户」。

## 接入检查清单

- [ ] 已获得学校信息化部门对第三方应用接入的批准。
- [ ] 回调地址已在 CAS / OIDC 客户端登记，HTTPS 可访问。
- [ ] `ECNU_PUBLIC_BASE_URL` 与实际访问地址一致。
- [ ] `ECNU_COOKIE_SECURE=true`，站点仅通过 HTTPS 访问。
- [ ] `ECNU_DEV_LOGIN_ENABLED=false`。
- [ ] 已配置 `ECNU_ADMIN_SUBJECTS`。
- [ ] 在测试账号上验证登录、退出、会话过期、管理员权限。
- [ ] 在隐私说明中写明认证与数据留存方式。

## 常见问题

**登录后回到首页但仍是未登录？**
检查回调地址、Cookie 域/路径、反向代理是否改写了 `Host`，以及浏览器是否阻止第三方 Cookie。生产环境必须 HTTPS。

**CAS 返回 authenticationFailure？**
确认 service 与登记值完全一致、ticket 未过期、服务器时间准确。

**OIDC 报 userinfo 缺失？**
本应用要求学校 OIDC 提供 `userinfo_endpoint`。如果学校只提供 id_token，请联系维护者扩展受信任的 JWT 校验流程。

**开发时能否用真实学校 SSO？**
可以，但需要学校分配测试客户端；请勿在公开演示环境开启真实 SSO 的写权限。
