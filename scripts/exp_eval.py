"""A/B 实验用：只算检索召回率（不调生成，30 题约 15 秒）。

用法：
    $env:CHROMA_COLLECTION='exp-1024'
    .\\.venv\\Scripts\\python.exe scripts\\exp_eval.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import rag  # noqa: E402
from app.config import settings  # noqa: E402

TESTSET = ROOT / "data" / "testset.csv"


def page_hit(sources: list[dict], src: str, page: int) -> tuple[bool, int]:
    for rank, s in enumerate(sources, start=1):
        if s["file"] == src and s["page_start"] <= page <= s["page_end"]:
            return True, rank
    return False, 0


def main() -> int:
    rows = list(csv.DictReader(TESTSET.open(encoding="utf-8-sig")))
    count = rag.collection_count()
    hits, ranks = 0, []

    for row in rows:
        page = int(row["expected_page"])
        retrieved = rag.retrieve(row["question"], settings.top_k)
        ok, rank = page_hit(rag.make_sources(retrieved), row["expected_source"], page)
        hits += int(ok)
        if ok:
            ranks.append(rank)

    total = len(rows)
    print(f"集合={settings.collection} chunk_size={settings.chunk_size} "
          f"overlap={settings.chunk_overlap} 库内={count} 片")
    print(f"召回率 = {hits}/{total} = {hits / total:.1%}")
    if ranks:
        print(f"命中名次：平均 {sum(ranks) / len(ranks):.2f}，Top-1 命中 {ranks.count(1)} 题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
