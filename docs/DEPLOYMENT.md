# 部署说明

## 本地运行

```bash
python -m pip install -r requirements.txt
python -m app
```

默认只监听 `127.0.0.1:8765`，不会暴露到局域网。数据在 `~/.ecnu-assistant`（可用 `ECNU_DATA_DIR` 修改）。

## 生产环境配置

复制 `.env.example` 为 `.env`，至少修改：

```dotenv
ECNU_HOST=127.0.0.1
ECNU_PORT=8765
ECNU_PUBLIC_BASE_URL=https://assistant.example.edu.cn
ECNU_COOKIE_SECURE=true
ECNU_AUTH_MODE=cas              # 或 oidc
ECNU_DEV_LOGIN_ENABLED=false
ECNU_ADMIN_SUBJECTS=学号1,学号2
ECNU_ALLOW_USER_CRAWL=false
ECNU_DATA_DIR=/var/lib/ecnu-assistant
```

### HTTPS 与反向代理

必须使用 HTTPS。Nginx 示例：

```nginx
server {
    listen 443 ssl http2;
    server_name assistant.example.edu.cn;

    ssl_certificate     /etc/ssl/fullchain.pem;
    ssl_certificate_key /etc/ssl/privkey.pem;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # SSE 必须关闭缓冲
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }
}
```

应用会从 `X-Forwarded-For` 读取客户端 IP 用于限流；请确保该头只由可信代理写入。

### systemd（Linux）

```ini
[Unit]
Description=ECNU Assistant
After=network.target

[Service]
Type=simple
User=ecnu
WorkingDirectory=/opt/ecnu-assistant
EnvironmentFile=/opt/ecnu-assistant/.env
ExecStart=/usr/bin/python3 -m app
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ecnu-assistant
```

### Windows 自启

提醒的「系统弹窗 / CMD 窗口」需要在**已登录的交互式桌面**中运行，不能用 Session 0 的系统服务。

推荐用「任务计划程序」：

1. 触发器：用户登录时；
2. 操作：`C:\...\python.exe -m app`；
3. 起始于：项目根目录（包含 `app` 包的目录）；
4. 勾选「只在用户登录时运行」。

这样即使浏览器关闭，服务仍在后台，调度器可以弹出窗口。电脑关机或服务停止时不会提醒。

## Docker

```bash
docker build -t ecnu-assistant .
docker run -d --name ecnu-assistant \
  -p 127.0.0.1:8765:8765 \
  -v ecnu-data:/data \
  --env-file .env \
  ecnu-assistant
```

说明：

- 镜像内 `ECNU_DATA_DIR=/data`；
- 容器内无法弹出 Windows 的 CMD/桌面窗口，请只使用 `inapp` / `browser` 通道；
- 容器默认监听 `0.0.0.0`，仍需通过反向代理暴露；
- 如需系统弹窗，请用桌面方式部署。

## 数据备份

```bash
# 停止服务后
sqlite3 /var/lib/ecnu-assistant/assistant.db ".backup '/backup/assistant-$(date +%F).db'"
cp -r /var/lib/ecnu-assistant/avatars /backup/avatars-$(date +%F)
```

或直接复制整个数据目录。恢复时保持路径与权限一致。

## 首次上线

1. 用管理员账号登录一次（`ECNU_ADMIN_SUBJECTS` 匹配）。
2. 进入「官网文件」，先采集学校主页、教务处、图书馆等核心站点。
3. 在「官网问答」提几个有明确原文的问题，核对引用链接与日期。
4. 检查「今日热点」「论文推荐」能否访问外部服务；如网络受限，配置代理或禁用对应模块。
5. 发布社区规范，配置 AI 审核（可选），安排管理员值守。
6. 用测试账号验证匿名、举报、申诉、私信、关注。
7. 验证删除账号后的数据表现。

## 安全清单

- [ ] 全站 HTTPS，`ECNU_COOKIE_SECURE=true`
- [ ] `ECNU_DEV_LOGIN_ENABLED=false`
- [ ] `ECNU_ALLOW_USER_CRAWL=false`，仅管理员采集
- [ ] 管理员账号最小化，定期审查
- [ ] 数据目录权限仅服务账号可读写
- [ ] 备份加密并限制访问
- [ ] 反向代理关闭 SSE 缓冲
- [ ] 限制 `/api/docs` 的访问（可在 Nginx 加 IP 白名单）
- [ ] 如启用 AI 审核，选用合规的模型服务并在隐私说明中披露
- [ ] 定期更新依赖（Dependabot 已配置）

## 性能与容量

- 单进程 + SQLite + 内存索引适合数百名活跃用户、数万份文档。
- 每次采集会重建索引；大站点建议分批、低峰采集。
- 新闻/论文/学习资料有缓存；问答流式响应不落库。
- 若需要多实例：把数据库迁移到 PostgreSQL，把索引改为独立服务，并把限流改为 Redis。

## 故障排查

**503 / 打不开**：确认服务进程、端口、反向代理与防火墙。
**登录回调失败**：检查 `ECNU_PUBLIC_BASE_URL`、回调登记、HTTPS 与 Cookie。
**SSE 不推送**：Nginx 是否关闭 `proxy_buffering`，代理超时是否足够。
**采集全部 403**：目标站点拦截自动化；可换网络、降低频率，或仅保留链接。TLS EOF 会自动回退系统 curl。
**模型报 401/404**：检查 Key、模型 ID、Base URL；不同服务商路径不同。
**CMD 不弹窗**：Windows 服务/计划任务必须以当前用户交互式运行。
