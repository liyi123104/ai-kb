"""把录制的帧合成为演示视频（片头 + 录屏 + 片尾）。

用法：.venv\\Scripts\\python.exe scripts/build_demo_video.py [帧目录] [输出文件]

说明：无头浏览器抓不到 PDF 阅读器，所以视频只展示界面内的问答与出处卡片；
高亮 PDF 的效果在 8 张截图里另有体现（docs/screenshots/）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import imageio.v2 as imageio
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FRAMES_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "demo-frames"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "demo-video.mp4"

W, H = 1440, 900
FPS = 12
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

INTRO_SEC = 3.0
OUTRO_SEC = 4.5

ACCENT = (64, 158, 255)
DARK = (24, 28, 36)
LIGHT = (240, 244, 250)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def center_text(draw, box, text, f, fill):
    x0, y0, x1, y1 = box
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x0 + x1 - tw) / 2, (y0 + y1 - th) / 2 - bbox[1]), text, font=f, fill=fill)


def make_intro() -> Image.Image:
    img = Image.new("RGB", (W, H), DARK)
    d = ImageDraw.Draw(img)
    # 顶部渐变条
    for i in range(8):
        d.rectangle([0, i * 3, W, i * 3 + 3], fill=(*ACCENT, ))
    center_text(d, (0, 250, W, 360), "AI 学习资料知识库", font(86, True), LIGHT)
    center_text(d, (0, 380, W, 440), "本地 RAG 问答系统 · 演示", font(38), (170, 180, 195))
    d.line([(W / 2 - 180, 470), (W / 2 + 180, 470)], fill=ACCENT, width=3)
    for i, line in enumerate([
        "FastAPI + LangChain + ChromaDB + Ollama(qwen2.5:7b / bge-m3) + Vue3",
        "10 份 AI 学习资料 · 10,942 个片段 · 答案均带出处",
    ]):
        center_text(d, (0, 510 + i * 52, W, 560 + i * 52), line, font(26), (140, 150, 165))
    return img


def make_outro() -> Image.Image:
    img = Image.new("RGB", (W, H), DARK)
    d = ImageDraw.Draw(img)
    for i in range(8):
        d.rectangle([0, H - i * 3 - 3, W, H - i * 3], fill=ACCENT)
    center_text(d, (0, 170, W, 260), "实测数据", font(66, True), LIGHT)
    rows = [
        ("检索召回率", "90.0%", "27/30"),
        ("答案准确率", "73.3%", "22/30"),
        ("检索耗时", "0.31 秒", "AI 专用库"),
        ("流式首字", "2.34 秒", "本地模型"),
        ("功能测试", "30 / 30", "全部通过"),
    ]
    y = 300
    for name, value, note in rows:
        d.text((230, y), name, font=font(34), fill=(170, 180, 195))
        d.text((600, y - 6), value, font=font(42, True), fill=ACCENT)
        d.text((860, y + 6), note, font=font(24), fill=(120, 130, 145))
        y += 78
    center_text(d, (0, y + 40, W, y + 100), "30 个功能用例 · 8 组对照实验 · 完整文档", font(26), (140, 150, 165))
    return img


def watermark(frame: Image.Image) -> Image.Image:
    d = ImageDraw.Draw(frame, "RGBA")
    text = "AI 学习资料知识库 · 演示"
    f = font(20)
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 10
    x1, y1 = W - 24, H - 20
    d.rounded_rectangle(
        [x1 - tw - pad * 2, y1 - th - pad * 1.4, x1, y1],
        radius=8, fill=(0, 0, 0, 110),
    )
    d.text((x1 - tw - pad, y1 - th - pad * 0.9), text, font=f, fill=(255, 255, 255, 210))
    return frame


def main() -> int:
    meta = json.loads((FRAMES_DIR / "frames.json").read_text(encoding="utf-8"))
    frames = meta["frames"]
    if not frames:
        print("没有帧")
        return 1
    duration = frames[-1]["t"] / 1000

    # 提前读入所有帧，便于按时间点取样
    loaded = [(f["t"] / 1000, Image.open(FRAMES_DIR / f["name"]).convert("RGB")) for f in frames]
    print(f"帧 {len(loaded)} 张，录屏时长 {duration:.1f}s")

    writer = imageio.get_writer(
        OUT, fps=FPS, codec="libx264", quality=8,
        macro_block_size=None, ffmpeg_log_level="error",
        output_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    )

    def write(img: Image.Image, seconds: float):
        n = max(1, int(seconds * FPS))
        for _ in range(n):
            writer.append_data(__import__("numpy").array(img))

    intro = make_intro()
    write(intro, INTRO_SEC)

    idx = 0
    total_frames = int(duration * FPS)
    for i in range(total_frames):
        t = i / FPS
        while idx + 1 < len(loaded) and loaded[idx + 1][0] <= t:
            idx += 1
        img = loaded[idx][1].copy()
        if img.size != (W, H):
            img = img.resize((W, H))
        write(watermark(img), 1 / FPS)

    write(make_outro(), OUTRO_SEC)
    writer.close()

    for _, im in loaded:
        im.close()
    size_mb = OUT.stat().st_size / 1024 / 1024
    total = INTRO_SEC + duration + OUTRO_SEC
    print(f"完成：{OUT}（{size_mb:.1f} MB，约 {total:.0f} 秒）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
