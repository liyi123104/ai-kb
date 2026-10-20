"""A/B 实验用：按环境变量指定的参数把 materials 全量入库到独立集合。

用法（每个变体一个集合，互不覆盖，基线集合 ai-kb 保持不动）：

    $env:CHROMA_COLLECTION='exp-1024'; $env:CHUNK_SIZE='1024'; $env:CHUNK_OVERLAP='50'
    .\\.venv\\Scripts\\python.exe scripts\\exp_ingest.py --all
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse  # noqa: E402

from app import rag  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="实验用入库（按环境变量切分片参数与集合名）")
    parser.add_argument("--all", action="store_true", help="入库 materials 下全部 PDF")
    args = parser.parse_args()

    if settings.collection == "ai-kb":
        print("[拒绝] 实验不能写入基线集合 ai-kb，请用 CHROMA_COLLECTION 指定新集合", file=sys.stderr)
        return 2

    pdfs = sorted((ROOT / "materials").glob("*.pdf")) if args.all else \
        sorted((ROOT / "materials").glob("*.pdf"))[:1]

    print(f"[实验] 集合={settings.collection} chunk_size={settings.chunk_size} "
          f"overlap={settings.chunk_overlap} 文件数={len(pdfs)}")

    vs = rag.get_vectorstore()
    try:
        vs._collection.delete(where={})  # noqa: SLF001 - 清空本集合，避免上一轮残留
    except Exception:
        pass

    total = 0
    for pdf in pdfs:
        try:
            result = rag.ingest_file(pdf)
        except ValueError as exc:
            print(f"  [跳过] {pdf.name}: {exc}")
            continue
        total += result["chunks"]
        print(f"  {pdf.name}: {result['chunks']} 片", flush=True)

    print(f"[完成] 集合 {settings.collection} 共 {total} 片")
    return 0


if __name__ == "__main__":
    sys.exit(main())
