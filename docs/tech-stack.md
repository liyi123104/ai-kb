# AI 学习资料知识库 · 技术栈说明

> v1.0 · 2026-10-23 · 基于仓库与运行环境实测整理

## 一、总体架构

本项目是一条完整的 RAG（检索增强生成）链路：把 10 份 AI 学习资料解析、切片、向量化后存入本地向量库；提问时先检索最相关片段，再交给大模型生成带出处的答案。

| 层 | 技术 | 职责 |
|---|---|---|
| 表现层 | Vue 3 + Vite + Element Plus + Nginx | 问答界面、文件管理、模型选择、出处跳转 |
| 接口层 | FastAPI + Pydantic + Uvicorn | 12 个 REST/SSE 接口 |
| 业务层 | RAG 管线 | app/rag.py 等 7 个模块 |
| 模型层 | Ollama + DeepSeek | 生成与向量化 |
| 存储层 | ChromaDB + SQLite + 文件系统 | 向量、会话、原始语料 |
| 交付层 | Docker + docker compose | 两个容器一键起停 |

## 二、运行环境

| 项 | 版本 | 说明 |
|---|---|---|
| 操作系统 | Windows 11（开发机），Linux 容器内运行 | Docker 与本地开发两套环境 |
| Python | 3.12.10 (AMD64) | 后端与脚本；容器镜像同为 3.12 |
| Node.js | v24.20.0 | 前端构建（Vite 7 要求 Node ≥ 20） |
| npm | 11.19.0 | 前端依赖管理 |
| Docker | 29.9.2 (build a82e528) | 容器化部署（T5.1） |
| Ollama | 0.13.5 | 本地模型运行时（生成 + 向量） |

## 三、后端技术

| 技术 | 版本 | 用途 | 选型说明 |
|---|---|---|---|
| FastAPI | 0.150.0 | HTTP 接口框架，自动生成 OpenAPI 文档（/docs） | 同步路由 + 线程池，够用且代码量最小 |
| Uvicorn | 0.54.0 | ASGI 服务器，承载 FastAPI | 官方推荐搭配，容器内 --host 0.0.0.0 |
| Pydantic | 2.14.1 | 请求/响应模型与字段校验 | FastAPI 原生集成，错误信息直接可用 |
| python-dotenv | 1.2.4 | 读取 .env 配置 | 配置外置，切换模型不改代码 |
| python-multipart | 随 FastAPI | 解析上传的 multipart 表单 | /upload 依赖 |
| httpx / requests | 0.28.1 / 2.34.2 | HTTP 客户端 | 直连 Ollama 的 /api/embed 与健康检查 |
| SQLite (标准库) | 3.45+ | 会话与消息持久化 | 零运维、单文件，够本项目规模 |

## 四、AI 与模型层

| 技术 | 版本/规格 | 用途 | 说明 |
|---|---|---|---|
| Ollama | 0.13.5 | 本地模型运行时，提供 /api/generate、/api/chat、/api/embed | 免 GPU 运维，一条命令拉模型 |
| qwen2.5:7b | 4.4 GB | 默认生成模型（本地、免费、离线） | 中文效果好，6GB 显存可跑 |
| bge-m3 | 1.2 GB / 1024 维 | 向量模型，中文语义检索 | 中文检索强，维度与语料规模匹配 |
| deepseek-chat | 云端 API | 云端生成模型（可切换） | 答案更自然、准确率更高，演示用 |
| deepseek-r1:7b | 4.4 GB | 本机另一可选生成模型 | 验证「自动发现模型」功能 |
| LangChain | 1.4.6 | 模型抽象、文本切分、向量库对接 | 生态成熟，Ollama/OpenAI 一套接口 |
| langchain-core | 1.6.12 | BaseChatModel 等基础抽象 | get_llm 返回统一类型 |
| langchain-ollama | 1.1.0 | ChatOllama 适配器 | 本地生成模型接入 |
| langchain-openai | 1.7.2 | ChatOpenAI 适配器（DeepSeek 兼容 OpenAI 协议） | 一行配置切云端 |
| langchain-community | 0.4.2 | Chroma 向量库封装 | 与 LangChain 生态一致 |
| langchain-text-splitters | 1.1.3 | RecursiveCharacterTextSplitter | 按语义边界递归切分 |
| ollama (python sdk) | 0.6.3 | 备用客户端 | 调试与实验脚本使用 |

### 4.1 可切换的生成模型

| 模型 | 体积 | 角色 | 特点 |
|---|---|---|---|
| qwen2.5:7b | 4.4 GB | 本地生成（默认） | 免费、离线，答案偶尔偏公式化 |
| bge-m3:latest | 1.2 GB | 向量化（固定，不可切换） | 1024 维，换掉必须重建索引 |
| deepseek-chat | 云端 | 云端生成（可选） | 更自然、准确率 86.7%，需联网与 Key |
| deepseek-r1:7b | 4.4 GB | 本地生成（可选） | 用于验证模型切换功能 |

### 4.2 向量模型为什么固定

向量库是用 bge-m3 的 1024 维向量建立的（8,895 条）。换 embedding 模型必须重建索引，故不提供选项。


## 五、RAG 管线与核心参数

| 步骤 | 实现 | 产物 |
|---|---|---|
| 1. 解析 | scripts/01_extract.py + pypdf | PDF/DOCX/MD/TXT → 逐页纯文本，保留页码 |
| 2. 切片 | scripts/02_chunk.py + RecursiveCharacterTextSplitter | 512 字/片、重叠 50 字，跨页片段记 page_start/page_end |
| 3. 向量化 | scripts/03_embed.py + bge-m3（Ollama） | 每片 → 1024 维向量 |
| 4. 入库 | scripts/04_store.py + ChromaDB | 写入集合 ai-kb，id = source:page:序号:hash，同文本去重 |
| 5. 检索 | app/rag.py retrieve() | 问题向量化 → 余弦检索 Top-5 → 噪声过滤 → 相似度闸门 0.45 |
| 6. 生成 | app/llm.py + Ollama/DeepSeek | Top-2 片段 + 规则提示词 → 流式生成答案 |
| 7. 后处理 | rag.clean_answer / best_snippet | 去 LaTeX、按句清洗、出处摘要取最相关句 |
| 8. 溯源 | GET /files/{name}/highlight | PyMuPDF 定位命中句 → 黄色高亮 → 浏览器跳到该页 |

### 5.1 关键参数

| 参数 | 取值 | 依据 |
|---|---|---|
| 切片长度 chunk_size | 512 | E1 实验：256/512/1024 对应召回 90.0%/90.0%/86.7% |
| 切片重叠 chunk_overlap | 50 | E4 实验：0/20/50 对应 83.3%/83.3%/90.0% |
| 检索条数 top_k | 5 | 召回率按 Top-5 统计 |
| 喂入上下文条数 answer_top_n | 2 | E5 实验：1/2/3 条对应准确率 70.0%/83.3%/76.7% |
| 相似度闸门 score_gate | 0.45 | 低于此值走「资料中没有相关内容」 |
| 上下文窗口 num_ctx | 2048 | 6GB 显存下的平衡点，KV 缓存减半 |
| 模型保活 keep_alive | 30m | 避免每次请求重载模型 |

### 5.2 三个工程细节

- 切片重叠兜底：额外实现 `_enforce_overlap`，保证 ≤512 字且重叠 ≥50（LangChain 对超长单行会退化为 0）
- 双保险拒答：相似度闸门 0.45 + 提示词规则；四版提示词对比后采用平衡版，拒答 5/5、准确率 76.7%
- 输出自然语言：禁止 LaTeX + `clean_answer()` 兜底 + 流式按句清洗


## 六、数据存储

| 技术 | 规格 | 内容 | 说明 |
|---|---|---|---|
| ChromaDB | 1.5.9 | 向量库，集合 ai-kb 共 8,895 条（另有 4 个实验集合） | 本地持久化、零服务端、支持 metadata 过滤 |
| SQLite 表 sessions | id, created_at | 136 行：会话 | 单文件、随项目走 |
| SQLite 表 messages | id, session_id, role, content, sources, created_at | 274 行：消息含出处 JSON | 出处随消息保存，刷新可复原 |
| 文件存储 materials/ | 10 份 PDF，约 80 MB | 原始语料 | 只读挂载进容器 |
| 文件存储 data/uploads/ | 运行时上传 | 用户上传文件 | 与语料同目录读取 |
| 文件存储 data/tmp/ | 运行时 | TEMP/TMP 重定向 + 高亮缓存 | 规避低权限进程写系统临时目录失败 |

## 七、前端技术

| 技术 | 版本 | 用途 | 说明 |
|---|---|---|---|
| Vue 3 | 3.5 | 组合式 API（setup） | 轻量、上手快、生态成熟 |
| Vite | 7.1 | 开发服务器与构建（1657 模块，构建约 6s） | 冷启动快，HMR 好用 |
| Element Plus | 2.11 | 上传、下拉框、消息气泡等组件 | 中文文档完善，样式统一 |
| axios | 1.13 | 普通请求封装 | 错误处理方便 |
| fetch + 手写 SSE 解析 | 浏览器原生 | /chat/stream 流式接收 | EventSource 不支持 POST，故手写解析 |
| Nginx | 1.27-alpine | 生产静态托管 + /api 反代 | 官方镜像小，配置直观 |

## 八、文档处理

| 库 | 版本 | 用途 | 说明 |
|---|---|---|---|
| pypdf | 6.21.1 | PDF 文本提取（T1.1） | 纯 Python，无外部依赖 |
| PyMuPDF (fitz) | 1.28.2 | PDF 定位搜索 + 黄色高亮注释 | 能拿到文字坐标，pypdf 做不到 |
| python-docx | 1.2.0 | DOCX 解析入库、DOCX 转 HTML 阅读视图 | 官方库，稳定 |
| RecursiveCharacterTextSplitter | 1.1.3 | 跨页切片，自定义重叠兜底 | 先按段落/句号切，再按长度合并 |

## 九、部署与运维

| 技术 | 版本/规格 | 用途 | 说明 |
|---|---|---|---|
| Docker | 29.9.2 | 镜像构建与容器运行 | 一次构建，到处运行 |
| docker compose | v2 | 编排 backend + frontend 两个服务 | 一条命令起停 |
| python:3.12-slim | 179 MB | 后端基础镜像 | slim 版减少体积 |
| node:24-alpine | — | 前端构建阶段 | 与开发环境 Node 版本一致 |
| nginx:1.27-alpine | — | 前端运行阶段 | 体积小、配置简单 |
| requirements-docker.txt | 132 个包 | 容器依赖（去掉 torch 等 13 个未使用重包） | 镜像从预计 4GB+ 降到 1.29GB |

## 十、测试与质量

| 工具/脚本 | 规模 | 内容 | 说明 |
|---|---|---|---|
| 自建测试脚本 | tests/run_tests.py | 30 个用例：接口契约 10、安全边界 6、问答流式 6、纯函数与数据 8 | 不引入 pytest，零依赖可跑 |
| 质量评测 | scripts/evaluate.py | 30 题测试集：召回率、准确率、耗时 | 一条命令出基线数字 |
| 对照实验 | scripts/exp_*.py | E1 切片长度、E4 重叠、E5 上下文条数、E6 本地vs云端、E7 拒答提示词 | 每次只改一个变量 |
| 环境自检 | scripts/check_env.py | Ollama 可达性、模型是否齐全、向量库条数、前端依赖 | 换设备一键诊断 |
| 打包分发 | scripts/package.py | 源码包 0.7MB / 完整包 378MB | 内置拒绝打包 .env |

## 十一、技术选型理由

| 问题 | 结论 |
|---|---|
| 为什么用 Ollama 而不是直接调模型文件 | 免去 GPU 环境与推理框架维护；一条命令换模型；embedding 与生成同一套运行时 |
| 为什么 embedding 直连 /api/embed 而不走 LangChain | 实测 langchain_ollama 未把 keep_alive 传下去，模型被反复卸载，单次检索多花 2.2 秒 |
| 为什么默认向量模型放 CPU | 6GB 显存装不下 qwen(4.4G)+bge-m3(1.2G)；本地生成时把显存让给生成模型，云端生成时再放回 GPU |
| 为什么用 Chroma 而不是 FAISS/Milvus | 需要持久化 + metadata 过滤 + 零服务端；8,895 条规模远未到 Milvus 的必要门槛 |
| 为什么 SQLite | 会话量级小，单文件便于随项目迁移，无需额外服务 |
| 为什么前端有 Vue 还保留 Streamlit | Streamlit 是计划书里的临时界面（T3.1），用于快速验证后端，Vue 是产品界面 |
| 为什么切句而不是直接截 100 字做出处摘要 | 直接截取会从单词中间断开且常截到代码行，按句+相关度挑选后可读性明显更好 |

## 十二、明确未采用的技术

| 未采用 | 原因 |
|---|---|
| 模型微调 / LoRA | 计划书「不做」清单：本项目聚焦 RAG 工程链路，微调不产生额外工程价值 |
| 云端向量数据库（Pinecone 等） | 数据量小且要求离线可用，引入外部服务反而增加故障面 |
| 重排序模型（bge-reranker） | 列为 T6.1 的 E2 实验，需要额外拉模型，尚未执行 |
| 多模态 / OCR | 语料 PDF 文字层 100% 覆盖（T0.2 实测），OCR 无必要（T1.9 已取消） |
| Kubernetes / 服务网格 | 单机两容器，compose 足够 |

## 十三、工程与安全实践

| 实践 | 做法 |
|---|---|
| 路径穿越防护 | 所有 /files 接口先取 Path(name).name，再拼上传目录与语料目录 |
| 密钥不入库 | .env 被 .gitignore 忽略；打包脚本发现 .env 会直接中止 |
| 上传类型白名单 | 只接受 pdf/docx/md/txt，其余 400 |
| 上传内容校验 | 提取不到文本直接 400，避免空文件污染向量库 |
| 只读语料挂载 | docker-compose 中 materials 以 :ro 挂载 |

## 十四、版本清单

| 分类 | 版本 |
|---|---|
| 后端 | fastapi 0.150.0 / uvicorn 0.54.0 / pydantic 2.14.1 |
| 模型编排 | langchain 1.4.6 / langchain-core 1.6.12 / langchain-community 0.4.2 |
| 模型适配 | langchain-ollama 1.1.0 / langchain-openai 1.7.2 / ollama 0.6.3 |
| 文本切分 | langchain-text-splitters 1.1.3 |
| 向量与存储 | chromadb 1.5.9 / SQLite（标准库） |
| 文档处理 | pypdf 6.21.1 / pymupdf 1.28.2 / python-docx 1.2.0 |
| 数据处理 | numpy 2.5.4 / pandas 3.0.6（仅实验脚本） |
| 临时界面 | streamlit 1.66.0（ui_streamlit.py，备用） |
| 前端 | vue 3.5 / vite 7.1 / element-plus 2.11 / axios 1.13 |
| 运行环境 | Python 3.12.10 / Node 24.20.0 / Ollama 0.13.5 / Docker 29.9.2 |

## 附录：一次问答的完整技术路径

界面输入 → POST /api/chat/stream → Nginx/Vite 代理 → FastAPI → bge-m3 向量化 → Chroma 余弦 Top-5 → 噪声过滤 + 0.45 闸门 → 前 2 条拼提示词 → qwen2.5:7b 流式生成 → 按句清洗 → SSE 推送 → 写入 SQLite；点出处再请求 /files/{name}/highlight，PyMuPDF 标注并跳页。
