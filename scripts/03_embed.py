"""T1.3 生成向量：用 Ollama 的 bge-m3 做 embedding，并验证维度与语义相似度。

为什么用 Ollama：计划书 v1.3 修订记录已确认 —— Ollama 里已有 bge-m3（1.08GB），
走 OllamaEmbeddings 无需再从 HuggingFace 下载 2.27GB，也不占 C 盘模型缓存。

验收逻辑（对应计划书 T1.3）：
  1. 向量维度必须是 1024（bge-m3 输出维度）
  2. 语义相近的两句，余弦相似度 > 0.7
  3. 无关的两句，余弦相似度 < 0.3

用法（在 D:\\ai-kb 下，用虚拟环境的解释器）：
    .\\.venv\\Scripts\\python.exe scripts\\03_embed.py
    .\\.venv\\Scripts\\python.exe scripts\\03_embed.py --pair "第一句" "第二句"
    .\\.venv\\Scripts\\python.exe scripts\\03_embed.py --model bge-m3:latest
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from langchain_ollama import OllamaEmbeddings

# 默认模型从环境变量取，避免硬编码（计划书 6.3）；T2.2 会统一挪进 .env / app/config.py
DEFAULT_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest")
DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# 测试文本：一对应当高分，一对应当低分。内容与项目资料同域，避免「用无关领域测出虚高」。
PAIRS = [
    {
        "expect": "high",
        "a": "Transformer 的核心是自注意力机制，它让每个位置都能直接关注到序列中的所有位置。",
        "b": "自注意力机制是 Transformer 模型的关键结构，每个词元都能与全序列交互。",
    },
    {
        "expect": "low",
        "a": "Transformer 的核心是自注意力机制，它让每个位置都能直接关注到序列中的所有位置。",
        "b": "今天的午饭是红烧肉配米饭，饭后我打算去操场散步半小时。",
    },
]


def cosine(u: np.ndarray, v: np.ndarray) -> float:
    """余弦相似度；先做零向量保护，避免除零警告。"""
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0 or nv == 0:
        return 0.0
    return float(np.dot(u, v) / (nu * nv))


def main() -> int:
    parser = argparse.ArgumentParser(description="bge-m3 向量相似度验证")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama 模型名，默认 {DEFAULT_MODEL}")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Ollama 服务地址")
    parser.add_argument("--pair", nargs=2, metavar=("TEXT_A", "TEXT_B"),
                        help="可选：只算指定两句话的相似度")
    args = parser.parse_args()

    embedder = OllamaEmbeddings(model=args.model, base_url=args.base_url)

    pairs = PAIRS if not args.pair else [{"expect": "unknown", "a": args.pair[0], "b": args.pair[1]}]
    texts = [t for p in pairs for t in (p["a"], p["b"])]

    try:
        vectors = embedder.embed_documents(texts)
    except Exception as exc:  # noqa: BLE001
        # 常见原因：Ollama 没启动、模型没拉取、端口不通。给可读提示，不吞异常。
        print(f"[错误] 调用 Ollama 失败：{exc}", file=sys.stderr)
        print(f"       排查：1) ollama 服务是否在跑（{args.base_url}）"
              f"  2) 模型是否已拉取（ollama pull {args.model}）", file=sys.stderr)
        return 1

    dims = [len(v) for v in vectors]
    print("=" * 64)
    print(f"模型        : {args.model}")
    print(f"服务地址    : {args.base_url}")
    print(f"文本条数    : {len(texts)}")
    print(f"向量维度    : {dims}（应全部为 1024）")
    print(f"向量类型    : {type(vectors[0][0]).__name__}")
    print("=" * 64)

    results = []
    for i, p in enumerate(pairs):
        u = np.array(vectors[2 * i], dtype=float)
        v = np.array(vectors[2 * i + 1], dtype=float)
        sim = cosine(u, v)
        results.append((p["expect"], sim))
        print(f"\n[{'相近' if p['expect'] == 'high' else '无关' if p['expect'] == 'low' else '自定义'}] 余弦相似度 = {sim:.4f}")
        print(f"  A: {p['a'][:50]}")
        print(f"  B: {p['b'][:50]}")

    # 自检：三条验收标准全部机器判定
    problems = []
    if any(d != 1024 for d in dims):
        problems.append(f"向量维度不是 1024：{set(dims)}")
    for expect, sim in results:
        if expect == "high" and sim <= 0.7:
            problems.append(f"相近文本相似度 {sim:.4f} ≤ 0.7")
        if expect == "low" and sim >= 0.3:
            problems.append(f"无关文本相似度 {sim:.4f} ≥ 0.3")
    print()
    if problems:
        print("[自检失败] " + "；".join(problems))
        return 1
    print("[自检] 通过：维度 1024，相近 > 0.7，无关 < 0.3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
