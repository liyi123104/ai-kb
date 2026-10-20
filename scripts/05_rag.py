"""T1.5 + T1.6 最小 RAG 闭环与出处溯源。

链路：问题 → 向量检索 Top-K（过滤低价值碎片）→ 拼 prompt → Ollama qwen2.5:7b 生成
      → 输出「答案正文 + 参考资料列表（文件名 + 页码 + 命中片段摘要）」。

设计要点：
1. 「资料里没有」用双保险：
   a) 检索分数闸门：最佳相似度低于门槛直接回「资料中没有相关内容」，不调用模型；
   b) prompt 约束：只依据给定资料回答，资料不足必须明说。
   阈值依据：T1.3 实测无关文本对余弦可达 0.35，而相关问题在 0.59–0.67，故取 0.45，
   可用环境变量 RAG_SCORE_GATE 覆盖。
2. 低价值片段过滤：目录点线、字体/图片二进制块、纯符号碎片占语料约 2%，但常抢占 Top-1，
   会让出处看起来引用了没用的东西。检索时多取候选再筛掉，不重嵌入、不改数据。
3. 输出格式固定（T1.6 验收要求「格式稳定可解析」）：
      [ANSWER]
      <答案正文>
      [SOURCES]
      1. file=... page=... score=... text=...
   并支持 --json 输出机器可读结果，供 T4 评测脚本直接调用。
4. 页码口径：page 是 PDF 物理页；本书印刷页码可能不同（d2l-zh 实测 = 物理页 - 18），
   这里如实标注为 PDF 页，并同时给出区间。

用法（在 D:\\ai-kb 下，用虚拟环境的解释器）：
    .\\.venv\\Scripts\\python.exe scripts\\05_rag.py "什么是自注意力机制？"
    .\\.venv\\Scripts\\python.exe scripts\\05_rag.py "今天北京天气怎么样？"     # 应回答资料中没有
    .\\.venv\\Scripts\\python.exe scripts\\05_rag.py "What is DPR?" --json
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 同 04_store.py：chromadb 的 Rust 绑定需要可写临时目录，本机 Python 是低完整性进程，
# 写不了系统 Temp，必须先把 TEMP/TMP 指到仓库内目录，否则连库时报 (code: 14)。
TMP_DIR = ROOT / "data" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(TMP_DIR)
os.environ["TMP"] = str(TMP_DIR)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import argparse  # noqa: E402
import json  # noqa: E402

from langchain_community.vectorstores import Chroma  # noqa: E402
from langchain_ollama import ChatOllama, OllamaEmbeddings  # noqa: E402

CHROMA_DIR = ROOT / "data" / "chroma"
COLLECTION = "ai-kb"

EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
SCORE_GATE = float(os.getenv("RAG_SCORE_GATE", "0.45"))

NO_ANSWER = "资料中没有相关内容。"

PROMPT_TEMPLATE = """你是一个严谨的知识库问答助手。请只依据【参考资料】回答【问题】。

规则：
1. 只使用参考资料中的信息，不要编造，不要引入资料之外的知识。
2. 如果参考资料不足以回答问题，第一句必须原样写「资料中没有相关内容。」，再简要说明缺什么。
3. 回答用中文；可以在中文里保留英文术语（如 Transformer、embedding）。
4. 引用资料时用 [编号] 标注，例如「自注意力能并行计算 [2]」。

【参考资料】
{context}

【问题】
{question}

【回答】"""

_BASE64_RE = re.compile(r"[A-Za-z0-9+/=]{120,}")
_TOC_RE = re.compile(r"(?:\.\s){10,}")


def build_vectorstore() -> Chroma:
    embedder = OllamaEmbeddings(model=EMBED_MODEL, base_url=BASE_URL)
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embedder,
        persist_directory=str(CHROMA_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def is_low_value(text: str) -> bool:
    """判断切片是否为低信息碎片（目录点线、二进制块、纯符号）。"""
    if not text:
        return True
    if _BASE64_RE.search(text):      # 字体/图片数据被抽成文本
        return True
    if _TOC_RE.search(text):         # 目录的 ". . . ." 点线
        return True
    meaningful = sum(1 for ch in text if ch.isalnum())
    return meaningful / len(text) < 0.35


def retrieve(vs: Chroma, question: str, k: int) -> list[tuple]:
    """检索 k 条，剔除低价值碎片；必要时放大候选池补齐。"""
    pool = vs.similarity_search_with_score(question, k=max(k * 4, 12))
    kept = [(d, s) for d, s in pool if not is_low_value(d.page_content)]
    return kept[:k]


def page_label(md: dict) -> str:
    """页码展示：单页写 434，跨页写 434–435。"""
    start, end = md.get("page_start"), md.get("page_end")
    return str(start) if start == end else f"{start}–{end}"


def format_context(hits: list[tuple]) -> str:
    """把检索结果编号后拼成上下文，带文件名与物理页区间。"""
    blocks = []
    for i, (doc, _distance) in enumerate(hits, start=1):
        md = doc.metadata
        blocks.append(f"[{i}] 来源：{md['source']} PDF p.{page_label(md)}\n{doc.page_content.strip()}")
    return "\n\n".join(blocks)


def make_sources(hits: list[tuple]) -> list[dict]:
    """参考资料列表：文件名 + 页码 + 命中片段摘要 + 相似度。"""
    out = []
    for i, (doc, distance) in enumerate(hits, start=1):
        md = doc.metadata
        snippet = re.sub(r"\s+", " ", doc.page_content.strip())[:100]
        out.append({
            "index": i,
            "file": md["source"],
            "page": md["page"],
            "page_start": md["page_start"],
            "page_end": md["page_end"],
            "page_label": page_label(md),
            "score": round(1 - float(distance), 4),
            "snippet": snippet,
        })
    return out


def ask(question: str, k: int, show_context: bool = False) -> dict:
    """跑一次检索 + 生成，返回结构化结果（供命令行与评测脚本共用）。"""
    vs = build_vectorstore()
    hits = retrieve(vs, question, k)
    if not hits:
        return {"question": question, "answer": NO_ANSWER, "sources": [],
                "best_score": 0.0, "gate": SCORE_GATE, "gated": True, "error": "no_hits"}

    best_score = max(1 - float(d) for _, d in hits)

    # 闸门：明显不相关就直接拒绝，避免 7B 模型硬编
    if best_score < SCORE_GATE:
        return {"question": question, "answer": NO_ANSWER,
                "sources": make_sources(hits[:1]), "best_score": round(best_score, 4),
                "gate": SCORE_GATE, "gated": True, "error": None}

    prompt = PROMPT_TEMPLATE.format(context=format_context(hits), question=question)
    llm = ChatOllama(model=CHAT_MODEL, base_url=BASE_URL, temperature=0)
    resp = llm.invoke(prompt)
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return {"question": question, "answer": text.strip(), "sources": make_sources(hits),
            "best_score": round(best_score, 4), "gate": SCORE_GATE, "gated": False, "error": None}


def print_result(result: dict, show_context: bool) -> None:
    """固定文本格式：[ANSWER] 正文 / [SOURCES] 出处列表。"""
    print("=" * 64)
    print(f"问题      : {result['question']}")
    print(f"检索      : 最佳相似度 {result['best_score']:.4f}（闸门 {result['gate']}）"
          f"{'，已触发闸门' if result['gated'] else ''}")
    print("=" * 64)
    if show_context and result["sources"]:
        print("\n[CONTEXT]")
        for s in result["sources"]:
            print(f"  [{s['index']}] sim={s['score']:.4f} {s['file']} PDF p.{s['page_label']}"
                  f" | {s['snippet'][:60]}")
    print("\n[ANSWER]")
    print(result["answer"])
    print("\n[SOURCES]")
    if not result["sources"]:
        print("  （无）")
    for s in result["sources"]:
        print(f"  {s['index']}. file={s['file']} page={s['page_label']} "
              f"score={s['score']:.4f} text={s['snippet']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 问答（检索 + 本地生成 + 出处溯源）")
    parser.add_argument("question", help="问题")
    parser.add_argument("--k", type=int, default=5, help="检索条数，默认 5")
    parser.add_argument("--show-context", action="store_true", help="打印检索片段")
    parser.add_argument("--json", action="store_true", help="输出 JSON（供评测脚本调用）")
    args = parser.parse_args()

    try:
        result = ask(args.question, args.k)
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 执行失败：{exc}", file=sys.stderr)
        print(f"       排查：1) ollama 是否在跑（{BASE_URL}）2) 模型 {CHAT_MODEL} 是否已拉取",
              file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_result(result, args.show_context)

    # 自检（T1.5/T1.6 的验收标准都可机器判定）
    problems = []
    if not result["answer"]:
        problems.append("答案为空")
    if "没有相关内容" not in result["answer"] and not result["sources"]:
        problems.append("有答案但没有出处")
    if result["sources"] and any(not s["file"] or not s["page"] for s in result["sources"]):
        problems.append("出处缺少文件名或页码")
    if problems:
        print("\n[自检失败] " + "；".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
