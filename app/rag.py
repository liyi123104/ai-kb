"""RAG 核心（计划书 6.1 / T2.1）：文件解析、切片、入库、检索、生成。

本模块只做 RAG 链路本身，不包含 HTTP 与数据库逻辑（那些在 main.py / db.py）。
与 scripts/ 下的实验脚本同源，但这里是产品代码：配置全部来自 app.config。

页码口径：PDF 用物理页序；docx/md/txt 没有页的概念，统一记为 page=1。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".txt"}
NO_ANSWER = "资料中没有相关内容。"

# 入库期间为 True：保活线程看到后不再把聊天模型拉回显存，
# 否则它会把正在做嵌入的 bge-m3 挤出 GPU，后面的批次退回 CPU（实测 45 片/秒掉到 4.7）。
_INGESTING = threading.Event()


def is_ingesting() -> bool:
    return _INGESTING.is_set()

PROMPT_TEMPLATE = r"""你是一个严谨的知识库问答助手。请只依据【参考资料】回答【问题】。

规则：
1. 只使用参考资料中的信息，不要编造，不要引入资料之外的知识。
2. 第一行直接给出答案（一句话），不要写"根据资料"之类的铺垫。
3. 先判断资料里有没有**直接回答这个问题**的事实：
   有就直接回答（可以只答资料能支持的部分）；没有就第一行输出「资料中没有相关内容。」。
4. 「资料里出现了相同词汇」不等于「资料回答了这个问题」。
   例如资料讲的是"天气对农业的影响"，而问题是"今天北京天气怎么样"，必须拒答。
   不要用只言片语拼凑答案，也不要先否定再答。
5. 用与问题相同的语言回答（英文问题用英文答，中文问题用中文答）。
6. 回答里用 [编号] 标注依据，例如「自注意力能并行计算 [2]」。
7. **只写自然语言，不要输出任何 LaTeX 或数学标记**：不要出现 $...$、\( \)、\[ \]、
   \mathbb、\ldots、\leq 之类的写法。需要表达公式时用文字描述，例如
   「第 i 个输入是 d 维实数向量」「i 从 1 到 n」「x 的平方」。
   原文中的符号可以用中文字符表达：≤ ≥ ∈ × ÷。
   同时不要用下标/上标写法（如 x_i、R^d、O(n^2)、y_1），改用文字：
   「第 i 个输入」「d 维实数向量」「关于序列长度平方的复杂度」「第一个输出」。
   改写时**必须保留原文的关键数值、维度、层次数、术语**，不要因为改成自然语言而丢信息。

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
    """PDF 逐页提取。默认用 PyMuPDF（比 pypdf 快约 30 倍），失败时退回 pypdf。"""
    if settings.pdf_extractor.lower() == "fitz":
        try:
            return _extract_pdf_fitz(path)
        except Exception as exc:  # noqa: BLE001 - 解析器异常不致命，退回 pypdf
            logging.getLogger(__name__).warning("PyMuPDF 解析失败，改用 pypdf：%s", exc)
    return _extract_pdf_pypdf(path)


def _extract_pdf_fitz(path: Path) -> list[dict]:
    """PyMuPDF 提取：813 页约 1.4 秒（pypdf 要 42 秒），字数差异 0.7%。"""
    import pymupdf

    doc = pymupdf.open(str(path))
    if doc.needs_pass and not doc.authenticate(""):
        doc.close()
        raise ValueError(f"PDF 已加密，无法用空密码打开：{path.name}")
    try:
        return [{"page": i + 1, "text": doc[i].get_text().replace("\x00", "").strip()}
                for i in range(doc.page_count)]
    finally:
        doc.close()


def _extract_pdf_pypdf(path: Path) -> list[dict]:
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


def _unload_model(model: str) -> None:
    """让 Ollama 卸载指定模型，释放显存（失败不影响主流程）。"""
    payload = {"model": model, "prompt": "", "keep_alive": 0}
    req = urllib.request.Request(
        settings.ollama_base_url.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:  # noqa: BLE001 - 卸载失败只是慢一点，不影响入库
        pass


def _unload_embedder(embedder) -> None:
    payload = {"model": embedder.model, "input": "x", "keep_alive": 0}
    req = urllib.request.Request(
        settings.ollama_base_url.rstrip("/") + "/api/embed",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:  # noqa: BLE001
        pass


def _ingest_embedder():
    """入库用的嵌入器：默认放 GPU。

    为什么单独一个：平时问答要把显存让给生成模型（embedding 跑 CPU），
    但入库时根本不生成，此时把 bge-m3 放到 GPU 能快约 12 倍
    （实测 CPU 1.4–3.3 片/秒，GPU 25–42 片/秒）。
    入库前先把聊天模型卸载，腾出显存。
    """
    from app.llm import OllamaEmbedder, get_embedder

    if not settings.ingest_use_gpu:
        return get_embedder(), False
    _unload_model(settings.ollama_model)
    # 关键：先把已驻留的 CPU 实例卸载，否则 Ollama 会继续复用旧实例，
    # num_gpu=-1 不会生效（实测吞吐仍是 3.6 片/秒）。卸载后首次请求会按 GPU 重新加载。
    _unload_embedder(get_embedder())
    return OllamaEmbedder(
        model=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
        keep_alive="30m",
        num_gpu=-1,
    ), True


def ingest_file(path: Path, source_name: str | None = None, batch: int = 64,
                progress=None) -> dict:
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

    embedder, used_gpu = _ingest_embedder()
    batch = max(batch, 64)  # GPU 下批越大越划算（实测 64 片/批约 42 片/秒）
    started = time.perf_counter()
    _INGESTING.set()  # 通知保活线程：入库期间别把聊天模型拉回显存，否则会挤掉 bge-m3
    try:
        for i in range(0, len(chunks), batch):
            part = chunks[i:i + batch]
            texts = [c["text"] for c in part]
            # 自己算向量再写库：绕开 LangChain 固定的 embedding_function，
            # 才能临时换用 GPU 嵌入器
            vectors = embedder.embed_documents(texts)
            vs._collection.add(  # noqa: SLF001
                ids=[_chunk_id(c, i + j) for j, c in enumerate(part)],
                documents=texts,
                metadatas=[{k: c[k] for k in ("source", "page", "page_start", "page_end", "chars")}
                           for c in part],
                embeddings=vectors,
            )
            if progress is not None:
                progress(min(i + batch, len(chunks)), len(chunks))
    finally:
        _INGESTING.clear()

    elapsed = time.perf_counter() - started
    rate = len(chunks) / elapsed if elapsed else 0
    logging.getLogger(__name__).info(
        "[ingest] %s: %d 片，%.1fs（%.1f 片/秒，%s）", name, len(chunks), elapsed, rate,
        "GPU" if used_gpu else "CPU")

    if used_gpu:
        _unload_embedder(embedder)  # 用完把显存还给生成模型

    return {"filename": name, "chunks": len(chunks), "size": path.stat().st_size,
            "seconds": round(elapsed, 1), "chunks_per_sec": round(rate, 1)}


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


def rerank(hits: list[tuple], question: str) -> list[tuple]:
    """用生成模型对候选做一次列表式重排（listwise）。

    背景：Ollama 0.13 没有 /api/rerank 接口，无法直接调 cross-encoder；
    但可以让模型看完全部候选后输出一个排序，实测 0.8–1.1 秒/次、输出稳定为合法排列。
    失败（输出不是合法排列）时原样返回，不影响主流程。
    """
    from app.llm import get_llm

    if len(hits) < 2:
        return hits
    lines = []
    for i, (doc, _dist) in enumerate(hits, start=1):
        text = re.sub(r"\s+", " ", doc.page_content)[:220]
        lines.append(f"[{i}] {text}")
    prompt = (
        "你是检索结果排序器。根据问题判断下面片段的相关性，只输出序号，"
        "按相关性从高到低用逗号分隔（例如 3,1,5,2,4），不要解释。\n\n"
        f"问题：{question}\n\n" + "\n".join(lines) + "\n\n排序结果："
    )
    try:
        resp = get_llm().invoke(prompt)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        order = [int(x) for x in re.findall(r"\d", text)][: len(hits)]
        if sorted(order) != list(range(1, len(hits) + 1)):
            return hits   # 不是合法排列：保留原顺序
        reranked = [hits[i - 1] for i in order]
        return reranked
    except Exception as exc:  # noqa: BLE001 - 重排失败不应让检索失败
        logging.getLogger(__name__).warning("rerank 失败，保留向量顺序：%s", exc)
        return hits


def retrieve(question: str, k: int | None = None) -> list[tuple]:
    """检索并过滤低价值碎片。返回 [(Document, distance), ...]。

    开启 RERANK 后，取回候选再用生成模型做一次列表式重排（一次调用，约 1 秒）。
    """
    k = k or settings.top_k
    vs = get_vectorstore()
    pool = vs.similarity_search_with_score(question, k=max(k * 4, 12))
    kept = [(d, s) for d, s in pool if not is_low_value(d.page_content)]
    hits = kept[:k]
    if settings.rerank_enabled and len(hits) > 1:
        hits = rerank(hits, question)
    return hits


def page_label(md: dict) -> str:
    start, end = md.get("page_start"), md.get("page_end")
    return str(start) if start == end else f"{start}–{end}"


def format_context(hits: list[tuple]) -> str:
    blocks = []
    for i, (doc, _d) in enumerate(hits, start=1):
        md = doc.metadata
        blocks.append(f"[{i}] 来源：{md['source']} PDF p.{page_label(md)}\n{doc.page_content.strip()}")
    return "\n\n".join(blocks)


def best_snippet(text: str, question: str = "", limit: int = 120) -> str:
    """从片段里挑出「与问题最相关的一句话」作为出处摘要。

    直接截前 100 字会从单词/句子中间断开（例如 "e larger field called..."），
    读起来毫无信息量。这里按句子切分、按与问题的字面重叠打分，取最相关的一句；
    太短的残句会和下一句合并，超长时在词边界截断并加省略号。
    """
    flat = re.sub(r"\s+", " ", text or "").strip()
    if not flat:
        return ""

    ends = "。！？；.!?;"

    def is_prose(s: str) -> bool:
        cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
        if cjk / max(len(s), 1) >= 0.25:
            return True
        return not re.search(r"[=(){}\[\];_<>]|\b(import|def|class|return|print)\b", s)

    # 先按原始换行切块：PDF 里代码行与正文是靠换行分隔的，
    # 一旦把换行抹成空格，代码就会和正文粘成"一句"，后面无法过滤。
    blocks = [re.sub(r"\s+", " ", b).strip() for b in (text or "").splitlines()]
    sentences = []
    for block in blocks:
        if not block:
            continue
        for part in re.split(r"(?<=[。！？；.!?;])\s*", block):
            if part.strip():
                sentences.append(part.strip())
    # 优先用「以标点收尾」的完整句；只有整段都没标点时才退回原样
    complete = [s for s in sentences if s[-1] in ends and len(s) >= 12]
    pool = complete or [s for s in sentences if len(s) >= 12] or sentences or [flat]
    if not pool:
        return flat[:limit]

    # 代码行不适合当摘录（如 "num_hiddens, num_heads = 100, 5 ..."）
    prose = [s for s in pool if is_prose(s)]
    if prose:
        pool = prose

    if question:
        q_chars = {question[i:i + 2] for i in range(len(question) - 1)}
        def score(s: str) -> float:
            s_chars = {s[i:i + 2] for i in range(len(s) - 1)}
            overlap = len(q_chars & s_chars) / (len(s_chars) or 1)
            # 残句往往密度高但信息少，按长度打个折，避免只选到半句
            return overlap * min(len(s), 60) / 60
        best = max(pool, key=score)
    else:
        best = pool[0]

    # 太短（半个句子）就把后面的内容接上，保证可读
    if len(best) < 30:
        idx = flat.find(best)
        if idx >= 0:
            tail = flat[idx + len(best): idx + len(best) + limit]
            best = (best + tail).strip()

    if len(best) <= limit:
        return best

    cut = best[:limit]
    # 英文尽量不切断单词：回退到最后一个空格
    if " " in cut and not re.search(r"[\u4e00-\u9fff]", cut[-12:]):
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip("，,、 ") + "…"


def make_sources(hits: list[tuple], question: str = "") -> list[dict]:
    out = []
    for i, (doc, distance) in enumerate(hits, start=1):
        md = doc.metadata
        raw = re.sub(r"\s+", " ", doc.page_content.strip())
        out.append({
            "index": i,
            "file": md["source"],
            "page": md["page"],
            "page_start": md["page_start"],
            "page_end": md["page_end"],
            "page_label": page_label(md),
            "score": round(1 - float(distance), 4),
            "snippet": best_snippet(raw, question),
            # 完整片段（截断 600 字）：前端点开原文时用它逐句定位高亮
            "text": raw[:600],
        })
    return out


def build_messages(hits: list[tuple], question: str) -> list[dict]:
    """给流式接口用的消息列表：system 放规则，user 放资料与问题。"""
    return [
        {"role": "system", "content": "你是严谨的知识库问答助手，只依据给定资料回答，资料不足时明确说「资料中没有相关内容。」"},
        {"role": "user", "content": f"【参考资料】\n{format_context(hits)}\n\n【问题】\n{question}"},
    ]


def answer(question: str, k: int | None = None, answer_top_n: int | None = None,
           provider: str | None = None, model: str | None = None) -> dict:
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
        return {"question": question, "answer": NO_ANSWER, "sources": make_sources(hits[:1], question),
                "best_score": round(best_score, 4), "gate": settings.score_gate,
                "gated": True, "error": None}

    context_hits = hits[:answer_top_n or settings.answer_top_n]
    prompt = PROMPT_TEMPLATE.format(context=format_context(context_hits), question=question)
    resp = get_llm(provider=provider, model=model).invoke(prompt)
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return {"question": question, "answer": clean_answer(text), "sources": make_sources(hits, question),
            "best_score": round(best_score, 4), "gate": settings.score_gate,
            "gated": False, "error": None}


_LATEX_MAP = {
    r"\(": "", r"\)": "", r"\[": "", r"\]": "", r"\$": "",
    r"\mathbb{R}": "R", r"\mathbb{N}": "N", r"\mathbb{Z}": "Z",
    r"\ldots": "…", r"\dots": "…", r"\cdots": "…",
    r"\leq": "≤", r"\geq": "≥", r"\in": "属于", r"\times": "×",
    r"\sum": "求和", r"\prod": "连乘", r"\partial": "偏导",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\theta": "θ",
    r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ",
}
_LATEX_TOKEN_RE = re.compile(r"\\[a-zA-Z]+")
_MATH_DELIM_RE = re.compile(r"\$+")
_CONTROL_RE = re.compile(r"\\[()\[\]$]")


def clean_answer(text: str) -> str:
    """把答案里残留的 LaTeX 标记清掉，保证输出是自然语言（prompt 已要求，这里是兜底）。"""
    if not text:
        return text
    out = text
    for k, v in _LATEX_MAP.items():
        out = out.replace(k, v)
    out = _CONTROL_RE.sub("", out)
    out = _LATEX_TOKEN_RE.sub("", out)     # 剩余的 \xxx 命令直接删掉
    out = _MATH_DELIM_RE.sub("", out)      # 去掉 $ 定界符
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
