"""生成《技术点详解》Word 文档（附 Markdown 版）。

每个技术点统一按六段展开：
  它是什么 → 在本项目里做什么 → 关键机制 → 选型对比 → 踩过的坑 → 面试怎么答
内容取自本项目真实代码与实测结果。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(r"D:\ai-kb")
OUT_DOCX = ROOT / "docs" / "技术点详解.docx"
OUT_MD = ROOT / "docs" / "tech-details.md"

GREY = RGBColor(0x66, 0x66, 0x66)
BLUE = RGBColor(0x1F, 0x4E, 0x79)

# ---------------------------------------------------------------- 内容
# 每个技术点：序号、名称、版本、一句话定位、是什么、在本项目做什么、
# 关键机制[]、选型对比[(方案, 优点, 缺点)]、踩坑[]、问答[(Q, A)]
POINTS: list[dict] = []


def pt(no, name, ver, tagline, what, here, mech, options, pits, qa):
    POINTS.append(dict(no=no, name=name, ver=ver, tagline=tagline, what=what, here=here,
                      mech=mech, options=options, pits=pits, qa=qa))


# ============================ 第一章 接口层 ============================
pt(
    1, "FastAPI", "0.150.0",
    "整个后端就是一套 FastAPI 路由：12 个接口撑起上传、问答、流式、文件、历史五类能力。",
    "FastAPI 是基于 Python 类型注解的 Web 框架。你写普通函数，加上 @app.get/@app.post 装饰器，"
    "它就用 Pydantic 自动校验入参、序列化返回值，并生成一份可视化的 OpenAPI 文档。",
    "所有接口都在 app/main.py：/health、/providers、/upload、/chat、/chat/stream、"
    "/files（含删除、raw、view、highlight）、/sessions。启动命令是 python -m app.main，"
    "容器里则用 uvicorn app.main:app --host 0.0.0.0。",
    [
        "路径参数与查询参数自动解析：/files/{name}/highlight?page=434&q=... 直接映射到函数形参。",
        "请求体用 Pydantic 模型声明（ChatRequest），字段缺失或类型错会返回 422，不用手写校验。",
        "流式响应用 StreamingResponse + 生成器，配合 media_type=text/event-stream 实现 SSE。",
        "文件下载用 FileResponse，可以指定 media_type 与 content_disposition_type=inline。",
        "异常用 HTTPException 抛出，前端拿到统一的 {detail: ...} 结构。",
    ],
    [
        ("FastAPI（选用）", "类型驱动、自动文档、原生异步、SSE/文件响应都现成", "生态比 Flask 年轻"),
        ("Flask", "最灵活、教程多", "校验、文档、异步都要自己加"),
        ("Django REST", "全功能、带 ORM 与后台", "对一个小服务过重"),
    ],
    [
        "文件接口最初只写了 GET /files/{name} 的删除逻辑，后来加 /raw、/view、/highlight 三个子路径，"
        "注意删除是 DELETE /files/{name}，子路径是 GET，两者不冲突但要保持顺序清晰。",
        "流式接口一定要返回 StreamingResponse 而不是普通 JSON，否则前端拿不到逐字效果。",
    ],
    [
        ("为什么选 FastAPI 而不是 Flask？", "项目要的是「接口 + 自动校验 + 流式」，FastAPI 三样都原生支持；"
                                             "而且类型注解本身就是文档，节省维护成本。"),
        ("FastAPI 的异步对你项目有帮助吗？", "有，但不是决定性。真正的并发瓶颈在模型推理，"
                                             "所以我用同步路由 + 线程池，让耗时操作不阻塞事件循环；"
                                             "流式接口用生成器逐段 yiel，避免一次生成完再返回。"),
    ],
)

pt(
    2, "Uvicorn", "0.54.0",
    "真正监听端口、跑 FastAPI 应用的那个 ASGI 服务器。",
    "Uvicorn 是 ASGI 服务器，负责接收 HTTP 请求、把请求交给 FastAPI 应用、再把响应写回客户端。"
    "FastAPI 只是「应用」，需要一个服务器来运行它。",
    "本地用 python -m app.main 启动（内部起 uvicorn）；Dockerfile 的 CMD 是 "
    "uvicorn app.main:app --host 0.0.0.0 --port 8000，容器内必须监听 0.0.0.0 才能被宿主机访问。",
    [
        "单进程单事件循环即可支撑本项目（个人知识库，非高并发）。",
        "SSE 依赖长连接，uvicorn 默认不缓冲响应，配合 Nginx 关闭 proxy_buffering 才能逐字到达浏览器。",
        "启动时执行 @app.on_event('startup') 里的预热线程（保活模型），不阻塞服务启动。",
    ],
    [
        ("Uvicorn（选用）", "轻量、ASGI 原生、与 FastAPI 官方搭配", "多进程需配 gunicorn/多 worker"),
        ("Hypercorn", "支持 HTTP/2", "生态与文档不如 uvicorn"),
        ("Gunicorn + uvicorn worker", "多进程、适合生产高并发", "本项目单用户，属过度设计"),
    ],
    [
        "最初用 python app/main.py 直接跑，热重载和日志都很简陋；改成模块启动后统一了入口。",
        "容器里忘了 --host 0.0.0.0，宿主机访问不到，排查了一阵才想到是只听 127.0.0.1。",
    ],
    [
        ("为什么容器里必须 0.0.0.0？", "容器有自己的网络命名空间，127.0.0.1 指的是容器自己；"
                                    "监听 0.0.0.0 才能通过端口映射被外部访问。"),
        ("为什么不用多 worker？", "模型推理本身是串行的，多 worker 只会让显存/内存竞争更严重；"
                                  "单 worker + 预热常驻反而延迟更稳。"),
    ],
)

pt(
    3, "Pydantic", "2.14.1",
    "定义请求体的形状，顺便把「问题不能为空」这类校验做在入口处。",
    "Pydantic 用 Python 类型注解定义数据模型，运行时校验并转换。FastAPI 把它用作请求/响应契约。",
    "app/main.py 里的 ChatRequest：question（最少 1 个字符）、session_id、history、provider、model。"
    "任何一个字段类型不对，FastAPI 直接返回 422，业务代码不用再判空。",
    [
        "Field(min_length=1) 保证空问题在入口被拦掉（实测返回 400/422）。",
        "provider 与 model 都是 Optional，留空就用 .env 默认值，这让「界面切模型」不需要改配置。",
        "Pydantic v2 用 Rust 重写核心，校验比 v1 快很多，本项目无感但要写对语法（如 field_validator）。",
    ],
    [
        ("Pydantic（选用）", "与 FastAPI 无缝、错误信息友好、v2 性能好", "复杂嵌套模型学习曲线略陡"),
        ("marshmallow", "老牌、生态广", "需单独集成，FastAPI 不原生支持"),
        ("手工 if 校验", "零依赖", "字段一多就散落各处，容易漏"),
    ],
    [
        "把 「question: str」 写成必填后，前端传空格仍然通过（min_length=1 允许空格），"
        "所以业务层额外做了 strip 判空，返回「问题不能为空」。",
    ],
    [
        ("为什么要用模型而不是直接收 dict？", "模型把契约写在代码里：字段名、类型、默认值一目了然，"
                                          "而且自动生成文档与 422 错误。"),
        ("Optional 字段和默认值有什么区别？", "Optional 只表示可以为 None，默认值决定不传时的行为；"
                                          "本项目 provider/model 是「可以不传，传了就用」，所以是 Optional + 默认 None。"),
    ],
)

pt(
    4, "SSE（Server-Sent Events）", "浏览器原生",
    "让答案一个字一个字冒出来，而不是等十秒后一次性弹出。",
    "SSE 是一种基于 HTTP 长连接的服务器推送技术：服务端持续往同一个响应里写 "
    "event: 事件名 / data: 数据 的文本块，浏览器逐块接收。相比 WebSocket 更简单，单向即可。",
    "POST /chat/stream 就是 SSE：先发一条 event: sources（出处列表），再连发多条 event: token（文本片段），"
    "最后 event: done（带 session_id）。前端用 fetch 读流并手写解析。",
    [
        "事件格式：event: token\\ndata: \"文本\"\\n\\n，data 里放 JSON 可避免换行破坏协议。",
        "前端不能用 EventSource，因为它只支持 GET；所以用 fetch + ReadableStream 手工切分。",
        "Nginx 必须 proxy_buffering off，否则 Nginx 攒够缓冲区才转发，流式变成「一次性」。",
        "回答按句子边界聚合后再推送，既能清洗 LaTeX，又保留「逐句出现」的观感。",
    ],
    [
        ("SSE（选用）", "实现简单、HTTP 原生、断线可重连", "单向，客户端不能中途发消息"),
        ("WebSocket", "双向、实时", "握手与心跳复杂，本项目只需要服务端推送"),
        ("轮询", "最简单", "延迟高、请求多"),
    ],
    [
        "一开始用 LangChain 的 stream 直接逐 token 发，结果 LaTeX 标记被拆到多个 token 里，清洗后仍残留反斜杠；"
        "改成按句缓冲、整句清洗后再发才干净。",
        "Nginx 默认开启缓冲，本地 Vite 代理正常但容器部署后变「一次性返回」，加 proxy_buffering off 解决。",
    ],
    [
        ("SSE 和 WebSocket 怎么选？", "只需要服务端单向推送（生成过程）时选 SSE：协议简单、能复用现有 HTTP 鉴权、"
                                    "断线由浏览器自动重连；需要双向交互才用 WebSocket。"),
        ("流式输出要注意什么？", "三件事：服务端不缓冲（Nginx/代理）、事件格式规范（data 用 JSON）、"
                               "以及「半句话」问题——按句聚合能避免用户看到被切断的标记。"),
    ],
)

# ============================ 第二章 模型层 ============================
pt(
    5, "Ollama", "0.13.5",
    "本地模型的运行底座：一条命令拉模型、一个 HTTP 接口做推理。",
    "Ollama 是本地大模型运行时。它负责下载模型权重、管理显存与上下文、对外提供 /api/generate、"
    "/api/chat、/api/embed 等 HTTP 接口。对上层来说，它就是「本机的模型服务器」。",
    "本项目所有本地推理都走它：生成用 /api/chat（经 ChatOllama），向量化用 /api/embed（自写 "
    "OllamaEmbedder 直连），模型保活用 /api/generate + num_predict=0。容器部署时不进容器，"
    "而是通过 host.docker.internal:11434 访问宿主机上的 Ollama。",
    [
        "keep_alive 控制模型驻留时长：默认 5 分钟卸载，重载 7B 模型要十几秒，所以设成 30m 并加保活线程。",
        "/api/tags 列出本机已有模型——「界面自动发现模型」就是读这个接口。",
        "/api/ps 显示当前驻留模型与显存占用，是排查显存问题的关键工具。",
        "num_gpu 决定模型放 GPU 还是 CPU：6GB 显存装不下两个模型时，把 embedding 放 CPU。",
        "num_ctx 决定上下文窗口：2048 比 4096 的 KV 缓存小一半，实测整轮 5.3s → 2.9s。",
    ],
    [
        ("Ollama（选用）", "免 GPU 运维、一条命令换模型、HTTP 接口统一", "高并发能力弱，适合单机"),
        ("vLLM / TGI", "吞吐高、适合服务化", "部署复杂，6GB 显存跑 7B 收益不明显"),
        ("llama.cpp 直接调用", "最底层、可控", "要自己管模型加载与批处理"),
    ],
    [
        "keep_alive 对 embeddings 接口不生效：设了 30m，bge-m3 仍被卸载，每次检索重载 2.2 秒。"
        "最后是自写 OllamaEmbedder 直连 /api/embed 并显式下发 keep_alive 才解决。",
        "保活线程原来用 llm.invoke('ping')，会覆盖 Ollama 的 prompt 缓存，导致真实请求首 token 从 0.5s 掉到 3.5s；"
        "改成 num_predict=0 的空 generate 调用后恢复。",
        "bge-m3 对某些 token 会返回 500 NaN（实测 `sequence.` 触发），加了「逐词缩短重试」兜底。",
    ],
    [
        ("为什么要 keep_alive？", "模型卸载后重新加载 7B 要 10–20 秒，用户首次提问会卡死；"
                              "保活能把热态首 token 稳在 1.2 秒左右。"),
        ("6GB 显存怎么同时跑两个模型？", "跑不了。所以按场景分配：本地生成时 embedding 放 CPU 把显存让给 qwen；"
                                    "切云端生成时本机不跑生成模型，embedding 再放回 GPU。"),
    ],
)

pt(
    6, "qwen2.5:7b", "4.4 GB",
    "默认的本地生成模型：免费、离线，30 题准确率 76.7%。",
    "通义千问 2.5 的 7B 参数版本，量化后约 4.4GB，中文理解与指令遵循在同规模里表现稳定。",
    "默认生成模型（.env 的 OLLAMA_MODEL）。通过 ChatOllama 接入，temperature=0 保证可复现，"
    "num_ctx=2048，keep_alive=30m。界面上也可以临时切到 deepseek-r1:7b 或云端模型。",
    [
        "temperature=0：同一问题多次结果基本一致，便于评测与复现。",
        "7B 的短板是「照抄原文」：即使提示词禁止 LaTeX，复杂公式仍会带出 x_i、R^d 这类写法。",
        "答案质量对上下文条数敏感：喂 2 条比 3 条更准（83.3% vs 76.7%），说明第 3 条多是噪声。",
    ],
    [
        ("qwen2.5:7b（选用）", "中文好、6GB 显存可跑、免费离线", "复杂公式与长答案偶有偏差"),
        ("deepseek-r1:7b", "推理链更强，适合数学/逻辑", "输出啰嗦、更慢，本机上答得不如 qwen 贴合资料"),
        ("llama3.1:8b", "英文强、生态广", "中文资料问答略逊"),
    ],
    [
        "同一批 30 题，本地 qwen 准确率 76.7%，云端 deepseek-chat 86.7%——差距主要在「按资料组织语言」而不是检索，"
        "因为两者召回率都是 90.0%。",
    ],
    [
        ("为什么用 7B 而不是更大的模型？", "硬件是 6GB 显存，7B 量化后刚好能跑且留出 KV 缓存空间；"
                                     "再大一档就得上云端或换机器。"),
        ("本地和云端差距多大？", "同一检索、同一 30 题：本地 76.7%、云端 86.7%；整轮耗时 3.6s vs 2.0s。"
                             "差距在生成质量，不在检索。"),
    ],
)

pt(
    7, "bge-m3", "1.2 GB / 1024 维",
    "把中文问题与文档片段变成向量，是整个检索的地基。",
    "BAAI 出品的中文 embedding 模型，支持多语言、长文本，输出 1024 维向量。语义相近的文本向量距离近。",
    "所有入库与检索都用它：切片入库时批量向量化（8,895 条），提问时把问题向量化。"
    "通过自写的 OllamaEmbedder 直连 Ollama 的 /api/embed。",
    [
        "余弦距离检索：Chroma 里配置 hnsw:space=cosine，相似度 = 1 - 距离。",
        "1024 维是硬约束：换模型（尤其换维度）必须重建全部索引，所以界面上不提供切换。",
        "中文语料下，问题与片段的相似度通常在 0.45–0.65；低于 0.45 基本是无关内容。",
        "批量入库时单条失败会退化逐条重试，避免一条坏数据拖垮整批。",
    ],
    [
        ("bge-m3（选用）", "中文检索强、1024 维、Ollama 可直接跑", "比小模型慢一点"),
        ("text-embedding-3（OpenAI）", "效果好、免运维", "要联网与费用，且数据出网"),
        ("bge-small（384 维）", "快、体积小", "中文检索精度下降，原定的 E3 实验未执行"),
    ],
    [
        "个别 token 会让 bge-m3 返回 500（NaN），复现到是 `sequence.` 这类片段；解决方式是失败后逐词缩短重试。",
        "换 embedding 模型必须重建索引这条，最初没意识到，设计界面切换时差点让用户把向量库搞废。",
    ],
    [
        ("为什么检索指标和生成模型无关？", "因为召回率只取决于 embedding + 向量库；本地和云端共用同一份 8,895 条向量，"
                                     "所以召回都是 90.0%。"),
        ("相似度 0.55 算高吗？", "在中文长文档里 0.5–0.6 已经是强相关；0.45 是闸门，"
                              "低于它的片段基本答非所问，实测无关问题最高也只有 0.48。"),
    ],
)

pt(
    8, "DeepSeek API", "deepseek-chat / 云端",
    "可切换的云端生成模型：答案更自然、准确率 86.7%、整轮 1–2 秒。",
    "DeepSeek 提供 OpenAI 兼容的 Chat Completions 接口，所以能直接用 langchain-openai 的 ChatOpenAI 接入，"
    "只需改 base_url 与 api_key。",
    "app/llm.py 的 get_llm()：当 provider=deepseek 时返回 ChatOpenAI(model=deepseek-chat, "
    "base_url=https://api.deepseek.com)。界面上选中「云端 deepseek-chat」时按请求下发 provider/model。",
    [
        "OpenAI 兼容协议意味着不用写新适配器，换模型只是换 base_url。",
        "准确率 86.7%（26/30）比本地高 6.7 个百分点，整轮 1.1–2.0 秒。",
        "与本地模式的差异只在生成：召回率同为 90.0%。",
        "Key 只放在 .env（已被 .gitignore 忽略），打包脚本发现 .env 会直接中止。",
    ],
    [
        ("DeepSeek（选用）", "中文好、便宜、OpenAI 兼容、国内直连", "需联网并消耗 token"),
        ("OpenAI GPT-4o", "效果最好", "成本高、需外网"),
        ("本地更大模型", "数据不出网", "6GB 显存跑不动"),
    ],
    [
        "云端模式下后端仍在保活本地 qwen（白占 4.4GB 显存，把 bge-m3 挤出 GPU），"
        "修成「只有 provider=ollama 时才保活聊天模型」。",
        "云端未配置有效 Key 时不应让界面崩：/providers 会把它标成不可用，下拉框置灰。",
    ],
    [
        ("云端模式要注意什么？", "一是别在本机白占显存去保活用不到的模型；二是 Key 必须只落在 .env；"
                             "三是切换要能在请求级别完成，不要重启服务。"),
        ("为什么演示建议切云端？", "答案更自然（不会蹦 LaTeX）、准确率高 6.7 个点、整轮快一倍，"
                              "而检索用的向量库完全一样。"),
    ],
)

pt(
    9, "LangChain", "1.4.6 / core 1.6.12",
    "模型与向量库的适配层：让「换模型」只改一个文件。",
    "LangChain 是一套 LLM 应用开发框架，提供统一的模型接口（BaseChatModel）、文本切分器、"
    "向量库封装等。它的价值在于把不同厂商的差异收敛到适配器里。",
    "app/llm.py 用 ChatOllama 与 ChatOpenAI 两个适配器，对外统一返回 BaseChatModel；"
    "app/rag.py 用 RecursiveCharacterTextSplitter 切分；向量库用 langchain_community 的 Chroma 封装。",
    [
        "统一接口的价值：rag.py 里只写 get_llm(...).stream(prompt)，不关心背后是 Ollama 还是 DeepSeek。",
        "适配器也有代价：langchain_ollama 的 embeddings 没把 keep_alive 传下去，最后只能绕过它自己实现。",
        "切分器 RecursiveCharacterTextSplitter 会按分隔符优先级递归切，但遇到超长单行时重叠会退化为 0。",
    ],
    [
        ("LangChain（选用）", "生态成熟、适配器多、切分与向量库封装省事", "抽象层层层嵌套，出问题时要读源码"),
        ("LlamaIndex", "更偏索引与检索策略", "本项目切片策略简单，用不上其复杂索引"),
        ("直接调各家 SDK", "最直接、可控", "换模型要改业务代码"),
    ],
    [
        "LangChain 的 Chroma 封装会打出 Deprecation 警告（建议用 langchain-chroma），不影响功能，"
        "但日志里每次都刷一条，最后选择容忍而不是再引入一个包。",
        "重叠退化为 0 的问题：不能只信框架，自己写了 _enforce_overlap 兜底。",
    ],
    [
        ("LangChain 在你项目里做了什么？", "三件事：模型适配（Ollama/DeepSeek 一套接口）、文本切分、"
                                        "向量库封装。但它不是黑盒，出问题时我直接绕过它调 HTTP 接口。"),
        ("什么时候不该用框架？", "当你只需要一两个能力却要引入整层抽象时。"
                              "比如 embedding，我最后就是自己写的 40 行 HTTP 客户端，反而更快更稳。"),
    ],
)

# ============================ 第三章 检索与存储 ============================
pt(
    10, "ChromaDB", "1.5.9",
    "8,895 条向量存在本地一个目录里，余弦检索 Top-5 只要 0.2 秒。",
    "Chroma 是嵌入式向量数据库：不需要起服务，数据落在本地目录（SQLite + 索引文件），"
    "支持按 metadata 过滤与余弦/欧氏距离。",
    "data/chroma 目录是向量库，集合 ai-kb 存 8,895 条；另有 4 个实验集合（exp-256/1024/ov0/ov20）"
    "对应不同切片参数。检索走 similarity_search_with_score(k=5)，距离转相似度 = 1 - 距离。",
    [
        "cosine 空间：collection 创建时指定 hnsw:space=cosine，与 bge-m3 的语义距离匹配。",
        "metadata 里存 source、page、page_start、page_end，检索结果天然带页码，才能做出处跳转。",
        "id 设计为 source:page:序号:hash，同文本去重、同页多片不冲突。",
        "客户端做单例缓存：每次新建 PersistentClient 要 0.8 秒，缓存后检索降到 0.2 秒。",
    ],
    [
        ("Chroma（选用）", "嵌入式零运维、metadata 过滤、持久化", "超大规模（千万级）性能不如 Milvus"),
        ("FAISS", "检索极快", "不负责持久化与 metadata，要自己写一层"),
        ("Milvus / Qdrant", "分布式、亿级规模", "要单独部署服务，本项目用不上"),
    ],
    [
        "Chroma 的 Rust 绑定需要可写 TEMP：低完整性进程下报 (code: 14) unable to open database file，"
        "最后在 import 前把 TEMP/TMP 指到仓库内目录 data/tmp 才解决。",
        "上传同名文件时出现 Expected IDs to be unique：因为 id 只用了 source+page，"
        "加了序号与内容哈希后解决。",
    ],
    [
        ("为什么不用 FAISS？", "FAISS 只做向量检索，持久化、metadata、增量删除都要自己实现；"
                            "Chroma 一并提供，8,895 条规模性能也够（检索 0.2 秒）。"),
        ("什么是余弦相似度？", "两个向量夹角的余弦值，只看方向不看长度，适合文本语义比较；"
                           "1 表示同向（极相似），0 表示无关。"),
    ],
)

pt(
    11, "SQLite", "标准库 3.45+",
    "会话与消息落在 data/app.db，刷新页面还能看到历史。",
    "SQLite 是嵌入式关系数据库，整个库就是一个文件，不需要服务进程。Python 标准库自带驱动。",
    "app/db.py 建两张表：sessions(id, created_at) 与 messages(id, session_id, role, content, sources, created_at)。"
    "每次问答把用户问题与助手答案（含出处 JSON）写进去；/sessions 与 /sessions/{id} 读出来。",
    [
        "sources 字段用 JSON 文本存，读的时候反序列化，避免再建一张出处的关联表。",
        "init_db() 放在模块导入时执行，否则 TestClient 不跑 startup 事件时表不存在。",
        "所有写操作用同一个连接 + 短事务，避免并发写锁。",
    ],
    [
        ("SQLite（选用）", "零依赖、单文件、随项目迁移", "高并发写较弱"),
        ("PostgreSQL", "功能强、并发好", "要起服务，本项目用不上"),
        ("直接存 JSON 文件", "更简单", "并发写会损坏，查询也麻烦"),
    ],
    [
        "TestClient 默认不触发 startup，导致测试时表不存在；把建表放到 module import 解决。",
        "sources 存 JSON 后，前端取历史能直接渲染出处卡片，不需要再查一次向量库。",
    ],
    [
        ("为什么不用 ORM？", "两张表、五个字段，SQL 直接写更清楚；ORM 会引入额外依赖与学习成本。"),
        ("历史记录怎么保证和答案对得上？", "同一事务里把 user 与 assistant 两条消息一起写，"
                                      "sources 与答案同源，不会错位。"),
    ],
)

pt(
    12, "RAG 检索策略", "自研（app/rag.py）",
    "召回率 90% 的核心不在库，而在「检索 + 过滤 + 闸门 + 提示词」这四步怎么配合。",
    "RAG（Retrieval-Augmented Generation）是「先检索、再生成」的范式：把相关资料找出来塞进提示词，"
    "让模型基于资料回答，从而减少幻觉并给出处。",
    "app/rag.py 的 retrieve()：问题向量化 → Chroma 余弦检索 Top-5 → 过滤低价值片段（is_low_value）"
    "→ 取前 2 条拼进提示词（answer_top_n=2）→ 生成 → 清洗 → 附出处。",
    [
        "相似度闸门 0.45：低于它直接返回「资料中没有相关内容」，不调模型，省时且不编造。",
        "上下文只给 2 条（E5 实验）：1/2/3 条对应准确率 70.0%/83.3%/76.7%，多了反而带偏。",
        "提示词分两层规则：先判断「资料是否直接回答问题」，再要求「只写自然语言、禁 LaTeX」。",
        "出处带上 page_start/page_end 与完整片段，前端才能跳页并高亮。",
    ],
    [
        ("Top-5 检索 + Top-2 生成（选用）", "召回与准确兼顾，实测最优", "参数需靠实验确定"),
        ("全部塞进上下文", "不用挑", "超长、噪声多、变慢"),
        ("纯靠模型自身知识", "无需检索", "会编造，无法给出处"),
    ],
    [
        "最初把出处摘要写成「取前 100 字」，结果常从单词中间断开、甚至截到代码行；"
        "改成按句切分 + 按问题相关度挑最相关句。",
        "加入「纯自然语言」规则后拒答能力回退（又问「今天北京天气」编答案），"
        "四版提示词对比后收紧成「有直接事实才答」，恢复 5/5 拒答且准确率维持 76.7%。",
    ],
    [
        ("RAG 的幻觉怎么压？", "三层：检索闸门挡掉无关资料、提示词要求「没有就拒答」、"
                            "出处可点击回原文核验。"),
        ("为什么召回率不是 100%？", "3 道题命中了同一文件的不同页（内容确实在，但页码不符），"
                                "属于评测口径问题，不是检索失败。"),
    ],
)

# ============================ 第四章 文档处理 ============================
pt(
    13, "pypdf", "6.21.1",
    "把 10 份 PDF 的每一页文字抽出来，是整条链路的起点。",
    "pypdf 是纯 Python 的 PDF 库，能读取页对象与文本层。相比 PyMuPDF，它更轻、依赖更少。",
    "scripts/01_extract.py 用它逐页提取文本，保留页码，产出 829,035 字（d2l-zh 单本）。"
    "提取质量直接决定后面切片与检索的质量。",
    [
        "先做格式检查（T0.2）：统计 Tj/TJ 操作符，确认 PDF 有文字层，避免拿到扫描件。",
        "逐页提取而不是整本提取，才能保留 page 元数据用于出处。",
        "空页与乱码要统计出来：d2l-zh 有 1 页空页、替换符 0 个，说明文字层干净。",
    ],
    [
        ("pypdf（选用）", "纯 Python、轻、够用", "复杂版式还原一般"),
        ("PyMuPDF", "功能强、能取坐标、能高亮", "体积大，提取不是它的主要用途"),
        ("pdfplumber", "表格抽取强", "慢，依赖多"),
    ],
    [
        "d2l-zh 印刷页码 ≠ 物理页码（差 18 页），出处展示时统一用物理页，另存 page_label 说明。",
        "PDF 里的换行会把句子切断（「尽\\n管」），所以切片后需要清洗空白再入库。",
    ],
    [
        ("PDF 提取最大的坑是什么？", "扫描件没有文字层，抽出来是空；所以做之前先用操作符统计确认有文字层，"
                                 "再决定是否要 OCR（本项目 100% 有文字层，OCR 取消）。"),
        ("页码怎么对得上？", "提取时保留物理页码，出处只标物理页；印刷页码另外存一个 label 字段做提示。"),
    ],
)

pt(
    14, "PyMuPDF (fitz)", "1.28.2",
    "实现「点出处 → 打开 PDF → 跳到该页 → 命中句子标黄」。",
    "PyMuPDF 是 PDF 渲染与编辑库，能拿到每个字符的坐标、按文本搜索、添加注释（高亮、批注）。",
    "GET /files/{name}/highlight：在该页 search_for(句子) 拿到矩形 → add_highlight_annot 加黄色注释 "
    "→ 另存缓存 → 返回给浏览器。这是 pypdf 做不到的。",
    [
        "search_for 返回矩形列表，天然适配高亮注释。",
        "按句搜索而不是整段：PDF 里有换行与公式，整段往往搜不到。",
        "按与问题的相关度排序句子，优先高亮正文解释句而不是代码块。",
        "只在命中时才写缓存：否则匹配失败的结果被缓存，用户再点就「高亮消失」了。",
    ],
    [
        ("PyMuPDF（选用）", "有坐标、能高亮、速度快", "体积大（约 20MB）"),
        ("pypdf", "轻", "没有文本坐标，无法定位"),
        ("浏览器搜索参数 #search=", "零依赖", "Chrome 已不支持，跨浏览器不可靠"),
    ],
    [
        "阿里云镜像提供的 pymupdf 2.0 wheel 与索引哈希不一致，安装直接失败；"
        "改为下载 1.28.2 的 wheel、校验 sha256 后本地安装。",
        "高亮消失事件：缓存里存了「零注释」的坏结果，改法是不命中不缓存 + 缓存加版本号。",
        "第一次只按「前 100 字」搜索，结果标在代码行上；改成整段送进来逐句搜索后才标到正文。",
    ],
    [
        ("怎么在 PDF 上做高亮？", "搜索到文本矩形后加 Highlight 注释，注释是 PDF 标准对象，"
                              "浏览器内置阅读器能直接显示，不需要前端再画一层。"),
        ("为什么要缓存？", "一本 813 页的书每次重新打开+保存要几百毫秒到几秒；"
                       "按「文件+页码+片段」哈希缓存后第二次是毫秒级。"),
    ],
)

pt(
    15, "python-docx", "1.2.0",
    "让 Word 文件也能入库问答，并在浏览器里直接阅读。",
    "python-docx 用来读写 .docx：段落、样式、表格都能访问。它也是本次生成这些说明文档的工具。",
    "两处用途：① 上传 docx 时抽段落文本入库；② GET /files/{name}/view 把 docx 转成 HTML 页面"
    "（标题、段落、表格保留），避免浏览器直接下载。",
    [
        "docx 没有「页」的概念，所以出处对 docx 只标页码为 1（或段落序号），不能跳页。",
        "转 HTML 时按 style.name 判断层级（Heading 1 → h2），表格逐行转 tr/td。",
        "浏览器渲染不了 docx，inline 也会触发下载，所以只能服务端转换后返回 HTML。",
    ],
    [
        ("python-docx（选用）", "官方库、稳定、读写都行", "不负责渲染版式"),
        ("LibreOffice headless 转 PDF", "保留原版式、还能跳页", "要装几百 MB 的运行时"),
        ("mammoth", "docx 转 HTML 更专业", "多一个依赖，本项目简单转换够用"),
    ],
    [
        "最初 docx 用 Content-Disposition: attachment 直接下载，用户反馈「点了就下载，看不到内容」；"
        "改成 /view 返回 HTML 后解决。",
    ],
    [
        ("docx 和 PDF 处理有什么区别？", "PDF 有固定版面与页码，能定位、能高亮；"
                                     "docx 是流式文档，只能按段落读，出处无法精确到「页」。"),
        ("为什么不用 LibreOffice 转 PDF？", "能保留版式，但要在服务端装几百 MB 运行时；"
                                       "本项目只需要「能读」，HTML 足够。"),
    ],
)

pt(
    16, "RecursiveCharacterTextSplitter + 自定义重叠", "1.1.3",
    "把长文档切成 512 字的块，重叠 50 字——这个数字是实验选出来的。",
    "LangChain 的递归切分器：按分隔符优先级（段落 → 换行 → 句号 → 空格）递归切，尽量不破坏语义边界。",
    "scripts/02_chunk.py：chunk_size=512、chunk_overlap=50，跨页片段记录 page_start/page_end。"
    "另外实现了 _enforce_overlap 兜底。",
    [
        "512 来自 E1 实验：256/512/1024 → 召回 90.0%/90.0%/86.7%，平均名次 1.56/1.33/1.92，512 最优。",
        "50 来自 E4 实验：0/20/50 → 83.3%/83.3%/90.0%，说明 20 字重叠几乎没作用。",
        "框架的重叠在「超长单行」时会退化为 0，所以必须自己保证每个片段与上一片至少重叠 50 字。",
        "切完要校验：0 个超长片段、相邻重叠 ≥50、页码连续。",
    ],
    [
        ("512 / 重叠 50（选用）", "实验最优，召回 90%", "参数需要实验确定"),
        ("按段落切", "语义最完整", "长度差异大，长的超 token、短的没信息"),
        ("按固定长度硬切", "简单", "会把句子切断，语义破碎"),
    ],
    [
        "LangChain 的重叠在 PDF 长行上变成 0，导致相邻片段没上下文；自己写了 _enforce_overlap。",
        "一开始用 1024 长度以为「上下文更全」，实测召回反而降到 86.7%——块太大，检索粒度变粗。",
    ],
    [
        ("切片长度怎么定？", "做实验。256/512/1024 三档跑同一批题，看召回率与平均命中名次；"
                         "本项目 512 最优，256 持平但切片数翻倍，1024 明显下降。"),
        ("重叠有什么用？", "让相邻片段共享上下文，避免答案正好被切在边界。实验显示 20 字几乎无效，50 字才明显提升。"),
    ],
)

# ============================ 第五章 前端 ============================
pt(
    17, "Vue 3", "3.5",
    "单页应用：左侧文件与模型选择，右侧对话与出处卡片。",
    "Vue 3 是渐进式前端框架，组合式 API（setup + ref/computed）让逻辑按功能聚合，而不是按选项分散。",
    "web/src/views/Chat.vue 一个组件承载主界面；api.js 封装 axios 与 SSE 解析。"
    "状态用 ref/computed 管理（messages、provider、providers）。",
    [
        "ref 管可变状态，computed 从「provider:model」id 里拆出 provider 与 model 两个值。",
        "流式更新：每收到一段 token 就 reply.content += t 并自动滚到底部。",
        "父消息持有 question 字段，点出处时把问题一起传给后端做相关度排序。",
    ],
    [
        ("Vue 3（选用）", "上手快、组合式 API 清晰、Element Plus 生态好", "大型应用需额外状态管理"),
        ("React", "生态最大", "本项目体量小，JSX + hooks 反而更啰嗦"),
        ("纯 HTML + JS", "零构建", "状态与组件复用会很痛苦"),
    ],
    [
        "模型下拉框最初只支持「本地/云端」，后来改成自动发现：/providers 返回 id 形如 "
        "ollama:qwen2.5:7b，前端要按第一个冒号拆开（模型名本身自带冒号）。",
    ],
    [
        ("为什么用组合式 API？", "逻辑按功能聚合：模型选择相关的东西放一起，流式接收放一起，"
                             "比选项式更好读也更好抽函数。"),
        ("流式渲染怎么做的？", "不用 v-html，而是维护一个响应式字符串，每段 token 追加后 Vue 自动增量更新 DOM，"
                           "再调 scrollToBottom。"),
    ],
)

pt(
    18, "Vite", "7.1",
    "开发时秒开、改代码即时刷新；构建 1657 个模块约 6 秒。",
    "Vite 是前端构建工具：开发阶段用原生 ESM 直接给浏览器，不做打包；生产构建用 Rollup。",
    "npm run dev 起开发服务器（5173），并把 /api 代理到后端 8000；npm run build 产出 dist，"
    "由 Nginx 托管。",
    [
        "代理配置解决跨域：/api/health → http://127.0.0.1:8000/health（rewrite 去掉 /api）。",
        "必须显式绑 127.0.0.1：默认只监听 ::1，浏览器输入 127.0.0.1:5173 会连不上。",
        "构建产物是纯静态文件，容器里由 Nginx 托管，反代 /api 到 backend 服务。",
    ],
    [
        ("Vite（选用）", "冷启动极快、HMR 好用、配置简单", "生产构建仍是 Rollup，超大项目需调优"),
        ("Webpack", "生态最全、可控性最强", "配置复杂、冷启动慢"),
        ("不用构建工具", "最简单", "无法用 SFC 与依赖打包"),
    ],
    [
        "Vite 默认监听 IPv6 的 ::1，导致 127.0.0.1:5173 打不开；在 vite.config.js 里加 host: '127.0.0.1' 解决。",
        "只改 src 时 HMR 生效；改了 vite.config.js 必须重启 dev server。",
    ],
    [
        ("Vite 为什么快？", "开发时不做打包，浏览器按需请求 ESM 模块，启动只编译用到的文件；"
                         "HMR 也只需替换改动模块。"),
        ("开发和生产环境请求路径怎么统一？", "开发用 Vite 代理 /api → 8000，生产用 Nginx 反代 /api → backend:8000，"
                                        "前端代码里始终只写 /api。"),
    ],
)

pt(
    19, "Element Plus + axios", "2.11 / 1.13",
    "让界面看起来像个产品，而不是一堆原始 HTML 控件。",
    "Element Plus 是 Vue 3 的组件库（上传、下拉、消息、按钮）；axios 是 HTTP 客户端，"
    "支持拦截器与统一错误处理。",
    "上传区用 el-upload（拖拽 + 点击）、模型选择用 el-select、对话气泡与出处卡片是自定义样式；"
    "axios 封装在 api.js，baseURL 统一为 /api。",
    [
        "el-upload 需要自己处理 before-upload 与 http-request，才能走自定义 POST /upload。",
        "按钮禁用状态由 question.trim() 决定，空输入时发不出去（自动化测试里验证过）。",
        "axios 拦截器统一把后端 {detail} 转成可读的中文错误提示。",
    ],
    [
        ("Element Plus（选用）", "中文文档、组件全、与 Vue3 契合", "样式定制需要覆盖 CSS 变量"),
        ("Ant Design Vue", "企业风格、组件丰富", "体积更大，风格偏重"),
        ("Naive UI", "轻、TS 友好", "生态与示例不如 Element Plus 多"),
    ],
    [
        "el-select 的选项在 body 里渲染（不在组件 DOM 内），做自动化点击时必须用全局选择器 "
        ".el-select-dropdown__item，不能从组件根节点找。",
        "编程方式填 el-input 时，直接设 value 不触发 v-model，必须用原生 setter + dispatchEvent('input')。",
    ],
    [
        ("为什么不用 Tailwind 自己写？", "上传、下拉、消息这些交互组件从零写成本高；"
                                    "Element Plus 直接给成品，样式再用少量 CSS 调整。"),
        ("前端怎么处理错误？", "axios 拦截器把 HTTP 错误转成消息提示；流式接口单独 try/catch，"
                          "失败时在气泡里显示「请求失败」而不是静默。"),
    ],
)

pt(
    20, "Nginx", "1.27-alpine",
    "生产环境托管前端静态文件，并把 /api 反代到后端容器。",
    "Nginx 是高性能 Web 服务器/反向代理。这里承担两件事：托管 Vue 构建产物、把 /api 请求转给 backend 容器。",
    "web/nginx.conf：location / 用 try_files 兜底 index.html（SPA 路由）；location /api/ "
    "proxy_pass http://backend:8000/；并为 SSE 关闭缓冲。",
    [
        "SPA 必须 try_files $uri $uri/ /index.html，否则刷新子路由会 404。",
        "proxy_buffering off 是 SSE 的关键，否则浏览器要等整段生成完才收到。",
        "proxy_read_timeout 600s：生成慢时不至于被 Nginx 提前断开。",
        "容器间用服务名 backend 通信（compose 内的 DNS），不是 localhost。",
    ],
    [
        ("Nginx（选用）", "成熟、配置直观、镜像小", "动态配置需 reload"),
        ("Caddy", "自动 HTTPS", "生态与排查资料不如 Nginx"),
        ("FastAPI 直接托管静态文件", "少一个进程", "缓存、压缩、并发都不如 Nginx"),
    ],
    [
        "本地开发用 Vite 代理一切正常，容器部署后流式变成「一次性」——原因是 Nginx 默认缓冲，"
        "加 proxy_buffering off 才对。",
    ],
    [
        ("为什么容器里写 http://backend:8000？", "compose 会给服务建内部 DNS，服务名就是主机名；"
                                           "localhost 在容器里指容器自己，转发会失败。"),
        ("SSE 为什么要关缓冲？", "Nginx 默认攒够 buffer 才发给客户端，长连接下就变成「等全部生成完再吐」，"
                            "流式效果消失。"),
    ],
)

# ============================ 第六章 工程与部署 ============================
pt(
    21, "Docker", "29.9.2",
    "把「装环境」变成「跑镜像」：后端 1.29GB，一条命令起来。",
    "Docker 用镜像把应用与依赖打包在一起，容器运行时彼此隔离。好处是环境一致、交付简单。",
    "Dockerfile 两阶段：python:3.12-slim 装依赖跑 uvicorn；web/Dockerfile 用 node 构建、"
    "nginx 托管。数据（向量库、SQLite、语料）通过 volume 挂载，不进镜像。",
    [
        "依赖清单单独 COPY 一层：改代码不会触发重装依赖，构建从十几分钟降到几十秒。",
        "基础镜像参数化（ARG BASE_IMAGE），国内可换镜像站，默认仍是官方镜像。",
        "pip 加 --timeout/--retries 与缓存挂载，应对国内镜像读超时。",
        "requirements-docker.txt 去掉 torch 等 13 个未使用重包，镜像从 4GB+ 降到 1.29GB。",
    ],
    [
        ("Docker（选用）", "环境一致、交付简单、可复现", "Windows 下 WSL2 有性能损耗"),
        ("直接跑 Python", "最快", "换机器就要重装环境，容易出错"),
        ("虚拟机镜像", "最彻底", "体积大、启动慢"),
    ],
    [
        "首次构建卡 24 分钟后超时：pip 没设 timeout 与重试，且没挂缓存，失败就要从头再来。",
        "`sentence-transformers` 会偷偷拉 554MB 的 torch，而代码里根本没 import 它——镜像瘦身的最大一块就是它。",
        "容器里问答比本机慢 2–4 倍：Docker Desktop 的 WSL2 虚拟机和宿主抢 CPU，检索只占 0.24 秒，慢在生成。",
    ],
    [
        ("镜像为什么能降到 1.29GB？", "去掉三个死重量：torch 链（sentence-transformers/transformers）、"
                                 "Streamlit 链（pandas/pyarrow/matplotlib）、以及打包工具。代码里都没用到。"),
        ("数据怎么持久化？", "向量库、SQLite、语料都在宿主机目录，通过 volume 挂进容器；"
                         "删容器不丢数据，实测重启后 8,895 条向量仍在。"),
    ],
)

pt(
    22, "docker compose", "v2",
    "一条命令起停两个容器，并管好它们的网络与依赖顺序。",
    "compose 用一个 YAML 描述多容器应用：镜像怎么构建、端口怎么映射、卷怎么挂、谁依赖谁。",
    "docker-compose.yml 定义 backend（8000，挂 data 与 materials，连宿主机 Ollama）与 "
    "frontend（80，依赖 backend）。",
    [
        "extra_hosts: host.docker.internal:host-gateway 让容器能访问宿主机的 Ollama。",
        "healthcheck 用 python 请求 /health，容器状态能显示 healthy，方便判断就绪。",
        "env_file: .env 把配置注入容器，但 OLLAMA_BASE_URL 在 environment 里覆盖为宿主机地址。",
        "materials 以 :ro 只读挂载，防止容器误改语料。",
    ],
    [
        ("docker compose（选用）", "一条命令起停、YAML 可读、够本项目用", "大规模编排不如 K8s"),
        ("docker run 两条命令", "更直接", "端口/卷/网络要手动记"),
        ("Kubernetes", "生产级编排", "单机两容器属于杀鸡用牛刀"),
    ],
    [
        "容器内 .env 的 OLLAMA_BASE_URL 是 127.0.0.1，在容器里指自己，必须覆盖成 host.docker.internal。",
        "compose 的 build.args 要显式透传环境变量，否则 Dockerfile 里的 ARG 拿到空值（曾报 base name should not be blank）。",
    ],
    [
        ("compose 里容器怎么访问宿主机？", "Docker Desktop 提供 host.docker.internal 这个特殊域名；"
                                     "Linux 上则用 extra_hosts 映射到 host-gateway。"),
        ("为什么 frontend 要 depends_on backend？", "保证启动顺序；但注意 depends_on 只保证启动先后，"
                                                "不保证后端已就绪，所以还配了 healthcheck。"),
    ],
)

pt(
    23, "配置外置与环境变量", ".env / python-dotenv",
    "换模型、换地址、换 Key 都只改一个文件，代码一行不动。",
    "把「会变的东西」从代码里抽出来放进 .env，用 python-dotenv 读入，集中到 app/config.py 的 Settings。",
    ".env 里有 LLM_PROVIDER、OLLAMA_MODEL、OLLAMA_BASE_URL、DEEPSEEK_API_KEY、CHUNK_SIZE、"
    "TOP_K、ANSWER_TOP_N、RAG_SCORE_GATE 等；.env.example 入库作为模板，.env 不入库。",
    [
        "所有配置都有默认值，缺项不会崩：没配 Key 时云端项自动不可用。",
        "配置里做了两处自动化：向量设备按 provider 选（本地 CPU / 云端 GPU），TEMP 指到仓库内目录。",
        "敏感信息隔离：.env 被 .gitignore 忽略，打包脚本发现 .env 直接中止。",
    ],
    [
        (".env + Settings（选用）", "简单、可读、换环境只改文件", "无类型校验时会静默出错"),
        ("命令行参数", "临时覆盖方便", "每次都要输，容易忘"),
        ("配置中心（Nacos 等）", "集中管理", "单人项目属于过度设计"),
    ],
    [
        "OLLAMA_BASE_URL 曾写 localhost，Windows 先解析 IPv6 ::1 而 Ollama 只听 IPv4，"
        "每次调用白等约 2 秒——这个配置项一个字母的差别造成了整轮延迟翻倍。",
    ],
    [
        ("配置为什么不用硬编码？", "模型、地址、Key 都是环境相关；写死在代码里换机器就要改代码，"
                              "而且 Key 容易跟着提交泄露。"),
        ("一个配置项能造成多大影响？", "实测：localhost → 127.0.0.1 这一处改动，"
                                 "嵌入 2.16s→0.11s、首 token 5–6s→1.23s、整轮减半。"),
    ],
)

pt(
    24, "测试与评测工具链", "自建 / 30 用例",
    "功能对不对靠 30 个用例，效果好不好靠 30 题评测，参数怎么定靠对照实验。",
    "测试分三层：单元/契约测试（接口行为）、质量评测（30 题召回与准确率）、对照实验（单变量对比）。",
    "tests/run_tests.py（30 用例，自己拉起服务）、scripts/evaluate.py（30 题评测）、"
    "scripts/exp_*.py（E1/E4/E5/E6/E7 实验）、scripts/check_env.py（环境自检）。",
    [
        "不用 pytest：自写断言与结果表，零额外依赖，换机器也能直接跑。",
        "测试要能自己造数据：docx 用例自己生成文件上传，不依赖库里恰好有什么。",
        "评测与实验必须同口径：同一批 30 题、同一套检索，只改一个变量。",
    ],
    [
        ("自建脚本（选用）", "零依赖、输出清晰、能跑在用户机器上", "生态工具（覆盖率等）需另配"),
        ("pytest", "生态成熟、插件多", "要装依赖，本项目用例数量不大"),
        ("手工点点点", "最快上手", "不可重复、回归时会漏"),
    ],
    [
        "测试写完第一轮就抓出 3 个真 bug：拒答回退、片段把代码和正文粘一起、以及我自己测试代码里"
        "响应头大小写写错导致误判。",
        "评测脚本 --limit 3 会把 eval-results.csv 覆盖成 3 行，之后必须重跑全量才能留档。",
    ],
    [
        ("怎么证明 RAG 有效？", "同一批 30 题固定口径跑召回率与准确率，再做单变量实验证明参数选择；"
                           "所有数字都能在 data/eval-results.csv 里查到。"),
        ("测试和评测的区别？", "测试验证「程序行为对不对」（接口返回码、事件顺序）；"
                           "评测衡量「答案质量好不好」（召回率、准确率）。两者都要有。"),
    ],
)

CHAPTERS = [
    ("第一章 接口层", [1, 2, 3, 4]),
    ("第二章 模型层", [5, 6, 7, 8, 9]),
    ("第三章 检索与存储", [10, 11, 12]),
    ("第四章 文档处理", [13, 14, 15, 16]),
    ("第五章 前端", [17, 18, 19, 20]),
    ("第六章 工程、部署与测试", [21, 22, 23, 24]),
]

INTRO = (
    "这份文档逐个讲清项目里用到的 24 个技术点。每个技术点统一按六段展开："
    "它是什么 → 在本项目里做什么 → 关键机制 → 选型对比 → 踩过的坑 → 面试怎么答。"
    "所有代码位置、参数、数字都来自本仓库的实际实现与实测结果，不是泛泛的技术介绍。"
)

READING = [
    ("想快速了解全貌", "只看每节开头的「一句话定位」，24 句读完约 5 分钟。"),
    ("准备面试", "重点看每节最后的「面试怎么答」，再结合「踩过的坑」讲细节。"),
    ("要复现或改造", "看「在本项目里做什么」里的文件路径与参数名，直接对照代码。"),
]


# ---------------------------------------------------------------- 排版工具
def set_base_style(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    style.paragraph_format.space_after = Pt(4)
    style.paragraph_format.line_spacing = 1.25


def add_label_para(doc, label: str, text: str):
    p = doc.add_paragraph()
    run = p.add_run(label + "　")
    run.bold = True
    run.font.color.rgb = BLUE
    p.add_run(text)
    return p


def add_bullets(doc, items: list[str]) -> None:
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def add_options_table(doc, rows: list[tuple]) -> None:
    table = doc.add_table(rows=1, cols=3)
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    hdr = table.rows[0].cells
    for i, h in enumerate(("方案", "优点", "缺点")):
        hdr[i].text = ""
        run = hdr[i].paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(9)
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(val))
            run.font.size = Pt(9)
    for row in table.rows:
        for i, w in enumerate((5.0, 5.8, 5.4)):
            row.cells[i].width = Cm(w)
        tr_pr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        cant.set(qn("w:val"), "true")
        tr_pr.append(cant)
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def add_qa(doc, qa: list[tuple]) -> None:
    for q, a in qa:
        p = doc.add_paragraph()
        run = p.add_run("Q " + q)
        run.bold = True
        p2 = doc.add_paragraph()
        p2.paragraph_format.left_indent = Cm(0.6)
        p2.add_run("A " + a)


# ---------------------------------------------------------------- DOCX
def build_docx() -> None:
    doc = Document()
    set_base_style(doc)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(2.2)
        section.left_margin = section.right_margin = Cm(2.3)

    title = doc.add_heading("AI 学习资料知识库 · 技术点详解", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph("24 个技术点 · 逐个讲透「是什么 / 干什么 / 为什么 / 踩过什么坑 / 怎么答」")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.runs[0].font.size = Pt(10)
    sub.runs[0].font.color.rgb = GREY
    meta = doc.add_paragraph("v1.0 · 2026-10-23 · 依据本仓库代码与实测数据整理")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.runs[0].font.size = Pt(9)
    meta.runs[0].font.color.rgb = GREY

    doc.add_heading("写在前面", level=1)
    doc.add_paragraph(INTRO)
    doc.add_paragraph("建议阅读方式：")
    for who, how in READING:
        p = doc.add_paragraph(style="List Bullet")
        run = p.add_run(who + "：")
        run.bold = True
        p.add_run(how)

    by_no = {p["no"]: p for p in POINTS}
    for chapter, numbers in CHAPTERS:
        doc.add_heading(chapter, level=1)
        for no in numbers:
            item = by_no[no]
            doc.add_heading(f"{no}. {item['name']}", level=2)

            tag = doc.add_paragraph()
            run = tag.add_run(item["tagline"])
            run.italic = True
            run.font.color.rgb = GREY

            version = doc.add_paragraph()
            r = version.add_run(f"版本 / 规格：{item['ver']}")
            r.font.size = Pt(9)
            r.font.color.rgb = GREY

            add_label_para(doc, "它是什么", item["what"])
            add_label_para(doc, "在本项目里做什么", item["here"])

            doc.add_paragraph().add_run("关键机制").bold = True
            add_bullets(doc, item["mech"])

            doc.add_paragraph().add_run("选型对比").bold = True
            add_options_table(doc, item["options"])

            doc.add_paragraph().add_run("踩过的坑").bold = True
            add_bullets(doc, item["pits"])

            doc.add_paragraph().add_run("面试怎么答").bold = True
            add_qa(doc, item["qa"])
            doc.add_paragraph()

    doc.add_heading("附录：把 24 个技术点串成一条线", level=1)
    doc.add_paragraph(
        "用户在 Vue 界面输入问题 → axios/fetch 发起 POST /api/chat/stream → Vite（开发）或 Nginx（生产）"
        "反代到 FastAPI → Pydantic 校验请求 → rag.retrieve() 用 bge-m3（Ollama /api/embed）把问题向量化 → "
        "ChromaDB 余弦检索 Top-5 → 过滤噪声片段并按 0.45 闸门判断 → 取前 2 条拼进提示词 → "
        "ChatOllama 调用 qwen2.5:7b（或 ChatOpenAI 调 DeepSeek）流式生成 → 按句清洗 LaTeX 后通过 SSE 推送 → "
        "答案与出处写入 SQLite → 前端渲染气泡与出处卡片；点击出处时再请求 /files/{name}/highlight，"
        "由 PyMuPDF 在原 PDF 上标注并跳页。整个过程由 Docker + compose 打包，"
        "由 30 个用例与 30 题评测守住质量。"
    )

    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            para.paragraph_format.keep_with_next = True
    doc.save(OUT_DOCX)


# ---------------------------------------------------------------- Markdown
def build_md() -> None:
    out = ["# AI 学习资料知识库 · 技术点详解\n",
           "> 24 个技术点，逐个讲透「是什么 / 干什么 / 为什么 / 踩过什么坑 / 怎么答」\n",
           "## 写在前面\n", INTRO + "\n"]
    for who, how in READING:
        out.append(f"- **{who}**：{how}")
    out.append("")

    by_no = {p["no"]: p for p in POINTS}
    for chapter, numbers in CHAPTERS:
        out.append(f"## {chapter}\n")
        for no in numbers:
            it = by_no[no]
            out.append(f"### {no}. {it['name']}（{it['ver']}）\n")
            out.append(f"*{it['tagline']}*\n")
            out.append(f"**它是什么**　{it['what']}\n")
            out.append(f"**在本项目里做什么**　{it['here']}\n")
            out.append("**关键机制**\n")
            out += [f"- {m}" for m in it["mech"]]
            out.append("\n**选型对比**\n")
            out.append("| 方案 | 优点 | 缺点 |")
            out.append("|---|---|---|")
            out += [f"| {a} | {b} | {c} |" for a, b, c in it["options"]]
            out.append("\n**踩过的坑**\n")
            out += [f"- {p}" for p in it["pits"]]
            out.append("\n**面试怎么答**\n")
            for q, a in it["qa"]:
                out.append(f"- **Q：{q}**\n  A：{a}")
            out.append("")
    out.append("## 附录：把 24 个技术点串成一条线\n")
    out.append(
        "界面输入 → POST /api/chat/stream → Vite/Nginx 反代 → FastAPI → Pydantic 校验 → "
        "bge-m3 向量化 → Chroma 余弦 Top-5 → 过滤 + 0.45 闸门 → 前 2 条拼提示词 → "
        "qwen2.5:7b（或 DeepSeek）流式生成 → 按句清洗 → SSE 推送 → 写入 SQLite；"
        "点出处 → PyMuPDF 标注并跳页。Docker 打包，30 用例 + 30 题评测守质量。\n"
    )
    OUT_MD.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    build_docx()
    build_md()
    print("技术点数量:", len(POINTS))
    print("生成:", OUT_DOCX, OUT_DOCX.stat().st_size // 1024, "KB")
    print("生成:", OUT_MD, OUT_MD.stat().st_size // 1024, "KB")
