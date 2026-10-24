# 部署方案（T6.2 准备）

计划书 T6.2 要求「公网能打开界面 → 能完成上传与提问 → 地址写入 README 与简历」。
下面两条路线都写好了完整命令，选定后照做即可；两条都不改技术栈。

## 公网加固清单（部署前逐项过）

| 项 | 做法 | 本项目状态 |
|---|---|---|
| 鉴权 | `.env` 设 `AUTH_TOKEN`，界面登录一次 | ✅ 已实现（登录 + 7 天会话 Cookie） |
| 限流 | `.env` 的 `RATE_LIMIT_PER_MINUTE`（默认 120/分钟）与 `RATE_LIMIT_UPLOAD_PER_MINUTE`（默认 30） | ✅ 已实现（应用层按 IP 滑动窗口，超限 429） |
| 更外层限流 | `deploy/nginx-public.conf` 里的 `limit_req` | ✅ 样例已备 |
| HTTPS | `deploy/nginx-public.conf` + `certbot --nginx -d 你的域名` | ✅ 配置样例已备（需域名） |
| Cookie 安全标记 | HTTPS 下设 `COOKIE_SECURE=1` | ✅ 已实现 |
| 关闭接口文档 | 生产设 `DOCS_ENABLED=0`（/docs 与 /openapi.json 变 404） | ✅ 已实现 |
| 上传体积 | 应用内 100MB 上限 + Nginx `client_max_body_size 100m` | ✅ 两处都有 |
| 数据备份 | `scripts/backup_data.py`（向量库 + SQLite + 上传文件打 zip） | ✅ 已实现，实测 701MB |
| 日志 | `data/app.log`，5MB×3 轮转 | ✅ 已实现 |
| 容器重启策略 | compose 里 `restart: unless-stopped` + healthcheck | ✅ 已配 |

**部署顺序建议**：先按上表配好 `.env`（AUTH_TOKEN / DOCS_ENABLED=0 / COOKIE_SECURE=1）→ 起容器 →
套上 Nginx 样例并申请证书 → 最后把地址写进 README 与简历。

## 先决条件（两条路线共用）

> **公网部署必须做的一步**：在 `.env` 里设置 `AUTH_TOKEN=<任意随机串>`。
> 本项目默认不鉴权，一旦暴露公网，任何人都能上传或删除你的资料。
> 设置后打开界面登录一次即可：后端下发 7 天会话 Cookie，之后问答、上传、打开 PDF 都不再需要令牌；
> 也支持 `?token=<AUTH_TOKEN>` 一次性登录链接（登录后地址栏自动去掉参数）。

1. 本机能跑通：后端 `python -m app.main`、前端 `cd web; npm run dev`；
2. Ollama 在跑，模型 `bge-m3`、`qwen2.5:7b` 已拉取；
3. 项目根目录 `D:\ai-kb`，`.env` 已按 `.env.example` 配好。

---

## 方案 A：内网穿透（免费，当天可用，适合录视频/临时演示）

**优点**：不买服务器、不用改代码，5 分钟出公网地址。
**缺点**：地址每次重启会变；本机关机就没了；免费版有带宽/并发限制。

### A-1 安装 cpolar 或 ngrok（二选一，由你安装）

- cpolar：<https://www.cpolar.com/>（国内访问快，免费版够用）
- ngrok：<https://ngrok.com/>（需要注册拿 token）

### A-2 打两个隧道

```powershell
# 后端（8000）—— 注意用 http 隧道
cpolar http 8000
# 前端（5173）
cpolar http 5173
```

或用 ngrok：

```powershell
ngrok http 8000
ngrok http 5173
```

### A-3 前端要指向公网后端

当前前端用 Vite 代理 `/api` → 本机 8000，公网访问时这条代理不生效，需要改一处：

```bash
# web/.env.production 新建，写后端公网地址
VITE_API_BASE=https://<后端公网地址>
```

并把 `web/src/api.js` 的 `baseURL` 从 `/api` 改成 `import.meta.env.VITE_API_BASE || '/api'`。
（这是一处改动，需要你确认后我再动代码；本地开发行为保持不变。）

### A-4 验收

- 浏览器打开前端公网地址 → 能上传、能提问、能看到出处；
- 把地址写进 README 的「在线演示」。

---

## 方案 B：云服务器（¥60–100/月，地址稳定，可写进简历）

**优点**：地址固定，随时可访问，最像线上产品。
**缺点**：要装 Docker、拉模型（或改走云端 API），1 核 2G 跑 7B 不现实。

### B-1 关键现实约束

1 核 2G 的服务器**跑不动 7B 本地模型**。两条子路线：

| 子路线 | 做法 | 成本 |
|---|---|---|
| B-1 云端模型 | 服务器上只跑 FastAPI + Chroma，模型走 DeepSeek API（`LLM_PROVIDER=deepseek`） | 服务器 ¥60/月 + token 费（本项目一天几毛） |
| B-2 本地模型 | 服务器至少要 8 核 16G + GPU，成本高得多 | 不建议 |

**推荐 B-1**：向量仍在服务器上用 bge-m3 跑（CPU 可接受，只在入库/检索时用），生成走 DeepSeek。

### B-2 部署步骤（B-1 路线）

```bash
# 1) 服务器装 Docker（Ubuntu 示例）
curl -fsSL https://get.docker.com | sh

# 2) 拉代码
git clone <你的仓库地址> ai-kb && cd ai-kb

# 3) 配置
cp .env.example .env
# 编辑 .env：
#   LLM_PROVIDER=deepseek
#   DEEPSEEK_API_KEY=sk-...
#   OLLAMA_BASE_URL=http://<本机或另一台机器的 Ollama>  ← 若服务器无 Ollama，需改走云端 embedding
```

### B-3 关于 embedding 的取舍（必须说清）

服务器没有 Ollama 就没有 bge-m3，两条路：

1. **在服务器上装 Ollama 只跑 bge-m3**（约 1.2GB 内存占用，1 核 2G 勉强，建议 2 核 4G）；
2. 换云端 embedding（如 DeepSeek 暂无 embedding 接口，需要第三方）——**这属于换技术栈，需你确认**。

**结论：最省事的是「2 核 4G 服务器 + 服务器上装 Ollama 只跑 bge-m3 + 生成走 DeepSeek」。**

### B-4 起服务

```bash
docker compose up -d --build
# 前端 http://<公网IP>/    后端 http://<公网IP>:8000/docs
```

### B-5 Nginx 与端口

- 80 端口给前端（compose 已配），8000 给后端（建议安全组只开 80，用 Nginx 反代 8000）；
- 若要 HTTPS，用 certbot：`certbot --nginx -d your-domain.com`。

### B-6 验收

- 公网打开前端 → 上传一个小 md → 提问 → 看到出处；
- 地址写进 README 与简历。

---

## 我建议的顺序

1. **先做 A**（内网穿透）：零成本，今天就能拿到可演示链接，够录 T5.3 的视频；
2. **简历上先不写在线地址**，等 B 真正跑起来再写；
3. 若决定做 B，选 **2 核 4G + 服务器装 Ollama（只跑 bge-m3）+ DeepSeek 生成**。

## 需要你确认的两点

1. 选 A 还是 B（或都跳过）；
2. 若选 A，是否允许我改 `web/src/api.js` 支持 `VITE_API_BASE`（一处小改动，本地行为不变）。
