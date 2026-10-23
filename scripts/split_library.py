"""把向量库按领域拆成两个集合，解决「语料漂移」问题。

背景：知识库里除了 10 份 AI 学习资料，还混进了 PostgreSQL 手册（15,669 片）、
Adobe PDF 规范（5,499 片）等通用技术文档，占了 74%。它们让检索变慢（0.4s → 0.9s），
也让「AI 学习知识库」这个定位名不副实。

做法：把向量**连同原始向量一起搬走**（不重新嵌入），分成
  ai-kb-ai   只含 10 份 AI 学习资料
  ai-kb-ref  其余通用技术参考
原集合 ai-kb 默认保留不动；确认新集合可用后再自己删。

用法：
  .venv\\Scripts\\python.exe scripts\\split_library.py --dry-run   # 只看计划
  .venv\\Scripts\\python.exe scripts\\split_library.py --apply     # 真正搬移
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

# 原始 10 份 AI 学习资料
AI_SOURCES = {
    "d2l-zh.pdf",
    "slp3-语音与语言处理第3版草稿.pdf",
    "mml-book-数学基础.pdf",
    "attention-is-all-you-need.pdf",
    "dpr-dense-retrieval.pdf",
    "rag-lewis-2020.pdf",
    "rag-survey-gao-2023.pdf",
    "ragas-评测.pdf",
    "self-rag-2023.pdf",
    "sentence-bert.pdf",
}

# 除原始 10 份外，文件名里带这些关键词的也算 AI 资料（论文、教材、综述）
AI_KEYWORDS = ("rag", "llm", "bert", "agent", "react", "toolformer", "faiss", "bge",
               "embedding", "transformer", "deepseek", "datawhale", "judge", "attention",
               "vector", "prompt", "lora", "fine-tun")

# 明显不属于 AI 领域的（数据库手册、PDF 规范、RFC、容器实践等）
NON_AI_KEYWORDS = ("postgresql", "adobe", "pdf-reference", "rfc", "docker", "kubernetes",
                   "mysql", "linux", "nginx", "redis", "java", "spring")


def classify(name: str) -> str:
    """判断某个文件属于 AI 资料还是通用参考。"""
    lower = name.lower()
    if name in AI_SOURCES:
        return "ai"
    if any(k in lower for k in NON_AI_KEYWORDS):
        return "ref"
    if any(k in lower for k in AI_KEYWORDS):
        return "ai"
    return "ref"


TARGET_AI = "ai-kb-ai"
TARGET_REF = "ai-kb-ref"
PAGE = 500


def counts_by_source(col) -> dict[str, int]:
    counts: dict[str, int] = {}
    offset = 0
    while True:
        part = col.get(include=["metadatas"], limit=1000, offset=offset)
        metas = part.get("metadatas") or []
        for md in metas:
            src = md.get("source")
            if src:
                counts[src] = counts.get(src, 0) + 1
        if len(metas) < 1000:
            break
        offset += 1000
    return counts


def copy_source(src_col, dst_col, source: str, delete_source: bool = False) -> int:
    """把某个来源的向量（含 embeddings）复制到目标集合。

    默认**保留原集合**：这样 AI 定向检索与全量检索两个库都能用，切换只改一个环境变量。
    只有显式加 --move 时才会从源集合删除。
    """
    copied = 0
    offset = 0
    while True:
        part = src_col.get(where={"source": source},
                           include=["embeddings", "documents", "metadatas"],
                           limit=PAGE, offset=offset)
        ids = part.get("ids") or []
        if not ids:
            break
        dst_col.add(ids=ids,
                    embeddings=[list(v) for v in part["embeddings"]],
                    documents=part["documents"],
                    metadatas=part["metadatas"])
        if delete_source:
            src_col.delete(ids=ids)
        copied += len(ids)
        offset += len(ids)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只打印计划）")
    parser.add_argument("--move", action="store_true", help="从原集合删除（危险，默认保留）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划")
    args = parser.parse_args()
    do_apply = args.apply and not args.dry_run

    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    names = [c.name for c in client.list_collections()]
    if settings.collection not in names:
        print(f"[失败] 找不到集合 {settings.collection}（现有：{names}）", file=sys.stderr)
        return 2

    src_col = client.get_collection(settings.collection)
    counts = counts_by_source(src_col)
    total = sum(counts.values())
    ai_parts = {n: c for n, c in counts.items() if classify(n) == "ai"}
    ref_parts = {n: c for n, c in counts.items() if classify(n) == "ref"}

    print(f"源集合 {settings.collection}：{len(counts)} 个文件 / {total} 片")
    print(f"\n→ {TARGET_AI}（AI 学习资料）：{len(ai_parts)} 个文件 / {sum(ai_parts.values())} 片")
    for n, c in sorted(ai_parts.items(), key=lambda x: -x[1]):
        print(f"    {c:6d}  {n}")
    print(f"\n→ {TARGET_REF}（通用技术参考）：{len(ref_parts)} 个文件 / {sum(ref_parts.values())} 片")
    for n, c in sorted(ref_parts.items(), key=lambda x: -x[1])[:12]:
        print(f"    {c:6d}  {n}")
    if len(ref_parts) > 12:
        print(f"    …… 另外 {len(ref_parts) - 12} 个文件")

    unknown = [n for n in counts if n not in AI_SOURCES and classify(n) == "ref"]
    print(f"\n按关键词归到 {TARGET_REF} 的文件：{len(unknown)} 个")

    if not do_apply:
        print("\n（这是预演。执行：--apply 复制；要清空原集合再加 --move。）")
        return 0

    for target in (TARGET_AI, TARGET_REF):
        if target not in [c.name for c in client.list_collections()]:
            client.create_collection(target, metadata={"hnsw:space": "cosine"})
    dst_ai = client.get_collection(TARGET_AI)
    dst_ref = client.get_collection(TARGET_REF)

    moved_ai = moved_ref = 0
    for name in ai_parts:
        moved_ai += copy_source(src_col, dst_ai, name, delete_source=args.move)
        print(f"  [AI] {name} 完成")
    for name in ref_parts:
        moved_ref += copy_source(src_col, dst_ref, name, delete_source=args.move)
        print(f"  [REF] {name} 完成")

    print(f"\n完成：{TARGET_AI} 复制 {moved_ai} 片（现有 {dst_ai.count()}），"
          f"{TARGET_REF} 复制 {moved_ref} 片（现有 {dst_ref.count()}）")
    if args.move:
        print(f"（--move 已从原集合删除，剩余 {src_col.count()} 片）")
    else:
        print(f"原集合 {settings.collection} 保持完好，仍可用（{src_col.count()} 片）")
    print(f"\n之后把 .env 里的 CHROMA_COLLECTION 设成 {TARGET_AI} 就只检索 AI 资料。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
