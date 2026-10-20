"""T4.2 评测脚本：批量跑测试集，统计检索召回率与答案准确率，导出 CSV。

指标定义（与计划书 3.2 一致）：
  检索召回率 = 正确片段进入 Top-5 的题数 / 总题数
      「正确片段」判定：Top-5 里存在一条，文件名等于 expected_source，
      且 expected_page 落在该条的 [page_start, page_end] 区间内。
  答案准确率 = 答案覆盖正确要点的题数 / 总题数
      要点判定先用「期望答案的 4-gram 命中率」自动打分，再人工复核修正。
  首字延迟 / 完整耗时：本次记录检索耗时与整轮耗时（流式首字延迟由 T3.4 单独验证）。

用法：
    .\\.venv\\Scripts\\python.exe scripts\\evaluate.py
    .\\.venv\\Scripts\\python.exe scripts\\evaluate.py --k 5 --out data/eval-results.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import rag  # noqa: E402
from app.llm import get_llm  # noqa: E402


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def coverage(expected: str, generated: str) -> float:
    """期望答案的 4-gram 有多少比例出现在生成答案里（自动打分，供人工复核参考）。"""
    exp, gen = normalize(expected), normalize(generated)
    if not exp or not gen:
        return 0.0
    if exp in gen:
        return 1.0
    grams = [exp[i:i + 4] for i in range(0, max(len(exp) - 3, 1), 2)]
    if not grams:
        return 0.0
    return sum(1 for g in grams if g in gen) / len(grams)


def page_hit(sources: list[dict], expected_source: str, expected_page: int) -> tuple[bool, int]:
    """判断 Top-K 里是否命中正确出处，返回 (是否命中, 首次命中的名次[1 起])。"""
    for rank, s in enumerate(sources, start=1):
        if s["file"] != expected_source:
            continue
        if s["page_start"] <= expected_page <= s["page_end"]:
            return True, rank
    return False, 0


JUDGE_PROMPT = """判断「模型答案」是否覆盖了「标准答案」的关键要点。

判定标准：
- 允许语言不同（标准答案是英文、模型用中文答，只要事实一致就算正确）。
- 允许改写、允许补充细节；只要关键事实（概念、数值、结论）一致即算正确。
- 模型答非所问、答成别的概念、或只说「资料中没有相关内容」而标准答案存在，算错误。

问题：{question}
标准答案：{expected}
模型答案：{generated}

只输出一个词：正确 或 错误。"""


def llm_judge(llm, question: str, expected: str, generated: str) -> tuple[bool, str]:
    """语义判定答案是否正确（弥补 4-gram 比对在跨语言场景下的失效）。"""
    if not generated or generated.startswith("[失败]"):
        return False, "生成失败"
    try:
        resp = llm.invoke(JUDGE_PROMPT.format(question=question, expected=expected,
                                              generated=generated[:900]))
        text = (resp.content if isinstance(resp.content, str) else str(resp.content)).strip()
    except Exception as exc:  # noqa: BLE001
        return False, f"评审失败：{exc}"
    correct = "正确" in text and "错误" not in text
    return correct, text[:20]


def main() -> int:
    parser = argparse.ArgumentParser(description="批量评测（召回率 / 准确率 / 耗时）")
    parser.add_argument("--testset", default=str(ROOT / "data" / "testset.csv"))
    parser.add_argument("--k", type=int, default=5, help="检索条数，默认 5")
    parser.add_argument("--out", default=str(ROOT / "data" / "eval-results.csv"))
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题（调试用，0=全部）")
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.testset).open(encoding="utf-8-sig")))
    if args.limit:
        rows = rows[: args.limit]
    print(f"[评测] 题目 {len(rows)} 道，Top-{args.k}")
    llm = get_llm()

    results = []
    for i, row in enumerate(rows, start=1):
        question = row["question"]
        expected_page = int(row["expected_page"])

        t0 = time.perf_counter()
        hits = rag.retrieve(question, args.k)
        t_retrieve = time.perf_counter() - t0
        sources = rag.make_sources(hits)

        hit, rank = page_hit(sources, row["expected_source"], expected_page)

        t1 = time.perf_counter()
        try:
            answer = rag.answer(question)
            answer_text = answer["answer"]
        except Exception as exc:  # noqa: BLE001 - 单题失败不应中断整轮评测
            answer_text = f"[失败] {exc}"
        t_answer = time.perf_counter() - t1

        score = coverage(row["expected_answer"], answer_text)
        correct, judge_note = llm_judge(llm, question, row["expected_answer"], answer_text)
        results.append({
            "id": row["id"],
            "question": question,
            "expected_answer": row["expected_answer"],
            "expected_source": row["expected_source"],
            "expected_page": expected_page,
            "hit": 1 if hit else 0,
            "hit_rank": rank,
            "top1_source": sources[0]["file"] if sources else "",
            "top1_page": sources[0]["page_label"] if sources else "",
            "auto_coverage": round(score, 3),
            "answer_correct": 1 if correct else 0,
            "judge_note": judge_note,
            "retrieve_seconds": round(t_retrieve, 2),
            "answer_seconds": round(t_answer, 2),
            "answer": answer_text.replace("\n", " ")[:300],
        })
        print(f"  [{i:02d}/{len(rows)}] 命中={'Y' if hit else 'N'} rank={rank} "
              f"coverage={score:.2f} judge={"Y" if correct else "N"} {t_retrieve:.2f}s+{t_answer:.1f}s | {question[:30]}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    total = len(results)
    recall = sum(r["hit"] for r in results) / total
    accuracy = sum(r["answer_correct"] for r in results) / total
    avg_ret = sum(r["retrieve_seconds"] for r in results) / total
    avg_ans = sum(r["answer_seconds"] for r in results) / total
    print("=" * 64)
    print(f"检索召回率   : {recall:.1%}  ({sum(r['hit'] for r in results)}/{total})  目标 ≥ 80%")
    print(f"答案准确率   : {accuracy:.1%}  ({sum(r['answer_correct'] for r in results)}/{total})  目标 ≥ 70%（自动初判，待人工复核）")
    print(f"检索平均耗时 : {avg_ret:.2f}s")
    print(f"整轮平均耗时 : {avg_ans:.1f}s（含本地模型生成）")
    print(f"输出         : {out}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
