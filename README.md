# AI 学习资料知识库（ai-kb）

个人 RAG 知识库问答系统：把 AI 学习资料灌进向量库，提问后返回**带出处**的答案（文件名 + 页码）。

> 项目计划书见 [`docs/AI学习资料知识库-项目计划书.docx`](docs/AI学习资料知识库-项目计划书.docx)（v1.1）。任务按计划书第五节的任务 ID 顺序推进。

## 技术栈（计划书第 2 节，已定稿，禁止更换）

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + Pydantic |
| AI 编排 | LangChain |
| 向量库 | ChromaDB（本地文件版，`data/chroma/`） |
| Embedding | `BAAI/bge-m3`（多语，1024 维，约 2.2GB） |
| 业务库 | SQLite（`data/app.db`） |
| 模型（开发） | Ollama + `qwen2.5:7b` |
| 模型（演示） | DeepSeek API |
| 前端 | Streamlit（临时）→ Vue3 + Element Plus + Vite（最终） |
| 部署 | Docker Compose |

模型调用统一走 `app/llm.py` 的抽象层，用 `.env` 的 `LLM_PROVIDER` 切换，业务代码不硬编码模型。

## 目录结构（计划书 6.1）

```text
D:\ai-kb\
├─ app\            后端：main.py / rag.py / llm.py / db.py / config.py（T2.1 落地）
├─ web\            Vue3 前端（M3 起）
├─ scripts\        一次性脚本：提取、切片、评测
├─ data\           chroma\ 向量库 · app.db · uploads\ 原始文件 · testset.csv
├─ docs\           计划书、文档、截图
├─ materials\      10 份 AI 学习资料 PDF（约 80MB，不进 Git）
├─ .gitignore
└─ README.md
```

`app/`、`web/`、`scripts/`、`data/chroma/`、`data/uploads/` 目前用 `.gitkeep` 占位，保证目录结构进版本库；对应代码文件在各任务中创建。

## 学习资料（`materials/`，10 份，不进 Git）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `d2l-zh.pdf` | 动手学深度学习（中文第二版） |
| 2 | `mml-book-数学基础.pdf` | Mathematics for Machine Learning |
| 3 | `slp3-语音与语言处理第3版草稿.pdf` | Speech and Language Processing（3rd draft） |
| 4 | `attention-is-all-you-need.pdf` | Attention Is All You Need |
| 5 | `sentence-bert.pdf` | Sentence-BERT |
| 6 | `dpr-dense-retrieval.pdf` | Dense Passage Retrieval |
| 7 | `rag-lewis-2020.pdf` | RAG 原始论文 |
| 8 | `rag-survey-gao-2023.pdf` | RAG 综述 |
| 9 | `self-rag-2023.pdf` | Self-RAG |
| 10 | `ragas-评测.pdf` | RAGAS：RAG 自动评测 |

全部为官方发布或 arXiv 预印本，10/10 含可复制文字层（T0.2 结论），无扫描件，无需 OCR。

## 当前进度

- [x] T0.1 环境自检 → 记录见 [`docs/env-T0.1.md`](docs/env-T0.1.md)
- [x] T0.2 资料格式检查 → 10/10 电子版，T1.9 OCR 取消
- [x] T0.3 项目骨架（本文件 + 目录 + Git + .gitignore）
- [x] T0.4 安装依赖（`.venv` = Python 3.12.10，145 个包，`requirements.txt` 已锁版本）

## 运行环境

| 项 | 值 |
|---|---|
| 虚拟环境 | `D:\ai-kb\.venv`，Python **3.12.10**（隔离，`include-system-site-packages = false`） |
| 依赖 | `requirements.txt`（148 行：3 行说明 + 144 条版本锁定） |
| 关键版本 | langchain 1.4.6 · chromadb 1.5.9 · fastapi 0.150.0 · streamlit 1.66.0 · **sentence-transformers 6.1.0** · **torch 2.14.1+cpu** |
| Ollama | 0.13.5，模型目录 `D:\deepseekr17b\models`（已拉 `deepseek-r1:7b`；待拉 `bge-m3`、`qwen2.5:7b`） |

一键安装依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 国内网络若超时，改用镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`。
> 详细环境记录见 [`docs/env-T0.1.md`](docs/env-T0.1.md)。

激活虚拟环境（可选，直接调 `.\.venv\Scripts\python.exe` 效果相同）：

```powershell
Set-ExecutionPolicy -Scope Process Bypass   # 本项目目录带 Low 完整性标签，需先放行当前会话
.\.venv\Scripts\Activate.ps1                # 或在 cmd 里用 .venv\Scripts\activate.bat
```
