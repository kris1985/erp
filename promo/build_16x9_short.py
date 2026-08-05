#!/usr/bin/env python3
"""Shorter 16:9 boss promo (~70s), consistent male voice."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets_16x9"
AUDIO = ROOT / "audio"
WORK = ROOT / "work16"
OUT = ROOT / "out"
W, H = 1920, 1080

# Reuse already-built composite frames from previous build
FRAMES = {
    "dashboard": WORK / "F_dashboard.png",
    "orders": WORK / "F_orders.png",
    "scan": WORK / "F_scan_combo.png",
    "salary": WORK / "F_salary.png",
    "mobile": WORK / "F_mobile_grid.png",
}

# Compressed timeline: cut silent fillers + redundant slides
# All audio = edge-tts Yunyang (male)
timeline = [
    (ASSETS / "L01_data.png", AUDIO / "01.mp3"),          # 数据暗示
    (ASSETS / "L04_three_pains.png", AUDIO / "04.mp3"),   # 三大痛点（合并痛点叙事）
    (ASSETS / "L06_product.png", AUDIO / "06.mp3"),       # 产品登场
    (FRAMES["dashboard"], AUDIO / "07.mp3"),              # 看板
    (FRAMES["orders"], AUDIO / "11.mp3"),                 # 订单派工（男声已重录）
    (FRAMES["scan"], AUDIO / "08.mp3"),                   # 扫码报工
    (FRAMES["salary"], AUDIO / "09.mp3"),                 # 算薪
    (ASSETS / "L08_cta.png", AUDIO / "10.mp3"),           # CTA
]


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def make_clip(image: Path, audio: Path, out_mp4: Path) -> None:
    dur = ffprobe_duration(audio) + 0.08
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{dur:.3f}", "-shortest",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    for key, path in FRAMES.items():
        if not path.exists():
            raise SystemExit(f"missing frame {path}, run build_16x9.py first")
    for img, aud in timeline:
        if not img.exists() or not aud.exists():
            raise SystemExit(f"missing {img} or {aud}")

    clips = []
    total = 0.0
    for i, (img, aud) in enumerate(timeline, 1):
        clip = WORK / f"short_{i:02d}.mp4"
        print(f"encode {i}/{len(timeline)} {img.name} + {aud.name} ({ffprobe_duration(aud):.1f}s)")
        make_clip(img, aud, clip)
        clips.append(clip)
        total += ffprobe_duration(clip)

    lst = WORK / "concat_short.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    raw = OUT / "workshop_boss_promo_16x9_short_raw.mp4"
    final = OUT / "workshop_boss_promo_16x9.mp4"

    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(raw)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(
        [
            "ffmpeg", "-y", "-i", str(raw),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(final),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    meta = {
        "output": str(final),
        "width": W,
        "height": H,
        "aspect": "16:9",
        "duration_sec": round(ffprobe_duration(final), 2),
        "clips": len(clips),
        "voice": "zh-CN-YunyangNeural (male) throughout",
        "note": "short cut: removed market/process/boss fillers + silent UI beats; regen 11-13 male -5%",
    }
    (OUT / "meta_16x9.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("DONE", final)


if __name__ == "__main__":
    main()
