# AI 学习资料知识库（ai-kb）

把 AI 学习资料灌进向量库，提问后返回**带出处**的答案（文件名 + PDF 页码）。

- 单用户、无账号体系；支持 PDF / Word / Markdown / TXT
- 答案逐字流式输出，附「文件 + 页码 + 命中片段 + 相似度」
- 自建 30 题测试集评测：**检索召回率 90.0%**、**答案准确率 80.0%**

> 详细计划与进度见 [`docs/AI学习资料知识库-项目计划书.docx`](docs/AI学习资料知识库-项目计划书.docx)（v1.3）；
> 基线数据见 [`docs/baseline.md`](docs/baseline.md)。

## 界面

![首页](docs/screenshots/ui-home.png)

![问答与出处](docs/screenshots/ui-answer.png)

左侧是已入库资料（片数、大小、删除），右侧问答区给出答案与**出处卡片**（文件名 + PDF 页码 + 相似度 + 命中片段）。

## 架构

```text
            ┌──────────────────────────────┐
 浏览器 ──▶ │ Vue3 + Element Plus (web/)   │  Vite 开发 / Nginx 托管
            └───────────────┬──────────────┘
                     /api 代理（SSE 不缓冲）
            ┌───────────────▼──────────────┐
            │ FastAPI（app/main.py）        │  /upload /chat /chat/stream /files
            ├──────────────────────────────┤
            │ RAG 核心（app/rag.py）        │  解析→切片→检索→拼 prompt→生成
            ├──────────────┬───────────────┤
            │ ChromaDB      │ SQLite        │  向量库 data/chroma · 会话 data/app.db
            │ (bge-m3)      │ (历史)        │
            └──────────────┴───────┬───────┘
                                    │ HTTP
                          ┌─────────▼─────────┐
                          │ Ollama（宿主机）    │  bge-m3（向量）+ qwen2.5:7b（生成）
                          └───────────────────┘
```

模型层可切换：`LLM_PROVIDER=ollama`（本地免费）或 `deepseek`（云端，需 API Key），
业务代码不硬编码模型名，见 `app/llm.py`。

## 快速开始（本地）

```powershell
# 1) 依赖
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 配置（按需改 .env：模型名、端口、闸门阈值）
Copy-Item .env.example .env

# 3) 起服务
.\.venv\Scripts\python.exe -m app.main          # http://127.0.0.1:8000/docs
.\.venv\Scripts\python.exe -m streamlit run ui_streamlit.py   # 临时界面 http://localhost:8501

# 4) 产品界面（Vue3）
cd web; npm install --registry=https://registry.npmmirror.com; npm run dev   # http://127.0.0.1:5173
```

前置条件：本机装好 [Ollama](https://ollama.com/) 并拉取模型：

```powershell
ollama pull bge-m3
ollama pull qwen2.5:7b
```

首次使用需要把资料入库（把 PDF 放进 `materials/`）：

```powershell
.\.venv\Scripts\python.exe scripts\04_store.py --all    # 全量入库（约 8,900 片，视机器 40-60 分钟）
```

## Docker（可选）

```powershell
docker compose up -d --build
# 前端 http://localhost/    后端 http://localhost:8000/docs
```

Ollama 仍跑在宿主机，容器通过 `host.docker.internal:11434` 访问（compose 已配好）。

> 说明：本机当前未安装 Docker，这一项**尚未实机验证**，验证后再更新本段。

## 配置（`.env`）

| 键 | 默认 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` 或 `deepseek` |
| `OLLAMA_MODEL` | `qwen2.5:7b` | 生成模型 |
| `OLLAMA_EMBED_MODEL` | `bge-m3:latest` | 向量模型（1024 维） |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 地址 |
| `DEEPSEEK_API_KEY` | 空 | 切云端时才需要 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 512 / 50 | 切片参数 |
| `TOP_K` | 5 | 检索条数 |
| `RAG_SCORE_GATE` | 0.45 | 最佳相似度低于此值直接答「资料中没有相关内容」 |
| `APP_PORT` | 8000 | 服务端口 |

`.env` 不进 Git，模板见 `.env.example`。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（返回库里条数与当前模型） |
| POST | `/upload` | 上传文件 → 解析/切片/嵌入/入库，返回 `filename/chunks/size` |
| POST | `/chat` | 问答，返回 `answer/sources/session_id` |
| POST | `/chat/stream` | SSE 流式：`sources → token… → done` |
| GET | `/files` | 已入库文件（文件名、大小、切片数） |
| DELETE | `/files/{name}` | 删除文件及其向量 |
| GET | `/sessions/{id}` | 按会话 ID 取回历史 |

## 项目结构

```text
app/            config.py 配置 · llm.py 模型抽象 · rag.py RAG 核心 · db.py 历史 · main.py 路由
scripts/        01 提取 · 02 切片 · 03 向量验证 · 04 入库 · 05 命令行 RAG · 06 测试集 · evaluate.py 评测
web/            Vue3 前端（src/views/Chat.vue 主界面）
materials/      10 份 AI 学习资料 PDF（不进 Git）
data/           chroma/ 向量库 · app.db 历史 · uploads/ 上传文件 · testset.csv 测试集
docs/           计划书、基线、环境记录
```

## 评测

```powershell
.\.venv\Scripts\python.exe scripts\evaluate.py
```

30 题覆盖 10 份资料，指标定义与错题分析见 `docs/baseline.md`。当前基线：

| 指标 | 目标 | 实测 |
|---|---|---|
| 检索召回率 | ≥ 80% | **90.0%** |
| 答案准确率 | ≥ 70% | **80.0%** |
| 首字延迟 / 完整耗时 | ≤ 3s / ≤ 15s | **1.2s / 均值 3.6s** |
| 云端对照（deepseek-chat） | — | 召回 90.0% · 准确 **86.7%** · 1.1s |

## 几个值得说的技术点

1. **切片的 50 字重叠是补出来的**：LangChain 的 `chunk_overlap` 按切分单元整块回退，
   PDF 长行会让重叠变成 0。本项目切完后再做边界补齐，保证「≤512 字且相邻重叠 ≥50」。
2. **「资料中没有」用双保险**：相似度闸门（0.45）+ prompt 约束。单纯靠阈值不可靠 ——
   实测无关文本对的余弦也能到 0.35。
3. **bge-m3 的 NaN 兜底**：Ollama 版模型对个别 token 会返回 500，已在 Embedding 层加
   降级重试，避免一句坏输入让整次检索失败。
4. **出处不撒谎**：跨页切片同时记录 `page_start/page_end`，回答里写 `p.434–435`；
   d2l-zh 的印刷页码 = 物理页 − 18，文档如实标注是 PDF 物理页。

## 当前进度

- ✅ M0 环境 · M1 命令行 RAG · M2 后端 API · M3 前端（Vue3 可跑，代理/SSE 已验） · M4 测试集与基线
- 🟡 M5 交付：Docker 文件就绪但本机无 Docker、演示视频待录
- 🟡 M6 加分：A/B 实验 E1/E4 已出数据；E2/E3 需额外拉模型；云部署待定方案
- ⚠️ 首字延迟未达 ≤3s：6GB 显存跑本地 7B 模型，实测热态 3.5–6s，详见 `docs/baseline.md` 第 8 节

## 已知限制

- 单用户设计，无鉴权（计划书明确不做用户系统）
- 目录页/参考文献页仍会进入向量库（检索侧已过滤大部分）
- 本地 7B 模型在长答案上偶有细节偏差，基线文档里逐条记录了错题
