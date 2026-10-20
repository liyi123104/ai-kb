"""T4.1 生成 30 题测试集：从每份资料的正文切片里出题，答案必须能在原文中核对。

为什么这么生成：
  计划书要求「从资料出 30 个有标准答案的问题」，且要能定位到页码。手工从 10 份 PDF 里
  挑题容易挑到目录页或跨页断句；这里的做法是：
    1) 从向量库里按文件抽样正文切片（自动跳过目录点线/二进制块等噪声）；
    2) 让本地模型只依据这一段出一问一答，并要求答案照抄原文；
    3) 机器校验：答案要点必须能在原切片里找到，找不到就丢弃重试（防幻觉）；
    4) 出处直接取切片的 source + page_start，保证页码可核对。
  即「模型出题 + 原文校验 + 元数据取自切片」，避免测试集本身被幻觉污染。

用法：
    .\\.venv\\Scripts\\python.exe scripts\\06_make_testset.py
    .\\.venv\\Scripts\\python.exe scripts\\06_make_testset.py --per-file 4 --out data/testset.csv
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 从 scripts/ 下运行时，sys.path[0] 是 scripts/，需要把仓库根加进来才能 import app.*
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TMP_DIR = ROOT / "data" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(TMP_DIR)
os.environ["TMP"] = str(TMP_DIR)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from collections import defaultdict  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.rag import get_vectorstore, is_low_value  # noqa: E402

PROMPT = """下面是一段来自学习资料的原文。请只依据这段原文，出 1 道需要一两句话回答的问题，并给出答案。

要求：
1. 问题必须能仅凭这段原文回答，不要问原文没写的内容。
2. 答案必须直接取自原文（可以稍微改写语序），不要引入任何外部知识。
3. 问题要具体，优先问：概念定义、工作原理、两者的区别、某结构的作用、处理流程。
4. 禁止出这些题型：问年份、问页数、问作者/标题/会议、问「文中提到」「该图」、
   答案是孤立数字且该数字不是核心概念（如模型维度、数据集规模）的问题。
5. 问题要能独立看懂，不要出现「这段」「本文」等指代。
6. 只输出 JSON，不要解释，格式：
{{"question": "问题", "answer": "答案要点"}}

原文：
{chunk}
"""


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


# 参考文献/标题页的切片会产出「论文标题是什么」「发表在哪个会议」这类无价值题目，先剔除
REF_PATTERNS = [
    r"arXiv\s*preprint", r"Proceedings of", r"In Proceedings", r"\bpp\.\s*\d+",
    r"Association for Computational Linguistics", r"^\s*\[\d+\]",
]
BAD_QUESTION_RE = re.compile(
    r"(标题是什么|作者是谁|发表在|哪个会议|哪一卷|哪个期刊|Proceedings|这本书|该论文的标题|"
    r"这篇论文的标题|文献的标题|属于哪种类型|这段原文|这段文本|本文提到)"
)


def looks_like_reference(text: str) -> bool:
    """参考文献页判定：多个引用特征同时出现，或年份密度过高。"""
    hits = sum(1 for p in REF_PATTERNS if re.search(p, text, re.I))
    years = len(re.findall(r"\b(19|20)\d{2}\b", text))
    return hits >= 2 or years >= 6


def answer_supported(answer: str, chunk: str) -> bool:
    """校验答案要点是否真在原文里：按 4 字片段命中率判断，避免整句改写导致误判。"""
    ans, src = normalize(answer), normalize(chunk)
    if not ans:
        return False
    if ans in src:
        return True
    grams = [ans[i:i + 4] for i in range(0, max(len(ans) - 3, 1), 2)]
    if not grams:
        return False
    hit = sum(1 for g in grams if g in src)
    return hit / len(grams) >= 0.6


def ask_llm(llm, chunk: str) -> dict | None:
    try:
        resp = llm.invoke(PROMPT.format(chunk=chunk[:1200]))
    except Exception as exc:  # noqa: BLE001
        print(f"  [警告] 模型调用失败：{exc}", file=sys.stderr)
        return None
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    q, a = (data.get("question") or "").strip(), (data.get("answer") or "").strip()
    if len(q) < 6 or len(a) < 4:
        return None
    return {"question": q, "answer": a}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 30 题测试集")
    parser.add_argument("--per-file", type=int, default=3, help="每个文件出几题（默认 3，10 文件=30 题）")
    parser.add_argument("--out", default=str(ROOT / "data" / "testset.csv"))
    args = parser.parse_args()

    vs = get_vectorstore()
    data = vs._collection.get(include=["documents", "metadatas"], limit=20000)
    by_file: dict[str, list[dict]] = defaultdict(list)
    skipped_ref = 0
    for text, md in zip(data["documents"], data["metadatas"]):
        if is_low_value(text) or len(text) < 300:
            continue
        if looks_like_reference(text):
            skipped_ref += 1
            continue
        by_file[md["source"]].append({"text": text, "md": md})

    print(f"[抽样] 可用文件 {len(by_file)} 个，"
          f"候选切片 {sum(len(v) for v in by_file.values())} 条"
          f"（剔除参考文献类 {skipped_ref} 条）")

    llm = get_llm()
    rnd = random.Random(20261020)  # 固定种子，保证可复现
    rows: list[dict] = []
    seen_questions: set[str] = set()
    qid = 0

    # 轮流从各文件抽候选，直到凑够 target 题（按文件轮转，保证覆盖均衡）
    queues: dict[str, list[dict]] = {}
    for source, pool in by_file.items():
        shuffled = pool[:]
        rnd.shuffle(shuffled)
        queues[source] = shuffled

    target = args.per_file * len(by_file)
    attempted = 0
    while len(rows) < target and any(queues.values()):
        progressed = False
        for source in sorted(queues):
            if len(rows) >= target:
                break
            while queues[source]:
                candidate = queues[source].pop()
                attempted += 1
                qa = ask_llm(llm, candidate["text"])
                if not qa:
                    continue
                if BAD_QUESTION_RE.search(qa["question"]):
                    continue
                key = normalize(qa["question"])
                if key in seen_questions:
                    continue
                if not answer_supported(qa["answer"], candidate["text"]):
                    continue
                seen_questions.add(key)
                qid += 1
                rows.append({
                    "id": qid,
                    "question": qa["question"],
                    "expected_answer": qa["answer"],
                    "expected_source": source,
                    "expected_page": candidate["md"]["page_start"],
                })
                progressed = True
                print(f"  [{qid:02d}] {source} p.{candidate['md']['page_start']} | {qa['question'][:40]}")
                break  # 每个文件一轮只出一题，保证均衡
        if not progressed:
            break
    print(f"[尝试] 共试 {attempted} 段，成功出题 {len(rows)} 道")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "question", "expected_answer",
                                                "expected_source", "expected_page"])
        writer.writeheader()
        writer.writerows(rows)

    files_covered = len({r["expected_source"] for r in rows})
    with_page = sum(1 for r in rows if r["expected_page"])
    print("=" * 64)
    print(f"题目数量  : {len(rows)}")
    print(f"覆盖文件  : {files_covered}")
    print(f"有页码    : {with_page}/{len(rows)} = {with_page / max(len(rows), 1):.0%}")
    print(f"输出      : {out}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
