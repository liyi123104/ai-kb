"""RAG 核心（计划书 6.1 / T2.1）：文件解析、切片、入库、检索、生成。

本模块只做 RAG 链路本身，不包含 HTTP 与数据库逻辑（那些在 main.py / db.py）。
与 scripts/ 下的实验脚本同源，但这里是产品代码：配置全部来自 app.config。

页码口径：PDF 用物理页序；docx/md/txt 没有页的概念，统一记为 page=1。
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".txt"}
NO_ANSWER = "资料中没有相关内容。"

PROMPT_TEMPLATE = """你是一个严谨的知识库问答助手。请只依据【参考资料】回答【问题】。

规则：
1. 只使用参考资料中的信息，不要编造，不要引入资料之外的知识。
2. 第一行直接给出答案（一句话），不要写"根据资料"之类的铺垫。
3. 只有当你确实找不到任何相关依据时，才输出「资料中没有相关内容。」；
   只要能回答，就绝对不要出现这句话，也不要先否定再答。
4. 用与问题相同的语言回答（英文问题用英文答，中文问题用中文答）。
5. 回答里用 [编号] 标注依据，例如「自注意力能并行计算 [2]」。

【参考资料】
{context}

【问题】
{question}

【回答】"""

_BASE64_RE = re.compile(r"[A-Za-z0-9+/=]{120,}")
_TOC_RE = re.compile(r"(?:\.\s){10,}")


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def extract_pages(path: Path) -> list[dict]:
    """按页/段提取文本，返回 [{"page": 页号, "text": 文本}]。

    PDF 按物理页；docx 按段落合并成 1 页；md/txt 整篇算 1 页。
    异常：不支持的类型、加密 PDF、文件不存在，统一抛 ValueError（由上层转 400）。
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"不支持的文件类型：{suffix}（支持 pdf/docx/md/txt）")
    if not path.exists():
        raise ValueError(f"文件不存在：{path}")

    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    return _extract_text_file(path)


def _extract_pdf(path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError(f"PDF 已加密，无法用空密码打开：{path.name}")

    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - 单页坏掉不应让整本失败
            text = ""
        pages.append({"page": index, "text": text.replace("\x00", "").strip()})
    return pages


def _extract_docx(path: Path) -> list[dict]:
    from docx import Document

    doc = Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [{"page": 1, "text": text}]


def _extract_text_file(path: Path) -> list[dict]:
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return [{"page": 1, "text": path.read_text(encoding=encoding).strip()}]
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别文本编码：{path.name}")


# --------------------------------------------------------------------------- #
# 切片
# --------------------------------------------------------------------------- #
def _build_spans(pages: list[dict]) -> tuple[str, list[int], list[tuple[int, int, int]]]:
    parts, spans, offset = [], [], 0
    for p in pages:
        text = p["text"]
        spans.append((offset, offset + len(text), p["page"]))
        parts.append(text)
        offset += len(text) + 1  # join 用的 "\n"
    return "\n".join(parts), [s[0] for s in spans], spans


def _enforce_overlap(full_text: str, bounds: list[tuple[int, int]], size: int, overlap: int):
    """把切分器给出的边界调整为「长度 ≤ size 且相邻重叠 ≥ overlap」。

    LangChain 的 chunk_overlap 是按切分单元整块回退的，PDF 长行会导致重叠为 0，
    因此这里按结束位置回退补齐（细节见 docs/ 与 T1.2 记录）。
    """
    fixed, prev_end = [], 0
    for i, (start, end) in enumerate(bounds):
        end = min(end, len(full_text))
        start = max(end - size, 0)
        if i > 0 and start > prev_end - overlap:
            start = max(prev_end - overlap, 0)
            end = min(start + size, len(full_text))
        if start < end:
            fixed.append((start, end))
            prev_end = end
    return fixed


def _pages_of_range(spans, starts, begin: int, end: int) -> tuple[int, int]:
    from bisect import bisect_right

    if not spans:
        return 0, 0
    idx = max(bisect_right(starts, begin) - 1, 0)
    page_start = page_end = spans[idx][2]
    i = idx
    while i < len(spans) and spans[i][0] < end:
        page_end = spans[i][2]
        i += 1
    return page_start, page_end


def build_chunks(path: Path, source_name: str | None = None) -> list[dict]:
    """把文件切成带页码区间的 chunk 列表。"""
    pages = extract_pages(path)
    full_text, starts, spans = _build_spans(pages)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        add_start_index=True,
        separators=["\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ",", " ", ""],
    )
    docs = splitter.create_documents([full_text])
    bounds = [(int(d.metadata.get("start_index", 0)),
               int(d.metadata.get("start_index", 0)) + len(d.page_content)) for d in docs]
    fixed = _enforce_overlap(full_text, bounds, settings.chunk_size, settings.chunk_overlap)

    name = source_name or path.name
    chunks = []
    for start, end in fixed:
        text = full_text[start:end]
        if not text.strip():
            continue
        page_start, page_end = _pages_of_range(spans, starts, start, end)
        chunks.append({
            "source": name,
            "page": page_start,
            "page_start": page_start,
            "page_end": page_end,
            "chars": len(text),
            "text": text,
        })
    return chunks


# --------------------------------------------------------------------------- #
# 向量库
# --------------------------------------------------------------------------- #
_VECTORSTORE = None


def get_vectorstore():
    """返回向量库客户端单例。

    为什么缓存：Chroma 的 PersistentClient 初始化要打开 SQLite 并加载 HNSW 索引，
    每次请求都新建实测要 0.7–0.8 秒，直接把首字延迟顶到 4 秒以上。
    """
    global _VECTORSTORE
    if _VECTORSTORE is None:
        from langchain_community.vectorstores import Chroma

        from app.llm import get_embedder

        _VECTORSTORE = Chroma(
            collection_name=settings.collection,
            embedding_function=get_embedder(),
            persist_directory=str(settings.chroma_dir),
            collection_metadata={"hnsw:space": "cosine"},
        )
    return _VECTORSTORE


def _chunk_id(c: dict, seq: int) -> str:
    """确定性 id：同一文件同一位置重复入库得到同一 id（幂等），seq 保证同文件内不撞。"""
    digest = hashlib.sha1(c["text"].encode("utf-8")).hexdigest()[:12]
    return f'{c["source"]}:{c["page_start"]}:{seq}:{digest}'


def ingest_file(path: Path, source_name: str | None = None, batch: int = 64) -> dict:
    """解析 → 切片 → 嵌入 → 入库。返回 {"filename", "chunks", "size"}（对应 /upload 的返回）。"""
    name = source_name or path.name
    chunks = build_chunks(path, name)
    if not chunks:
        raise ValueError(f"文件没有可提取的文本：{name}")

    # 同一文件里内容完全相同的切片只保留一份：否则会得到重复 id（Chroma 会报
    # "Expected IDs to be unique"），而且重复向量只会白占索引。
    seen: set[str] = set()
    unique = []
    for c in chunks:
        if c["text"] in seen:
            continue
        seen.add(c["text"])
        unique.append(c)
    chunks = unique

    vs = get_vectorstore()
    # 同名文件重复上传：先删掉旧向量，避免同一文件出现两份
    vs._collection.delete(where={"source": name})  # noqa: SLF001

    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        vs.add_texts(
            [c["text"] for c in part],
            metadatas=[{k: c[k] for k in ("source", "page", "page_start", "page_end", "chars")}
                       for c in part],
            ids=[_chunk_id(c, i + j) for j, c in enumerate(part)],
        )
    return {"filename": name, "chunks": len(chunks), "size": path.stat().st_size}


def delete_file(name: str) -> int:
    """删除某个文件的全部向量，返回删除前的条数。"""
    vs = get_vectorstore()
    found = vs._collection.get(where={"source": name}, include=[])  # noqa: SLF001
    count = len(found.get("ids", []))
    if count:
        vs._collection.delete(where={"source": name})  # noqa: SLF001
    return count


def collection_count() -> int:
    return get_vectorstore()._collection.count()  # noqa: SLF001


# --------------------------------------------------------------------------- #
# 检索与生成
# --------------------------------------------------------------------------- #
def is_low_value(text: str) -> bool:
    """低信息碎片（目录点线 / 二进制块 / 纯符号）：会让出处看起来引用了没用的东西。"""
    if not text:
        return True
    if _BASE64_RE.search(text) or _TOC_RE.search(text):
        return True
    meaningful = sum(1 for ch in text if ch.isalnum())
    return meaningful / len(text) < 0.35


def retrieve(question: str, k: int | None = None) -> list[tuple]:
    """检索并过滤低价值碎片。返回 [(Document, distance), ...]。"""
    k = k or settings.top_k
    vs = get_vectorstore()
    pool = vs.similarity_search_with_score(question, k=max(k * 4, 12))
    kept = [(d, s) for d, s in pool if not is_low_value(d.page_content)]
    return kept[:k]


def page_label(md: dict) -> str:
    start, end = md.get("page_start"), md.get("page_end")
    return str(start) if start == end else f"{start}–{end}"


def format_context(hits: list[tuple]) -> str:
    blocks = []
    for i, (doc, _d) in enumerate(hits, start=1):
        md = doc.metadata
        blocks.append(f"[{i}] 来源：{md['source']} PDF p.{page_label(md)}\n{doc.page_content.strip()}")
    return "\n\n".join(blocks)


def make_sources(hits: list[tuple]) -> list[dict]:
    out = []
    for i, (doc, distance) in enumerate(hits, start=1):
        md = doc.metadata
        out.append({
            "index": i,
            "file": md["source"],
            "page": md["page"],
            "page_start": md["page_start"],
            "page_end": md["page_end"],
            "page_label": page_label(md),
            "score": round(1 - float(distance), 4),
            "snippet": re.sub(r"\s+", " ", doc.page_content.strip())[:100],
        })
    return out


def build_messages(hits: list[tuple], question: str) -> list[dict]:
    """给流式接口用的消息列表：system 放规则，user 放资料与问题。"""
    return [
        {"role": "system", "content": "你是严谨的知识库问答助手，只依据给定资料回答，资料不足时明确说「资料中没有相关内容。」"},
        {"role": "user", "content": f"【参考资料】\n{format_context(hits)}\n\n【问题】\n{question}"},
    ]


def answer(question: str, k: int | None = None, answer_top_n: int = 3) -> dict:
    """检索 + 生成，返回结构化结果（/chat 与评测脚本共用）。

    answer_top_n：喂给模型几条上下文。检索评估仍按 Top-K（默认 5）计算命中，
    但生成只用最相关的几条 —— 实测把 5 条全塞进去会掺入无关片段，反而拉低准确率。
    """
    from app.llm import get_llm

    hits = retrieve(question, k)
    if not hits:
        return {"question": question, "answer": NO_ANSWER, "sources": [],
                "best_score": 0.0, "gate": settings.score_gate, "gated": True, "error": "no_hits"}

    best_score = max(1 - float(d) for _, d in hits)
    if best_score < settings.score_gate:
        return {"question": question, "answer": NO_ANSWER, "sources": make_sources(hits[:1]),
                "best_score": round(best_score, 4), "gate": settings.score_gate,
                "gated": True, "error": None}

    context_hits = hits[:answer_top_n]
    prompt = PROMPT_TEMPLATE.format(context=format_context(context_hits), question=question)
    resp = get_llm().invoke(prompt)
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return {"question": question, "answer": text.strip(), "sources": make_sources(hits),
            "best_score": round(best_score, 4), "gate": settings.score_gate,
            "gated": False, "error": None}


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
