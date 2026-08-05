#!/usr/bin/env python3
"""Assemble boss-facing vertical promo video (1080x1920)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
SCREENS = ROOT / "screens"
AUDIO = ROOT / "audio"
WORK = ROOT / "work"
OUT = ROOT / "out"
W, H = 1080, 1920
BG = (18, 32, 28)
ACCENT = (232, 168, 56)
TEXT = (245, 242, 235)
MUTED = (170, 185, 175)

for p in (WORK, OUT):
    p.mkdir(parents=True, exist_ok=True)


def font(size: int):
    for path in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ):
        try:
            return ImageFont.truetype(path, size, index=0)
        except Exception:
            pass
    return ImageFont.load_default()


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def fit_on_canvas(src: Path, dst: Path, caption: str | None = None, mode: str = "contain") -> None:
    img = Image.open(src).convert("RGB")
    canvas = Image.new("RGB", (W, H), BG)
    iw, ih = img.size
    if mode == "cover_top":
        # desktop screenshots: scale to width, pin near top
        scale = W / iw
        nw, nh = W, int(ih * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        y = 180
        canvas.paste(img, (0, y))
        # fade bottom if overflow
        if y + nh > H - 220:
            pass
    elif mode == "phone":
        # mobile screenshot centered with frame-like margins
        max_w, max_h = 980, 1500
        scale = min(max_w / iw, max_h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        x, y = (W - nw) // 2, 220
        # subtle phone bezel
        draw = ImageDraw.Draw(canvas)
        pad = 18
        draw.rounded_rectangle(
            [x - pad, y - pad, x + nw + pad, y + nh + pad],
            radius=40,
            fill=(30, 48, 40),
            outline=(60, 85, 70),
            width=3,
        )
        canvas.paste(img, (x, y))
    else:
        scale = min(W / iw, H / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas.paste(img, ((W - nw) // 2, (H - nh) // 2))

    if caption:
        draw = ImageDraw.Draw(canvas)
        # bottom caption bar
        draw.rectangle([0, H - 220, W, H], fill=(12, 22, 18))
        f = font(40)
        # wrap caption
        lines = []
        cur = ""
        for ch in caption:
            cur += ch
            if len(cur) >= 14:
                lines.append(cur)
                cur = ""
        if cur:
            lines.append(cur)
        ty = H - 190
        for line in lines[:3]:
            bbox = draw.textbbox((0, 0), line, font=f)
            tw = bbox[2] - bbox[0]
            draw.text(((W - tw) // 2, ty), line, font=f, fill=ACCENT)
            ty += 52

    canvas.save(dst, "PNG")


def make_segment(image: Path, audio: Path, out_mp4: Path, duration: float | None = None) -> None:
    dur = duration if duration is not None else ffprobe_duration(audio)
    # slight pad so audio doesn't clip
    dur = max(dur + 0.15, 1.0)
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-i",
        str(audio),
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-t",
        f"{dur:.3f}",
        "-vf",
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def concat(parts: list[Path], out: Path) -> None:
    lst = WORK / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            str(out),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# Prepare frames
frames: list[tuple[Path, Path]] = []

# 1-5: graphic slides
mapping = [
    (ASSETS / "01_data_excel.png", AUDIO / "01.mp3", None, "contain"),
    (ASSETS / "02_data_market.png", AUDIO / "02.mp3", None, "contain"),
    (ASSETS / "03_pain_process.png", AUDIO / "03.mp3", None, "contain"),
    (ASSETS / "04_pain_three.png", AUDIO / "04.mp3", None, "contain"),
    (ASSETS / "05_pain_boss.png", AUDIO / "05.mp3", None, "contain"),
    (ASSETS / "06_product.png", AUDIO / "06.mp3", None, "contain"),
]

# Prepare UI frames with captions
ui_prep = [
    (SCREENS / "02_dashboard.png", AUDIO / "07.mp3", "进度看板：产量 · 瓶颈 · 交期风险", "cover_top"),
    (SCREENS / "05_scan_filled.png", AUDIO / "08.mp3", "工位扫码报工：正报 / 返修 / 补数", "phone"),
    (SCREENS / "04_salary.png", AUDIO / "09.mp3", "工资自动汇总 · 一键导出月结", "cover_top"),
    (ASSETS / "08_cta.png", AUDIO / "10.mp3", None, "contain"),
]

prepared: list[tuple[Path, Path]] = []

idx = 0
for src, audio, caption, mode in mapping + ui_prep:
    idx += 1
    frame = WORK / f"frame_{idx:02d}.png"
    if mode == "contain" and caption is None and src.parent == ASSETS:
        # already 1080x1920
        Image.open(src).convert("RGB").resize((W, H)).save(frame)
    else:
        fit_on_canvas(src, frame, caption=caption, mode=mode)
    prepared.append((frame, audio))

# Build clips
clips: list[Path] = []
for i, (frame, audio) in enumerate(prepared, 1):
    clip = WORK / f"clip_{i:02d}.mp4"
    print(f"encoding clip {i}/{len(prepared)} ...")
    make_segment(frame, audio, clip)
    clips.append(clip)

final = OUT / "workshop_boss_promo_vertical.mp4"
print("concat...")
concat(clips, final)

# Also make a landscape-ish master by side-by-side? skip — vertical is enough
# Write a short README
meta = {
    "output": str(final),
    "duration_sec": round(sum(ffprobe_duration(c) for c in clips), 2),
    "clips": len(clips),
    "resolution": f"{W}x{H}",
}
(OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False, indent=2))
print("DONE", final)
