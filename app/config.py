"""配置读取：所有路径、模型名、密钥统一从 .env / 环境变量读取（计划书 6.3）。

注意导入顺序：本模块必须在任何 chromadb 相关 import 之前被导入，
因为它负责把 TEMP/TMP 指到仓库内目录（低完整性进程写不了系统 Temp，
chromadb 的 Rust 绑定会因此报 (code: 14) unable to open database file）。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# .env 不进 Git（见 .gitignore），不存在时 load_dotenv 不会报错
load_dotenv(ROOT / ".env")

# chromadb 需要可写的临时目录：先设环境变量，再让各模块 import chromadb
TMP_DIR = ROOT / "data" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(TMP_DIR)
os.environ["TMP"] = str(TMP_DIR)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


def _get(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


class Settings:
    """集中式配置。字段名与 .env 键名一一对应，方便对照。"""

    # ---- 模型 ----
    llm_provider: str = _get("LLM_PROVIDER", "ollama")          # ollama | deepseek
    ollama_model: str = _get("OLLAMA_MODEL", "qwen2.5:7b")
    ollama_embed_model: str = _get("OLLAMA_EMBED_MODEL", "bge-m3:latest")
    ollama_base_url: str = _get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    # 让模型常驻显存：默认 Ollama 5 分钟就卸载，下一次请求要重新加载（实测 +17 秒）
    # ChatOllama 接受 "30m" 这样的字符串，OllamaEmbeddings 只接受整数秒，故拆成两个字段。
    ollama_keep_alive: str = _get("OLLAMA_KEEP_ALIVE", "30m")
    ollama_keep_alive_seconds: int = _get_int("OLLAMA_KEEP_ALIVE_SECONDS", 1800)
    # 上下文窗口：默认 4096 在 6GB 显存上会和 embedding 模型抢显存，KV 缓存溢出到 CPU，
    # 实测整轮生成 5.3–6.6s；降到 2048 后 2.9–3.5s。3 段上下文约 1.5k 字，2048 够用。
    ollama_num_ctx: int = _get_int("OLLAMA_NUM_CTX", 2048)
    # 向量模型放 CPU：6GB 显存装不下 qwen(4.7G) + bge-m3(1.2G)，两者同挤 GPU 会互相拖慢
    # （实测首 token 6s）。放到 CPU 后单条嵌入 0.19s，且给生成模型腾出 1.2GB。
    # 批量入库想用 GPU 时把它设为 -1 即可。
    ollama_embed_num_gpu: int = _get_int("OLLAMA_EMBED_NUM_GPU", 0)

    deepseek_model: str = _get("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_base_url: str = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_api_key: str = _get("DEEPSEEK_API_KEY", "")

    # ---- 检索 ----
    chunk_size: int = _get_int("CHUNK_SIZE", 512)
    chunk_overlap: int = _get_int("CHUNK_OVERLAP", 50)
    top_k: int = _get_int("TOP_K", 5)
    # 喂给生成模型的上下文条数（检索指标仍按 top_k 统计）
    answer_top_n: int = _get_int("ANSWER_TOP_N", 2)
    score_gate: float = _get_float("RAG_SCORE_GATE", 0.45)

    # ---- 存储 ----
    data_dir: Path = ROOT / "data"
    uploads_dir: Path = ROOT / "data" / "uploads"
    chroma_dir: Path = ROOT / "data" / "chroma"
    db_path: Path = ROOT / "data" / "app.db"
    collection: str = _get("CHROMA_COLLECTION", "ai-kb")
    # 入库时把向量模型放 GPU：入库不生成，让出显存能快约 12 倍
    # （实测 CPU 1.4–3.3 片/秒，GPU 25–42 片/秒）。显存不足时设为 0 退回 CPU。
    ingest_use_gpu: bool = _get_bool("INGEST_USE_GPU", True)
    # PDF 文本提取器：fitz（PyMuPDF，快约 30 倍）或 pypdf（老逻辑，兜底）
    pdf_extractor: str = _get("PDF_EXTRACTOR", "fitz")
    # 访问令牌：留空表示不启用（本机自用）。填了之后所有接口都要求带 X-Auth-Token，
    # 文件类 GET 接口也接受 ?token= 参数（浏览器直接打开链接时没法带请求头）。
    auth_token: str = _get("AUTH_TOKEN", "")
    # 列表式重排：用生成模型对 Top-K 候选排一次序（一次调用，约 1 秒）
    # Ollama 0.13 没有 /api/rerank，所以走提示词排序；关掉则保持纯向量顺序
    rerank_enabled: bool = _get_bool("RERANK", False)

    # ---- 服务 ----
    host: str = _get("APP_HOST", "0.0.0.0")
    port: int = _get_int("APP_PORT", 8000)

    def ensure_dirs(self) -> None:
        """启动时确保数据目录存在（uploads 会被 .gitkeep 保留）。"""
        for path in (self.data_dir, self.uploads_dir, self.chroma_dir, TMP_DIR):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()


def _auto_embed_device(s: Settings) -> None:
    """向量模型放哪块设备，按生成方式自动决定（显式设置环境变量则不覆盖）。

    为什么：6GB 显存装不下 qwen2.5:7b(4.4G) + bge-m3(1.2G) 同时驻留。
      - 本地生成（ollama）时，把显存留给生成模型，向量走 CPU（默认）；
      - 云端生成（deepseek）时本机不跑生成模型，向量放回 GPU，单条嵌入 0.15s。
    """
    import os as _os

    if _os.getenv("OLLAMA_EMBED_NUM_GPU") is not None:
        return
    s.ollama_embed_num_gpu = -1 if s.llm_provider.lower() == "deepseek" else 0


_auto_embed_device(settings)


def setup_logging(level: str = "INFO") -> None:
    """统一日志：控制台 + data/app.log（按 5MB 轮转，保留 3 份）。

    以前用 print 当日志，容器里只能 docker logs 翻，也没有轮转。
    """
    import logging
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    if root.handlers:          # 避免重复添加（uvicorn --reload 或多次 import）
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_path = ROOT / "data" / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
