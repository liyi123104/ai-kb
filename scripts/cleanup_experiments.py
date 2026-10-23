"""清理实验集合，回收磁盘。

背景：E1/E4 等实验留下了 5 个 exp-* 集合，共 49,728 片，占向量库约 60% 的空间。
结论已写进 docs/experiments.md，向量本身可以删；本脚本默认只列清单，加 --apply 才删。

用法：
  .venv\\Scripts\\python.exe scripts/cleanup_experiments.py            # 看清单
  .venv\\Scripts\\python.exe scripts/cleanup_experiments.py --apply    # 真删
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

KEEP = {"ai-kb", "ai-kb-ai", "ai-kb-ref"}
PREFIX = "exp-"


def dir_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / 1024 / 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正删除（默认只列清单）")
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    collections = client.list_collections()
    targets = [c for c in collections if c.name.startswith(PREFIX) and c.name not in KEEP]

    print(f"向量库目录：{settings.chroma_dir}（当前 {dir_size_mb(settings.chroma_dir):.0f} MB）")
    print(f"共 {len(collections)} 个集合，其中可清理 {len(targets)} 个：\n")

    total_chunks = 0
    for col in targets:
        n = col.count()
        total_chunks += n
        print(f"  {col.name:16s} {n:6d} 片")

    protected = [c.name for c in collections if c.name in KEEP]
    print(f"\n保留：{', '.join(protected)}")
    print(f"可回收：{len(targets)} 个集合 / {total_chunks} 片")

    if not args.apply:
        print("\n（这是预演。加 --apply 才会真正删除。）")
        return 0

    for col in targets:
        client.delete_collection(col.name)
        print(f"  已删除 {col.name}")
    print(f"\n完成：目录现在 {dir_size_mb(settings.chroma_dir):.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
