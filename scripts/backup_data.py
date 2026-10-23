"""备份数据：向量库 + SQLite + 上传文件，打成一个带时间戳的 zip。

备份内容（都是运行期产生的、重建成本高的东西）：
  data/chroma   向量库（可重建，但要重新入库，几十分钟）
  data/app.db   会话与消息
  data/uploads  用户上传的原始文件

不备份：向量库里的实验集合（已清理）、materials（原始语料，自己有）、.env（含密钥）。

用法：
  .venv\\Scripts\\python.exe scripts/backup_data.py              # 备份到 backups/
  .venv\\Scripts\\python.exe scripts/backup_data.py --keep 3     # 只保留最近 3 份
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def add_tree(zf: zipfile.ZipFile, base: Path, arc_root: str) -> int:
    """把一个目录递归写进 zip，返回文件数。"""
    if not base.exists():
        return 0
    count = 0
    for f in base.rglob("*"):
        if f.is_file():
            zf.write(f, arcname=f"{arc_root}/{f.relative_to(base).as_posix()}")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(ROOT / "backups"))
    parser.add_argument("--keep", type=int, default=5, help="保留最近几份备份")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"ai-kb-backup-{stamp}.zip"

    # 备份前先提醒：运行中的服务会写 db，最好在低峰期跑
    print(f"备份到 {target}")
    total = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        n = add_tree(zf, settings.chroma_dir, "data/chroma")
        print(f"  向量库: {n} 个文件")
        total += n

        if settings.db_path.exists():
            zf.write(settings.db_path, arcname="data/app.db")
            total += 1
            print("  SQLite: 1 个文件")

        n = add_tree(zf, settings.uploads_dir, "data/uploads")
        print(f"  上传文件: {n} 个")
        total += n

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"完成：{total} 个文件，{size_mb:.0f} MB")

    # 只保留最近 N 份
    backups = sorted(out_dir.glob("ai-kb-backup-*.zip"))
    for old in backups[: max(0, len(backups) - args.keep)]:
        old.unlink(missing_ok=True)
        print(f"  清理旧备份 {old.name}")

    print("\n恢复方法：停掉服务，把 zip 解压覆盖回项目根目录（data/ 下），再启动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
