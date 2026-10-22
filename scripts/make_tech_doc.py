"""生成《技术栈说明》文档（docx + md 两个版本）。

内容全部来自仓库与环境实测（版本号取自 importlib.metadata / package.json / docker），
不是凭印象写的。
"""
from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

ROOT = Path(r"D:\ai-kb")
OUT_DOCX = ROOT / "docs" / "技术栈说明.docx"
OUT_MD = ROOT / "docs" / "tech-stack.md"

# ---------------------------------------------------------------- 事实数据
ENV_ROWS = [
    ("操作系统", "Windows 11（开发机），Linux 容器内运行", "Docker 与本地开发两套环境"),
    ("Python", "3.12.10 (AMD64)", "后端与脚本；容器镜像同为 3.12"),
    ("Node.js", "v24.20.0", "前端构建（Vite 7 要求 Node ≥ 20）"),
    ("npm", "11.19.0", "前端依赖管理"),
    ("Docker", "29.9.2 (build a82e528)", "容器化部署（T5.1）"),
    ("Ollama", "0.13.5", "本地模型运行时（生成 + 向量）"),
]

BACKEND_ROWS = [
    ("FastAPI", "0.150.0", "HTTP 接口框架，自动生成 OpenAPI 文档（/docs）", "同步路由 + 线程池，够用且代码量最小"),
    ("Uvicorn", "0.54.0", "ASGI 服务器，承载 FastAPI", "官方推荐搭配，容器内 --host 0.0.0.0"),
    ("Pydantic", "2.14.1", "请求/响应模型与字段校验", "FastAPI 原生集成，错误信息直接可用"),
    ("python-dotenv", "1.2.4", "读取 .env 配置", "配置外置，切换模型不改代码"),
    ("python-multipart", "随 FastAPI", "解析上传的 multipart 表单", "/upload 依赖"),
    ("httpx / requests", "0.28.1 / 2.34.2", "HTTP 客户端", "直连 Ollama 的 /api/embed 与健康检查"),
    ("SQLite (标准库)", "3.45+", "会话与消息持久化", "零运维、单文件，够本项目规模"),
]

AI_ROWS = [
    ("Ollama", "0.13.5", "本地模型运行时，提供 /api/generate、/api/chat、/api/embed", "免 GPU 运维，一条命令拉模型"),
    ("qwen2.5:7b", "4.4 GB", "默认生成模型（本地、免费、离线）", "中文效果好，6GB 显存可跑"),
    ("bge-m3", "1.2 GB / 1024 维", "向量模型，中文语义检索", "中文检索强，维度与语料规模匹配"),
    ("deepseek-chat", "云端 API", "云端生成模型（可切换）", "答案更自然、准确率更高，演示用"),
    ("deepseek-r1:7b", "4.4 GB", "本机另一可选生成模型", "验证「自动发现模型」功能"),
    ("LangChain", "1.4.6", "模型抽象、文本切分、向量库对接", "生态成熟，Ollama/OpenAI 一套接口"),
    ("langchain-core", "1.6.12", "BaseChatModel 等基础抽象", "get_llm 返回统一类型"),
    ("langchain-ollama", "1.1.0", "ChatOllama 适配器", "本地生成模型接入"),
    ("langchain-openai", "1.7.2", "ChatOpenAI 适配器（DeepSeek 兼容 OpenAI 协议）", "一行配置切云端"),
    ("langchain-community", "0.4.2", "Chroma 向量库封装", "与 LangChain 生态一致"),
    ("langchain-text-splitters", "1.1.3", "RecursiveCharacterTextSplitter", "按语义边界递归切分"),
    ("ollama (python sdk)", "0.6.3", "备用客户端", "调试与实验脚本使用"),
]

RAG_PARAMS = [
    ("切片长度 chunk_size", "512", "E1 实验：256/512/1024 对应召回 90.0%/90.0%/86.7%"),
    ("切片重叠 chunk_overlap", "50", "E4 实验：0/20/50 对应 83.3%/83.3%/90.0%"),
    ("检索条数 top_k", "5", "召回率按 Top-5 统计"),
    ("喂入上下文条数 answer_top_n", "2", "E5 实验：1/2/3 条对应准确率 70.0%/83.3%/76.7%"),
    ("相似度闸门 score_gate", "0.45", "低于此值走「资料中没有相关内容」"),
    ("上下文窗口 num_ctx", "2048", "6GB 显存下的平衡点，KV 缓存减半"),
    ("模型保活 keep_alive", "30m", "避免每次请求重载模型"),
]

STORAGE_ROWS = [
    ("ChromaDB", "1.5.9", "向量库，集合 ai-kb 共 8,895 条（另有 4 个实验集合）", "本地持久化、零服务端、支持 metadata 过滤"),
    ("SQLite 表 sessions", "id, created_at", "136 行：会话", "单文件、随项目走"),
    ("SQLite 表 messages", "id, session_id, role, content, sources, created_at", "274 行：消息含出处 JSON", "出处随消息保存，刷新可复原"),
    ("文件存储 materials/", "10 份 PDF，约 80 MB", "原始语料", "只读挂载进容器"),
    ("文件存储 data/uploads/", "运行时上传", "用户上传文件", "与语料同目录读取"),
    ("文件存储 data/tmp/", "运行时", "TEMP/TMP 重定向 + 高亮缓存", "规避低权限进程写系统临时目录失败"),
]

FRONTEND_ROWS = [
    ("Vue 3", "3.5", "组合式 API（setup）", "轻量、上手快、生态成熟"),
    ("Vite", "7.1", "开发服务器与构建（1657 模块，构建约 6s）", "冷启动快，HMR 好用"),
    ("Element Plus", "2.11", "上传、下拉框、消息气泡等组件", "中文文档完善，样式统一"),
    ("axios", "1.13", "普通请求封装", "错误处理方便"),
    ("fetch + 手写 SSE 解析", "浏览器原生", "/chat/stream 流式接收", "EventSource 不支持 POST，故手写解析"),
    ("Nginx", "1.27-alpine", "生产静态托管 + /api 反代", "官方镜像小，配置直观"),
]

DOCPROC_ROWS = [
    ("pypdf", "6.21.1", "PDF 文本提取（T1.1）", "纯 Python，无外部依赖"),
    ("PyMuPDF (fitz)", "1.28.2", "PDF 定位搜索 + 黄色高亮注释", "能拿到文字坐标，pypdf 做不到"),
    ("python-docx", "1.2.0", "DOCX 解析入库、DOCX 转 HTML 阅读视图", "官方库，稳定"),
    ("RecursiveCharacterTextSplitter", "1.1.3", "跨页切片，自定义重叠兜底", "先按段落/句号切，再按长度合并"),
]

DEPLOY_ROWS = [
    ("Docker", "29.9.2", "镜像构建与容器运行", "一次构建，到处运行"),
    ("docker compose", "v2", "编排 backend + frontend 两个服务", "一条命令起停"),
    ("python:3.12-slim", "179 MB", "后端基础镜像", "slim 版减少体积"),
    ("node:24-alpine", "—", "前端构建阶段", "与开发环境 Node 版本一致"),
    ("nginx:1.27-alpine", "—", "前端运行阶段", "体积小、配置简单"),
    ("requirements-docker.txt", "132 个包", "容器依赖（去掉 torch 等 13 个未使用重包）", "镜像从预计 4GB+ 降到 1.29GB"),
]

TEST_ROWS = [
    ("自建测试脚本", "tests/run_tests.py", "30 个用例：接口契约 10、安全边界 6、问答流式 6、纯函数与数据 8", "不引入 pytest，零依赖可跑"),
    ("质量评测", "scripts/evaluate.py", "30 题测试集：召回率、准确率、耗时", "一条命令出基线数字"),
    ("对照实验", "scripts/exp_*.py", "E1 切片长度、E4 重叠、E5 上下文条数、E6 本地vs云端、E7 拒答提示词", "每次只改一个变量"),
    ("环境自检", "scripts/check_env.py", "Ollama 可达性、模型是否齐全、向量库条数、前端依赖", "换设备一键诊断"),
    ("打包分发", "scripts/package.py", "源码包 0.7MB / 完整包 378MB", "内置拒绝打包 .env"),
]

VERSION_ROWS = [
    ("后端", "fastapi 0.150.0 / uvicorn 0.54.0 / pydantic 2.14.1"),
    ("模型编排", "langchain 1.4.6 / langchain-core 1.6.12 / langchain-community 0.4.2"),
    ("模型适配", "langchain-ollama 1.1.0 / langchain-openai 1.7.2 / ollama 0.6.3"),
    ("文本切分", "langchain-text-splitters 1.1.3"),
    ("向量与存储", "chromadb 1.5.9 / SQLite（标准库）"),
    ("文档处理", "pypdf 6.21.1 / pymupdf 1.28.2 / python-docx 1.2.0"),
    ("数据处理", "numpy 2.5.4 / pandas 3.0.6（仅实验脚本）"),
    ("临时界面", "streamlit 1.66.0（ui_streamlit.py，备用）"),
    ("前端", "vue 3.5 / vite 7.1 / element-plus 2.11 / axios 1.13"),
    ("运行环境", "Python 3.12.10 / Node 24.20.0 / Ollama 0.13.5 / Docker 29.9.2"),
]

MODEL_ROWS = [
    ("qwen2.5:7b", "4.4 GB", "本地生成（默认）", "免费、离线，答案偶尔偏公式化"),
    ("bge-m3:latest", "1.2 GB", "向量化（固定，不可切换）", "1024 维，换掉必须重建索引"),
    ("deepseek-chat", "云端", "云端生成（可选）", "更自然、准确率 86.7%，需联网与 Key"),
    ("deepseek-r1:7b", "4.4 GB", "本地生成（可选）", "用于验证模型切换功能"),
]

FLOW_STEPS = [
    ("1. 解析", "scripts/01_extract.py + pypdf", "PDF/DOCX/MD/TXT → 逐页纯文本，保留页码"),
    ("2. 切片", "scripts/02_chunk.py + RecursiveCharacterTextSplitter", "512 字/片、重叠 50 字，跨页片段记 page_start/page_end"),
    ("3. 向量化", "scripts/03_embed.py + bge-m3（Ollama）", "每片 → 1024 维向量"),
    ("4. 入库", "scripts/04_store.py + ChromaDB", "写入集合 ai-kb，id = source:page:序号:hash，同文本去重"),
    ("5. 检索", "app/rag.py retrieve()", "问题向量化 → 余弦检索 Top-5 → 噪声过滤 → 相似度闸门 0.45"),
    ("6. 生成", "app/llm.py + Ollama/DeepSeek", "Top-2 片段 + 规则提示词 → 流式生成答案"),
    ("7. 后处理", "rag.clean_answer / best_snippet", "去 LaTeX、按句清洗、出处摘要取最相关句"),
    ("8. 溯源", "GET /files/{name}/highlight", "PyMuPDF 定位命中句 → 黄色高亮 → 浏览器跳到该页"),
]

DECISIONS = [
    ("为什么用 Ollama 而不是直接调模型文件", "免去 GPU 环境与推理框架维护；一条命令换模型；embedding 与生成同一套运行时"),
    ("为什么 embedding 直连 /api/embed 而不走 LangChain", "实测 langchain_ollama 未把 keep_alive 传下去，模型被反复卸载，单次检索多花 2.2 秒"),
    ("为什么默认向量模型放 CPU", "6GB 显存装不下 qwen(4.4G)+bge-m3(1.2G)；本地生成时把显存让给生成模型，云端生成时再放回 GPU"),
    ("为什么用 Chroma 而不是 FAISS/Milvus", "需要持久化 + metadata 过滤 + 零服务端；8,895 条规模远未到 Milvus 的必要门槛"),
    ("为什么 SQLite", "会话量级小，单文件便于随项目迁移，无需额外服务"),
    ("为什么前端有 Vue 还保留 Streamlit", "Streamlit 是计划书里的临时界面（T3.1），用于快速验证后端，Vue 是产品界面"),
    ("为什么切句而不是直接截 100 字做出处摘要", "直接截取会从单词中间断开且常截到代码行，按句+相关度挑选后可读性明显更好"),
]

NOT_USED = [
    ("模型微调 / LoRA", "计划书「不做」清单：本项目聚焦 RAG 工程链路，微调不产生额外工程价值"),
    ("云端向量数据库（Pinecone 等）", "数据量小且要求离线可用，引入外部服务反而增加故障面"),
    ("重排序模型（bge-reranker）", "列为 T6.1 的 E2 实验，需要额外拉模型，尚未执行"),
    ("多模态 / OCR", "语料 PDF 文字层 100% 覆盖（T0.2 实测），OCR 无必要（T1.9 已取消）"),
    ("Kubernetes / 服务网格", "单机两容器，compose 足够"),
]

SECURITY = [
    ("路径穿越防护", "所有 /files 接口先取 Path(name).name，再拼上传目录与语料目录"),
    ("密钥不入库", ".env 被 .gitignore 忽略；打包脚本发现 .env 会直接中止"),
    ("上传类型白名单", "只接受 pdf/docx/md/txt，其余 400"),
    ("上传内容校验", "提取不到文本直接 400，避免空文件污染向量库"),
    ("只读语料挂载", "docker-compose 中 materials 以 :ro 挂载"),
]


# ---------------------------------------------------------------- DOCX 生成
def set_east_asia(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def add_table(doc: Document, headers: list[str], rows: list[tuple], widths: list[float] | None = None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False          # 关掉自动调整，否则显式列宽会被覆盖
    # 表头在跨页时重复
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        run = hdr[i].paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(9.5)
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(val))
            run.font.size = Pt(9)
    if widths:
        # 每一行都要设，否则 LibreOffice/Word 会按内容重排
        for row in table.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    # 一行不跨页拆分（否则半行落在下一页很难看）
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        cant.set(qn("w:val"), "true")
        tr_pr.append(cant)
    doc.add_paragraph()
    return table


def build_docx() -> None:
    doc = Document()
    set_east_asia(doc)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(2.2)
        section.left_margin = section.right_margin = Cm(2.4)

    title = doc.add_heading("AI 学习资料知识库 · 技术栈说明", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph("v1.0 · 2026-10-23 · 基于仓库与运行环境实测整理")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.runs[0].font.size = Pt(9)
    sub.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    doc.add_heading("一、总体架构", level=1)
    doc.add_paragraph(
        "本项目是一条完整的 RAG（检索增强生成）链路：把 10 份 AI 学习资料（PDF/Word/Markdown/文本）"
        "解析、切片、向量化后存入本地向量库；用户提问时先检索最相关的片段，再交给大模型生成带出处的答案。"
        "前端是 Vue3 单页应用，后端是 FastAPI，模型由 Ollama 在宿主机提供，也可一行配置切到 DeepSeek 云端。"
    )
    add_table(doc, ["层", "技术", "职责"], [
        ("表现层", "Vue 3 + Vite + Element Plus + Nginx", "问答界面、文件管理、模型选择、出处跳转"),
        ("接口层", "FastAPI + Pydantic + Uvicorn", "12 个 REST/SSE 接口"),
        ("业务层", "RAG 管线（解析/切片/检索/生成/溯源）", "app/rag.py 等 7 个模块"),
        ("模型层", "Ollama（qwen2.5:7b / bge-m3）；DeepSeek API", "生成与向量化"),
        ("存储层", "ChromaDB + SQLite + 文件系统", "向量、会话、原始语料"),
        ("交付层", "Docker + docker compose", "两个容器一键起停"),
    ], widths=[2.6, 6.4, 7.5])

    doc.add_heading("二、运行环境与工具链", level=1)
    add_table(doc, ["项", "版本", "说明"], ENV_ROWS, widths=[3.4, 4.6, 8.4])

    doc.add_heading("三、后端技术", level=1)
    add_table(doc, ["技术", "版本", "用途", "选型说明"], BACKEND_ROWS, widths=[3.0, 2.2, 5.5, 5.5])
    doc.add_paragraph(
        "后端共 12 个接口：/health、/providers、/upload、/chat、/chat/stream、/files、/files/{name}（删除）、"
        "/files/{name}/raw、/files/{name}/view、/files/{name}/highlight、/sessions、/sessions/{id}。"
        "其中 /chat/stream 用 SSE 返回，事件顺序为 sources → token（多次）→ done。"
    )

    doc.add_heading("四、AI 与模型层", level=1)
    add_table(doc, ["技术", "版本/规格", "用途", "说明"], AI_ROWS, widths=[3.2, 2.6, 5.2, 5.2])
    doc.add_heading("4.1 可切换的生成模型", level=2)
    add_table(doc, ["模型", "体积", "角色", "特点"], MODEL_ROWS, widths=[3.4, 2.0, 4.2, 6.6])
    doc.add_paragraph(
        "生成模型可切换：.env 只提供默认值，界面上的「回答模型」下拉框会自动列出本机 Ollama 已下载的"
        "所有生成模型（自动排除向量模型），选中后随请求下发 provider 与 model，无需重启。"
    )
    doc.add_heading("4.2 向量模型为什么固定", level=2)
    doc.add_paragraph(
        "向量库是用 bge-m3 的 1024 维向量建立的（8,895 条）。换成别的 embedding 模型，语义空间与维度都变了，"
        "必须重建索引，所以下拉框里不提供向量模型选项。"
    )

    doc.add_heading("五、RAG 管线与核心参数", level=1)
    add_table(doc, ["步骤", "实现", "产物"], FLOW_STEPS, widths=[2.2, 6.4, 7.6])
    doc.add_heading("5.1 关键参数（均可在 .env 覆盖）", level=2)
    add_table(doc, ["参数", "取值", "依据"], RAG_PARAMS, widths=[4.6, 2.2, 9.4])
    doc.add_heading("5.2 三个工程细节", level=2)
    doc.add_paragraph(
        "① 切片重叠兜底：LangChain 对超长单行（PDF 常见）会把重叠退化为 0，因此额外实现了 _enforce_overlap，"
        "保证每个片段不超过 512 字且与上一片重叠不少于 50 字。", style="List Bullet")
    doc.add_paragraph(
        "② 双保险拒答：相似度闸门（0.45）先拦一层，提示词再要求「资料没有直接回答问题就输出资料中没有相关内容」。"
        "四版提示词对比后采用平衡版，无关问题拒答 5/5，30 题准确率 76.7%。", style="List Bullet")
    doc.add_paragraph(
        "③ 输出自然语言：提示词禁止 LaTeX 与上下标写法，另加 clean_answer() 兜底清洗，流式按句清洗后再推送。",
        style="List Bullet")

    doc.add_heading("六、数据存储", level=1)
    add_table(doc, ["技术", "规格", "内容", "说明"], STORAGE_ROWS, widths=[3.2, 3.4, 5.4, 4.2])

    doc.add_heading("七、前端技术", level=1)
    add_table(doc, ["技术", "版本", "用途", "说明"], FRONTEND_ROWS, widths=[3.6, 2.4, 5.6, 5.2])
    doc.add_paragraph("前端两个关键交互：")
    doc.add_paragraph(
        "① 模型选择：调用 /providers 拿到本机已下载模型 + 云端模型，选中后把 provider/model 一起发往后端。",
        style="List Bullet")
    doc.add_paragraph(
        "② 出处定位：点击任一出处，请求 /files/{name}/highlight?page=N&q=片段&question=问题，"
        "后端在该页搜索并按相关度排序句子、打黄色高亮，返回 PDF 并跳到对应页。", style="List Bullet")

    doc.add_heading("八、文档处理技术", level=1)
    add_table(doc, ["库", "版本", "用途", "说明"], DOCPROC_ROWS, widths=[3.8, 2.2, 5.4, 4.8])

    doc.add_heading("九、部署与运维", level=1)
    add_table(doc, ["技术", "版本/规格", "用途", "说明"], DEPLOY_ROWS, widths=[4.0, 3.2, 5.0, 4.0])
    doc.add_paragraph(
        "实测（2026-10-22）：后端镜像 1.29 GB、容器 healthy；挂载 data 后容器内读到 8,895 条向量，"
        "重启容器后仍在；经 Nginx 反代上传、问答、流式、删除全部通过；容器内 PDF 高亮 8 个注释、1.2 秒。"
        "国内无法直连 Docker Hub 时，可用环境变量覆盖 BASE_IMAGE / NODE_IMAGE / NGINX_IMAGE 走镜像站。"
    )

    doc.add_heading("十、测试与质量保障", level=1)
    add_table(doc, ["工具/脚本", "规模", "内容", "说明"], TEST_ROWS, widths=[3.4, 3.0, 5.6, 4.2])
    doc.add_paragraph(
        "质量基线（30 题测试集，data/testset.csv）：召回率 90.0%（27/30）、答案准确率 76.7%（24/30，"
        "自动初判）、无关问题拒答 5/5；云端 deepseek-chat 同题准确率 86.7%；热态首字节 1.2 秒、整轮 3.6 秒。"
    )

    doc.add_heading("十一、技术选型理由", level=1)
    add_table(doc, ["问题", "结论"], DECISIONS, widths=[6.4, 10.4])

    doc.add_heading("十二、明确未采用的技术", level=1)
    add_table(doc, ["未采用", "原因"], NOT_USED, widths=[5.4, 11.4])

    doc.add_heading("十三、工程与安全实践", level=1)
    add_table(doc, ["实践", "做法"], SECURITY, widths=[4.4, 12.4])

    doc.add_heading("十四、版本清单", level=1)
    add_table(doc, ["分类", "版本"], VERSION_ROWS, widths=[4.4, 12.4])

    doc.add_heading("附录：一次问答的完整技术路径", level=1)
    doc.add_paragraph(
        "用户在 Vue 界面输入问题 → axios/fetch 发起 POST /api/chat/stream → Nginx（或 Vite 代理）转发到 "
        "FastAPI → rag.retrieve() 用 bge-m3 把问题转成 1024 维向量 → ChromaDB 余弦检索 Top-5 → "
        "过滤噪声片段并按 0.45 闸门判断 → 取前 2 条拼进提示词 → ChatOllama 调用 qwen2.5:7b 流式生成 → "
        "按句清洗 LaTeX 后通过 SSE 推送 → 同时把答案与出处写入 SQLite → 前端渲染气泡与出处卡片；"
        "点击出处时再请求 /files/{name}/highlight，由 PyMuPDF 在原 PDF 上标注并跳页。"
    )

    # 标题不与正文分离（避免标题孤零零落在页面底部）
    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            para.paragraph_format.keep_with_next = True

    doc.save(OUT_DOCX)


# ---------------------------------------------------------------- Markdown
def build_md() -> None:
    def tbl(headers, rows):
        out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
        for r in rows:
            out.append("| " + " | ".join(str(x) for x in r) + " |")
        return "\n".join(out)

    md = [
        "# AI 学习资料知识库 · 技术栈说明\n",
        "> v1.0 · 2026-10-23 · 基于仓库与运行环境实测整理\n",
        "## 一、总体架构\n",
        "本项目是一条完整的 RAG（检索增强生成）链路：把 10 份 AI 学习资料解析、切片、向量化后存入本地向量库；"
        "提问时先检索最相关片段，再交给大模型生成带出处的答案。\n",
        tbl(["层", "技术", "职责"], [
            ("表现层", "Vue 3 + Vite + Element Plus + Nginx", "问答界面、文件管理、模型选择、出处跳转"),
            ("接口层", "FastAPI + Pydantic + Uvicorn", "12 个 REST/SSE 接口"),
            ("业务层", "RAG 管线", "app/rag.py 等 7 个模块"),
            ("模型层", "Ollama + DeepSeek", "生成与向量化"),
            ("存储层", "ChromaDB + SQLite + 文件系统", "向量、会话、原始语料"),
            ("交付层", "Docker + docker compose", "两个容器一键起停"),
        ]),
        "\n## 二、运行环境\n",
        tbl(["项", "版本", "说明"], ENV_ROWS),
        "\n## 三、后端技术\n",
        tbl(["技术", "版本", "用途", "选型说明"], BACKEND_ROWS),
        "\n## 四、AI 与模型层\n",
        tbl(["技术", "版本/规格", "用途", "说明"], AI_ROWS),
        "\n### 4.1 可切换的生成模型\n",
        tbl(["模型", "体积", "角色", "特点"], MODEL_ROWS),
        "\n### 4.2 向量模型为什么固定\n",
        "向量库是用 bge-m3 的 1024 维向量建立的（8,895 条）。换 embedding 模型必须重建索引，故不提供选项。\n",
        "\n## 五、RAG 管线与核心参数\n",
        tbl(["步骤", "实现", "产物"], FLOW_STEPS),
        "\n### 5.1 关键参数\n",
        tbl(["参数", "取值", "依据"], RAG_PARAMS),
        "\n### 5.2 三个工程细节\n",
        "- 切片重叠兜底：额外实现 `_enforce_overlap`，保证 ≤512 字且重叠 ≥50（LangChain 对超长单行会退化为 0）\n"
        "- 双保险拒答：相似度闸门 0.45 + 提示词规则；四版提示词对比后采用平衡版，拒答 5/5、准确率 76.7%\n"
        "- 输出自然语言：禁止 LaTeX + `clean_answer()` 兜底 + 流式按句清洗\n",
        "\n## 六、数据存储\n",
        tbl(["技术", "规格", "内容", "说明"], STORAGE_ROWS),
        "\n## 七、前端技术\n",
        tbl(["技术", "版本", "用途", "说明"], FRONTEND_ROWS),
        "\n## 八、文档处理\n",
        tbl(["库", "版本", "用途", "说明"], DOCPROC_ROWS),
        "\n## 九、部署与运维\n",
        tbl(["技术", "版本/规格", "用途", "说明"], DEPLOY_ROWS),
        "\n## 十、测试与质量\n",
        tbl(["工具/脚本", "规模", "内容", "说明"], TEST_ROWS),
        "\n## 十一、技术选型理由\n",
        tbl(["问题", "结论"], DECISIONS),
        "\n## 十二、明确未采用的技术\n",
        tbl(["未采用", "原因"], NOT_USED),
        "\n## 十三、工程与安全实践\n",
        tbl(["实践", "做法"], SECURITY),
        "\n## 十四、版本清单\n",
        tbl(["分类", "版本"], VERSION_ROWS),
        "\n## 附录：一次问答的完整技术路径\n",
        "界面输入 → POST /api/chat/stream → Nginx/Vite 代理 → FastAPI → bge-m3 向量化 → Chroma 余弦 Top-5 → "
        "噪声过滤 + 0.45 闸门 → 前 2 条拼提示词 → qwen2.5:7b 流式生成 → 按句清洗 → SSE 推送 → 写入 SQLite；"
        "点出处再请求 /files/{name}/highlight，PyMuPDF 标注并跳页。\n",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    build_docx()
    build_md()
    print("生成:", OUT_DOCX, OUT_DOCX.stat().st_size // 1024, "KB")
    print("生成:", OUT_MD, OUT_MD.stat().st_size // 1024, "KB")
