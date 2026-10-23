"""多次跑评测取均值，降低「单次 30 题、每题 3.3 分」带来的噪声。

为什么需要：30 题里每错一题就是 3.3 个百分点。单次跑到 73.3% 与 76.7% 其实只差 1 道题，
在没做多次采样前，分不清是退化还是随机波动。

用法：
  .venv\\Scripts\\python.exe scripts\\evaluate_repeat.py        # 默认 3 次
  .venv\\Scripts\\python.exe scripts\\evaluate_repeat.py 5      # 跑 5 次
"""
from __future__ import annotations

import csv
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "eval-results.csv"


def run_once() -> tuple[float, float, int, int]:
    """跑一次完整评测，返回（召回率, 准确率, 命中数, 正确数）。"""
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "evaluate.py")],
        cwd=str(ROOT), check=True, stdout=subprocess.DEVNULL,
    )
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    total = len(rows)
    hits = sum(1 for r in rows if r.get("hit") == "1")
    correct = sum(1 for r in rows if r.get("answer_correct") == "1")
    return hits / total, correct / total, hits, correct


def main() -> int:
    times = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    recalls, accuracies = [], []
    for i in range(1, times + 1):
        recall, accuracy, hits, correct = run_once()
        recalls.append(recall)
        accuracies.append(accuracy)
        print(f"第 {i}/{times} 次：召回 {recall:.1%}（{hits}）、准确 {accuracy:.1%}（{correct}）")

    print("=" * 56)
    print(f"召回率：均值 {statistics.mean(recalls):.1%}  "
          f"最低 {min(recalls):.1%}  最高 {max(recalls):.1%}  标准差 {statistics.pstdev(recalls)*100:.1f} 个点")
    print(f"准确率：均值 {statistics.mean(accuracies):.1%}  "
          f"最低 {min(accuracies):.1%}  最高 {max(accuracies):.1%}  标准差 {statistics.pstdev(accuracies)*100:.1f} 个点")
    if times > 1:
        spread = (max(accuracies) - min(accuracies)) * 100
        print(f"\n准确率极差 {spread:.1f} 个点（{spread/3.3:.1f} 道题）——"
              f"差异小于这个范围时，不能断言质量变化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
