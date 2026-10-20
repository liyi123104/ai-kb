"""T1.1 PDF 文本提取：逐页提取文本并保留页码，供后续切片使用。

用法（在 D:\\ai-kb 下，用虚拟环境的解释器）：
    .\\.venv\\Scripts\\python.exe scripts\\01_extract.py
    .\\.venv\\Scripts\\python.exe scripts\\01_extract.py "materials\\rag-lewis-2020.pdf"
    .\\.venv\\Scripts\\python.exe scripts\\01_extract.py xxx.pdf --chars 300
    .\\.venv\\Scripts\\python.exe scripts\\01_extract.py --out "%TEMP%\\pages.json"   # 落盘核对乱码

页码说明：这里的 page 是 PDF 的物理页序（第 1 页 = 1），与书上印刷页码可能相差一个偏移量
（封面、目录、前言会占页）。T1.6 做溯源时要如实标注这个口径。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pypdf import PdfReader

# pypdf 在遇到 Type1/CFF 字体时会反复告警“缺 fontTools”，一本书能刷几百行噪声，
# 淹没真正有用的输出。这里压到 ERROR：真出问题时仍会报错，但不再刷屏。
logging.getLogger("pypdf").setLevel(logging.ERROR)

# 默认样本：中文 813 页，最能暴露中文乱码问题
DEFAULT_PDF = Path(__file__).resolve().parent.parent / "materials" / "d2l-zh.pdf"


def extract_pages(pdf_path: Path) -> list[dict]:
    """逐页提取文本，返回 [{"page": 页码, "text": 文本, "chars": 字数}, ...]。

    参数
        pdf_path: PDF 文件路径
    返回
        按页码升序的列表，页码从 1 开始
    异常
        ValueError: 文件不存在、扩展名不是 .pdf、PDF 加密且无法打开
    """
    if not pdf_path.exists():
        raise ValueError(f"文件不存在：{pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"不是 PDF 文件：{pdf_path.name}")

    reader = PdfReader(str(pdf_path))

    # 有些 PDF 用空密码加密，能解开就继续；解不开就明确报错，不静默返回空文本
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError(f"PDF 已加密，无法用空密码打开：{pdf_path.name}")

    pages: list[dict] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            # pypdf 单页解析可能抛多种异常；一本书坏一页不该让整本失败，
            # 因此捕获后记录并继续（计划书 6.3 要求异常必须给出可读提示）。
            print(f"[警告] 第 {index} 页解析失败：{exc}", file=sys.stderr)
            text = ""
        # 去掉 NUL 等不可见字符，避免后续入库出错
        text = text.replace("\x00", "").strip()
        pages.append({"page": index, "text": text, "chars": len(text)})
    return pages


def cjk_ratio(text: str) -> float:
    """统计中文字符占比，用于判断中文 PDF 是否乱码或丢字。"""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF 文本提取（保留页码）")
    parser.add_argument("pdf", nargs="?", default=str(DEFAULT_PDF), help="PDF 路径")
    parser.add_argument("--chars", type=int, default=500, help="打印前多少字，默认 500")
    parser.add_argument("--sample-pages", type=int, default=3, help="展示前几页的页码映射")
    parser.add_argument("--out", default=None, help="可选：把逐页文本写成 UTF-8 JSON，便于核对乱码")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    try:
        pages = extract_pages(pdf_path)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    full_text = "\n".join(p["text"] for p in pages)
    empty_pages = [p["page"] for p in pages if p["chars"] == 0]
    total_chars = len(full_text)
    ratio = cjk_ratio(full_text)

    print("=" * 64)
    print(f"文件      : {pdf_path.name}")
    print(f"页数      : {len(pages)}")
    print(f"总字符数  : {total_chars}")
    print(f"平均每页  : {(total_chars / len(pages)):.0f} 字" if pages else "平均每页  : 0")
    print(f"空页数    : {len(empty_pages)}" + (f" -> {empty_pages[:10]}" if empty_pages else ""))
    print(f"中文占比  : {ratio:.1%}（中文资料应明显高于 0；接近 0 说明乱码、丢字或本身就是英文）")
    print("=" * 64)

    print(f"\n【前 {args.chars} 字】")
    print(full_text[: args.chars])

    print(f"\n【页码映射（前 {args.sample_pages} 页）】")
    for p in pages[: args.sample_pages]:
        head = p["text"][:40].replace("\n", " ")
        print(f"  第 {p['page']} 页（{p['chars']} 字）：{head}")

    if args.out:
        out_path = Path(args.out)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps({"source": pdf_path.name, "pages": pages}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            print(f"\n[输出] 逐页文本已写入 {out_path}")
        except OSError as exc:
            # 计划书 6.3：异常必须给出可读提示，不能静默失败
            print(f"\n[错误] 写文件失败：{out_path}（{exc}）", file=sys.stderr)

    # 自检：页数、字符数必须 > 0；中文占比只作提示（英文资料本来就很低）
    problems = []
    if not pages:
        problems.append("没有解析出任何页")
    if total_chars == 0:
        problems.append("提取到 0 个字符（可能是扫描件或解析失败）")
    if problems:
        print("\n[自检失败] " + "；".join(problems))
        return 1
    if ratio < 0.05:
        print("\n[提示] 中文占比低于 5%：若这本应是中文资料，请检查是否扫描件或字体缺映射")
    print("\n[自检] 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
