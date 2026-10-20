"""T1.4 向量入库与检索：把切片写入 ChromaDB（持久化），并按问题检索 Top-5。

为什么这么做：
1. 复用 T1.2 的切分逻辑（scripts/02_chunk.py 的 build_chunks），不重复实现，避免两处
   切片规则漂移。
2. 用 Ollama 的 bge-m3 生成向量（计划书 v1.3），维度 1024。
3. 向量库持久化到 data/chroma：Chroma 用 PersistentClient，进程退出后数据仍在。
4. 幂等：每片用「来源+页码区间+文本哈希」生成确定性 id，重复入库不会产生重复条目；
   需要重来一次时用 --rebuild 先删集合。
5. 距离用余弦（collection_metadata={"hnsw:space": "cosine"}）。bge 向量未归一化，
   默认的 l2 距离会被向量长度影响，余弦才是语义检索该用的度量。

用法（在 D:\\ai-kb 下，用虚拟环境的解释器）：
    .\\.venv\\Scripts\\python.exe scripts\\04_store.py                       # 入库 d2l-zh
    .\\.venv\\Scripts\\python.exe scripts\\04_store.py --rebuild             # 先清空再入库
    .\\.venv\\Scripts\\python.exe scripts\\04_store.py --query "什么是自注意力"  # 入库后检索
    .\\.venv\\Scripts\\python.exe scripts\\04_store.py --all                 # 10 份全部入库
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 重要（踩过的坑）：chromadb 1.x 的 Rust 绑定在启动时要写临时目录，
# 而本机的 Python 进程运行在低完整性级别，写不了 C:\Users\...\Temp，
# 会在打开数据库时报 `(code: 14) unable to open database file`。
# 标准库 sqlite3 反而正常，所以很容易误判成权限或路径问题。
# 解决：在任何 chromadb 相关 import 之前，把 TEMP/TMP 指到仓库内的可写目录。
TMP_DIR = ROOT / "data" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(TMP_DIR)
os.environ["TMP"] = str(TMP_DIR)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # 关掉 Chroma 匿名统计，少刷日志

import argparse  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402

from langchain_community.vectorstores import Chroma  # noqa: E402
from langchain_ollama import OllamaEmbeddings  # noqa: E402

MATERIALS = ROOT / "materials"
CHROMA_DIR = ROOT / "data" / "chroma"
COLLECTION = "ai-kb"
DEFAULT_PDF = MATERIALS / "d2l-zh.pdf"
BATCH = 64  # 每批嵌入多少片：太小慢、太大会让单次请求超时

MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest")
BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def load_chunker():
    """加载同目录的 02_chunk.py（文件名以数字开头，不能直接 import）。"""
    path = Path(__file__).with_name("02_chunk.py")
    spec = importlib.util.spec_from_file_location("chunk02", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载切片脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chunk_id(c: dict) -> str:
    """确定性 id：同一份文件的同一片，重复入库时得到同一个 id。"""
    digest = hashlib.sha1(c["text"].encode("utf-8")).hexdigest()[:12]
    return f'{c["source"]}:{c["page_start"]}:{c["page_end"]}:{digest}'


def drop_collection() -> None:
    """删除已有集合（--rebuild 用）。"""
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    existing = client.list_collections()
    names = [getattr(c, "name", c) for c in existing]
    if COLLECTION in names:
        client.delete_collection(COLLECTION)
        print(f"[重建] 已删除集合 {COLLECTION}")


def build_vectorstore() -> Chroma:
    embedder = OllamaEmbeddings(model=MODEL, base_url=BASE_URL)
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embedder,
        persist_directory=str(CHROMA_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="向量入库与 Top-5 检索")
    parser.add_argument("--pdf", default=None, help="只入库指定 PDF（默认 d2l-zh.pdf）")
    parser.add_argument("--all", action="store_true", help="入库 materials 下全部 PDF")
    parser.add_argument("--rebuild", action="store_true", help="先删除集合再入库")
    parser.add_argument("--query", default=None, help="入库后执行一次检索")
    parser.add_argument("--k", type=int, default=5, help="检索条数，默认 5")
    args = parser.parse_args()

    if args.rebuild:
        drop_collection()

    vs = build_vectorstore()

    # ---------- 入库 ----------
    if args.all:
        pdfs = sorted(MATERIALS.glob("*.pdf"))
    elif args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        pdfs = [DEFAULT_PDF]

    chunker = load_chunker()
    existing = vs._collection.count()  # noqa: SLF001 - 只为打印现状

    if existing > 0 and not args.rebuild:
        print(f"[跳过入库] 集合里已有 {existing} 条数据；如需重来请加 --rebuild")
        total_chunks = existing
    else:
        total_chunks = 0
        for pdf in pdfs:
            try:
                chunks = chunker.build_chunks(pdf, 512, 50)
            except ValueError as exc:
                print(f"[错误] {pdf.name}: {exc}", file=sys.stderr)
                continue
            print(f"[切分] {pdf.name}: {len(chunks)} 片", flush=True)
            for i in range(0, len(chunks), BATCH):
                part = chunks[i:i + BATCH]
                vs.add_texts(
                    [c["text"] for c in part],
                    metadatas=[{k: c[k] for k in ("source", "page", "page_start", "page_end", "chars")}
                               for c in part],
                    ids=[chunk_id(c) for c in part],
                )
                done = min(i + BATCH, len(chunks))
                print(f"  嵌入进度 {done}/{len(chunks)}", flush=True)
            total_chunks += len(chunks)
            print(f"[入库] {pdf.name} 完成，累计应有 {total_chunks} 条", flush=True)

    count = vs._collection.count()  # noqa: SLF001
    print("=" * 64)
    print(f"向量库目录  : {CHROMA_DIR}")
    print(f"集合名      : {COLLECTION}")
    print(f"入库条数    : {count}")
    print("=" * 64)

    # ---------- 检索 ----------
    if args.query:
        print(f"\n【检索】{args.query}（Top-{args.k}，余弦距离）")
        hits = vs.similarity_search_with_score(args.query, k=args.k)
        for rank, (doc, distance) in enumerate(hits, start=1):
            md = doc.metadata
            span = f"p.{md['page_start']}" + (
                f"–{md['page_end']}" if md["page_end"] != md["page_start"] else "")
            sim = 1 - float(distance)  # cosine 距离换算成相似度
            head = doc.page_content[:60].replace("\n", " ")
            print(f"  #{rank} sim={sim:.4f} {md['source']} {span} | {head}")

    # ---------- 自检 ----------
    problems = []
    if count == 0:
        problems.append("向量库里没有任何数据")
    if args.query:
        if len(hits) != args.k:
            problems.append(f"检索返回 {len(hits)} 条，期望 {args.k} 条")
        if any(not d.metadata.get("source") or not d.metadata.get("page") for d, _ in hits):
            problems.append("检索结果缺少 source / page 元数据")
    if problems:
        print("\n[自检失败] " + "；".join(problems))
        return 1
    print("\n[自检] 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
