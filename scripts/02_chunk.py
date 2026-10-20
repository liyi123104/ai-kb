"""T1.2 文本切片：按 chunk_size=512 / overlap=50 切分，保留来源与页码区间。

设计要点（为什么这么做）：
1. 跨页切分：把整份 PDF 正文当成一条连续文本流来切，避免每页尾部产生大量很短的
   碎片（碎片会污染向量库、拉低召回）。chunk 允许横跨页边界。
2. 页码不撒谎：因为允许跨页，元数据同时记 page_start / page_end；page 取 page_start，
   与计划书「source + page」约定兼容。
3. 强制重叠：LangChain 的 chunk_overlap 是按「切分单元」整块回退的，不是按字符。
   PDF 抽取出的文本一行往往 60~70 字符，比 overlap=50 还长，导致回退时一行都留不下，
   实测相邻重叠经常是 0。因此切片后用 _enforce_overlap() 做边界补齐：从上一片尾部
   借 50 字，必要时截掉本片尾巴，保证「长度 ≤512 且相邻重叠 ≥50」两条同时成立。

用法（在 D:\\ai-kb 下，用虚拟环境的解释器）：
    .\\.venv\\Scripts\\python.exe scripts\\02_chunk.py
    .\\.venv\\Scripts\\python.exe scripts\\02_chunk.py "materials\\rag-lewis-2020.pdf"
    .\\.venv\\Scripts\\python.exe scripts\\02_chunk.py --sample 5 --out data\\chunks-d2l.jsonl
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from bisect import bisect_right
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

logging.getLogger("pypdf").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "materials" / "d2l-zh.pdf"


def load_extractor():
    """加载同目录的 01_extract.py（文件名以数字开头，不能直接 import）。"""
    path = Path(__file__).with_name("01_extract.py")
    spec = importlib.util.spec_from_file_location("extract01", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载提取脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_page_spans(pages: list[dict]) -> tuple[str, list[int], list[tuple[int, int, int]]]:
    """把逐页文本拼成整篇，并记录每页的字符区间。

    返回
        full_text: 拼接后的整篇文本（页与页之间用 "\\n" 连接）
        starts:    每页起始偏移，供二分查找
        spans:     [(页起始, 页结束, 页码), ...]
    """
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    offset = 0
    for p in pages:
        text = p["text"]
        spans.append((offset, offset + len(text), p["page"]))
        parts.append(text)
        offset += len(text) + 1  # +1 是 join 用的 "\n"
    return "\n".join(parts), [s[0] for s in spans], spans


def pages_of_range(spans: list[tuple[int, int, int]], starts: list[int],
                   begin: int, end: int) -> tuple[int, int]:
    """给定字符区间，返回被覆盖的首末页码。"""
    if not spans:
        return 0, 0
    idx = max(bisect_right(starts, begin) - 1, 0)
    page_start = spans[idx][2]
    page_end = page_start
    i = idx
    while i < len(spans) and spans[i][0] < end:
        page_end = spans[i][2]
        i += 1
    return page_start, page_end


def enforce_overlap(full_text: str, bounds: list[tuple[int, int]],
                    chunk_size: int, overlap: int) -> list[tuple[int, int]]:
    """把切分器给出的边界调整为「长度 ≤ chunk_size 且相邻重叠 ≥ overlap」。

    做法：以每片的结束位置为准，起点默认回退到 end-chunk_size（最长 512）；
    若这样与上一片的重叠不足 overlap，就把起点再往前挪到 prev_end-overlap，
    并同步截短结尾以保持长度上限。这样「内容仍来自切分器的边界」，
    只是补上了它没做到的重叠。
    """
    fixed: list[tuple[int, int]] = []
    prev_end = 0
    for i, (start, end) in enumerate(bounds):
        end = min(end, len(full_text))
        start = max(end - chunk_size, 0)
        if i > 0 and start > prev_end - overlap:
            start = max(prev_end - overlap, 0)
            end = min(start + chunk_size, len(full_text))
        if start >= end:  # 极端情况：空片，跳过
            continue
        fixed.append((start, end))
        prev_end = end
    return fixed


def build_chunks(pdf_path: Path, chunk_size: int = 512, overlap: int = 50) -> list[dict]:
    """把一份 PDF 切成带页码区间的 chunk 列表（T1.4 入库直接复用）。

    返回
        [{"source", "page", "page_start", "page_end", "chars", "text"}, ...]
    异常
        ValueError: 交给 extract_pages 处理（文件不存在/非 PDF/加密）
    """
    extractor = load_extractor()
    pages = extractor.extract_pages(pdf_path)
    full_text, starts, spans = build_page_spans(pages)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        add_start_index=True,
        separators=["\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ",", " ", ""],
    )
    docs = splitter.create_documents([full_text])
    bounds = [(int(d.metadata.get("start_index", 0)),
               int(d.metadata.get("start_index", 0)) + len(d.page_content)) for d in docs]
    fixed = enforce_overlap(full_text, bounds, chunk_size, overlap)

    chunks: list[dict] = []
    for start, end in fixed:
        # 不做 strip：行首的空白一旦被去掉，真实内容重叠就会从 50 掉到 48/49，
        # 反而让验收标准失真。只用 strip() 判空。
        text = full_text[start:end]
        if not text.strip():
            continue
        page_start, page_end = pages_of_range(spans, starts, start, end)
        chunks.append({
            "source": pdf_path.name,
            "page": page_start,
            "page_start": page_start,
            "page_end": page_end,
            "chars": len(text),
            "text": text,
        })
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="文本切片（512/50，保留页码区间）")
    parser.add_argument("pdf", nargs="?", default=str(DEFAULT_PDF), help="PDF 路径")
    parser.add_argument("--chunk-size", type=int, default=512, help="切片长度，默认 512")
    parser.add_argument("--overlap", type=int, default=50, help="重叠长度，默认 50")
    parser.add_argument("--sample", type=int, default=3, help="打印多少个切片样例")
    parser.add_argument("--out", default=None, help="可选：切片结果写入 JSONL，供 T1.4 入库")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    try:
        chunks = build_chunks(pdf_path, args.chunk_size, args.overlap)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    lengths = [c["chars"] for c in chunks]

    def content_overlap(a: str, b: str) -> int:
        """a 的后缀与 b 的前缀最长公共长度：这才是「内容上真的重叠了多少」。"""
        for k in range(min(len(a), len(b)), 0, -1):
            if a[-k:] == b[:k]:
                return k
        return 0

    overlaps = [content_overlap(chunks[i]["text"], chunks[i + 1]["text"])
                for i in range(len(chunks) - 1)]

    print("=" * 64)
    print(f"文件        : {pdf_path.name}")
    print(f"页数        : {len(pages)}")
    print(f"总字符      : {len(full_text)}")
    print(f"切片参数    : chunk_size={args.chunk_size}, overlap={args.overlap}")
    print(f"切片数量    : {len(chunks)}")
    if lengths:
        print(f"长度        : 最小 {min(lengths)}, 最大 {max(lengths)}, 平均 {sum(lengths)/len(lengths):.1f}")
        print(f"超长切片    : {sum(1 for x in lengths if x > args.chunk_size)} 个（应为 0）")
        print(f"跨页切片    : {sum(1 for c in chunks if c['page_end'] > c['page_start'])} 个")
    if overlaps:
        print(f"相邻重叠    : 最小 {min(overlaps)}, 最大 {max(overlaps)}"
              f"（应 ≥ {args.overlap}）")
        print(f"重叠不足的相邻对: {sum(1 for x in overlaps if x < args.overlap)} 个（应为 0）")
    print("=" * 64)

    print(f"\n【切片样例（前 {args.sample} 个）】")
    for i, c in enumerate(chunks[: args.sample], start=1):
        head = c["text"][:60].replace("\n", " ")
        span = f"p.{c['page_start']}" + (f"–{c['page_end']}" if c["page_end"] != c["page_start"] else "")
        print(f"  #{i} {span} {c['chars']}字 | {head}")

    if args.out:
        out_path = Path(args.out)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8") as fh:
                for c in chunks:
                    fh.write(json.dumps(c, ensure_ascii=False) + "\n")
            print(f"\n[输出] {len(chunks)} 个切片已写入 {out_path}")
        except OSError as exc:
            print(f"\n[错误] 写文件失败：{out_path}（{exc}）", file=sys.stderr)

    # 自检：三条验收标准全部机器可判
    problems = []
    if not chunks:
        problems.append("没有产生任何切片")
    if any(x > args.chunk_size for x in lengths):
        problems.append(f"存在超过 {args.chunk_size} 字的切片")
    if any(x < args.overlap for x in overlaps):
        problems.append(f"存在相邻重叠小于 {args.overlap} 的切片对")
    if any((not c["source"]) or (not c["page"]) for c in chunks):
        problems.append("存在缺少 source / page 元数据的切片")
    if problems:
        print("\n[自检失败] " + "；".join(problems))
        return 1
    print("\n[自检] 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
