"""把项目打成可分发的 zip。

包含：代码、脚本、前端源码、文档、测试集与评测结果、启动脚本、配置模板。
排除：虚拟环境、node_modules、向量库、语料、上传文件、浏览器临时目录、.env（含密钥）。

用法：
  .venv\\Scripts\\python.exe scripts\\package.py          # 源码包（约 0.7MB）
  .venv\\Scripts\\python.exe scripts\\package.py --full   # 完整包（含向量库与语料）
产物：dist/ai-kb-src-YYYYMMDD.zip 或 dist/ai-kb-full-YYYYMMDD.zip
"""
from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dist"

# 目录级白名单：这些目录整个打进去（会再按 EXCLUDE 过滤）
INCLUDE_DIRS = ["app", "scripts", "docs", "web/src"]
# 单文件白名单
INCLUDE_FILES = [
    "README.md", "requirements.txt", "Dockerfile", "docker-compose.yml",
    "ui_streamlit.py", ".env.example", ".gitignore", ".gitattributes",
    "start.bat", "stop.bat",
    "web/package.json", "web/package-lock.json", "web/vite.config.js",
    "web/index.html", "web/Dockerfile", "web/nginx.conf",
    "data/testset.csv", "data/eval-results.csv", "data/eval-results-deepseek.csv",
]
# 任何层级命中这些片段就跳过（相对路径用 / 分隔）
EXCLUDE_PARTS = {
    "__pycache__", ".venv", "node_modules", "dist", ".git", "data/tmp",
    ".pytest_cache", "edge-profile",
}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log"}
EXCLUDE_NAMES = {".env", ".DS_Store", "Thumbs.db"}


def should_skip(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_PARTS:
        return True
    if any("edge-profile" in p for p in rel.parts):
        return True
    if rel.name in EXCLUDE_NAMES:
        return True
    if rel.suffix.lower() in EXCLUDE_SUFFIX:
        return True
    return False


# --full 时额外打进去的数据目录（向量库、原始语料、上传文件）
FULL_DIRS = ["data/chroma", "data/uploads", "materials"]
FULL = False  # 由 __main__ 根据命令行参数设置


def collect() -> list[Path]:
    files: list[Path] = []
    dirs = list(INCLUDE_DIRS) + (FULL_DIRS if FULL else [])
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not should_skip(p.relative_to(ROOT)):
                files.append(p)
    for f in INCLUDE_FILES:
        p = ROOT / f
        if p.is_file() and not should_skip(Path(f)):
            files.append(p)
    return sorted(set(files))


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    kind = "full" if FULL else "src"
    target = OUT_DIR / f"ai-kb-{kind}-{date.today():%Y%m%d}.zip"
    files = collect()

    # 安全闸：绝不允许 .env 进包
    leaked = [f for f in files if f.name == ".env"]
    if leaked:
        raise SystemExit(f"拒绝打包：检测到 .env（{leaked}）")

    # PDF / 图片本身已压缩，再压没收益还慢，直接存储
    STORED_SUFFIX = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".zip"}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if f.suffix.lower() in STORED_SUFFIX:
                zf.write(f, arcname=f"ai-kb/{rel}", compress_type=zipfile.ZIP_STORED)
            else:
                zf.write(f, arcname=f"ai-kb/{rel}")

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"产物：{target}")
    print(f"文件数：{len(files)}    大小：{size_mb:.2f} MB")

    # 自检：确认关键文件在包里、敏感文件不在
    with zipfile.ZipFile(target) as zf:
        names = zf.namelist()
    must_have = ["ai-kb/README.md", "ai-kb/app/main.py", "ai-kb/requirements.txt",
                 "ai-kb/web/src/views/Chat.vue", "ai-kb/docs/acceptance.md",
                 "ai-kb/data/testset.csv", "ai-kb/start.bat"]
    print("\n自检：")
    for m in must_have:
        print(f"  {'OK  ' if m in names else 'MISS'} {m}")
    bad = [n for n in names if n.endswith("/.env") or "/.venv/" in n
           or "node_modules" in n or n.endswith(".pyc")]
    print(f"  敏感/冗余文件：{len(bad)} 个（应为 0）")
    for n in bad[:5]:
        print(f"    ! {n}")

    # 按目录统计
    from collections import Counter
    top = Counter(n.split("/")[1] for n in names)
    print("\n各目录文件数：")
    for k, v in sorted(top.items(), key=lambda x: -x[1]):
        print(f"  {k:<14} {v}")


if __name__ == "__main__":
    import sys

    FULL = "--full" in sys.argv
    main()
