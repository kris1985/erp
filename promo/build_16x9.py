#!/usr/bin/env python3
"""Generate 16:9 landscape slides + composite UI frames, assemble promo video."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets_16x9"
SCREENS = ROOT / "screens_hd"
AUDIO = ROOT / "audio"
WORK = ROOT / "work16"
OUT = ROOT / "out"
W, H = 1920, 1080

BG = (16, 28, 24)
BG2 = (26, 46, 38)
PANEL = (32, 52, 44)
ACCENT = (232, 168, 56)
TEXT = (245, 242, 235)
MUTED = (168, 184, 174)
DANGER = (220, 96, 80)
OK = (90, 190, 140)

for p in (ASSETS, WORK, OUT):
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


def gradient():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(BG[0] * (1 - t) + BG2[0] * t)
        g = int(BG[1] * (1 - t) + BG2[1] * t)
        b = int(BG[2] * (1 - t) + BG2[2] * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    d.rectangle([0, 0, 12, H], fill=ACCENT)
    return img, d


def text_w(draw, text, f):
    b = draw.textbbox((0, 0), text, font=f)
    return b[2] - b[0]


def cx(d, text, y, f, fill=TEXT):
    tw = text_w(d, text, f)
    d.text(((W - tw) // 2, y), text, font=f, fill=fill)


def card(d, x, y, w, h):
    d.rounded_rectangle([x, y, x + w, y + h], radius=24, fill=PANEL)


def save(name, img):
    path = ASSETS / name
    img.save(path, "PNG")
    print("slide", path.name)
    return path


# --- Landscape graphic slides ---
img, d = gradient()
cx(d, "中小鞋厂现状", 140, font(36), MUTED)
cx(d, "十家里面，九家还在用 Excel", 220, font(60), TEXT)
card(d, 280, 400, 620, 340)
card(d, 1020, 400, 620, 340)
for x, big, small, color in [
    (280, "≈90%", "仍靠表格跟单记账", ACCENT),
    (1020, "3–7天", "月底算薪常见耗时", DANGER),
]:
    tw = text_w(d, big, font(96))
    d.text((x + (620 - tw) // 2, 460), big, font=font(96), fill=color)
    tw = text_w(d, small, font(34))
    d.text((x + (620 - tw) // 2, 600), small, font=font(34), fill=MUTED)
cx(d, "财务通宵 · 工人还在群里吵", 820, font(34), MUTED)
save("L01_data.png", img)

img, d = gradient()
cx(d, "隐性成本，每个月都在涨", 140, font(36), MUTED)
cx(d, "计件工厂数字化 · 一年比一年多", 220, font(56), TEXT)
card(d, 280, 400, 620, 340)
card(d, 1020, 400, 620, 340)
for x, big, small, color in [
    (280, "~10%", "年普及增速量级", ACCENT),
    (1020, "几万起", "大型鞋业 ERP 门槛", DANGER),
]:
    tw = text_w(d, big, font(96))
    d.text((x + (620 - tw) // 2, 460), big, font=font(96), fill=color)
    tw = text_w(d, small, font(34))
    d.text((x + (620 - tw) // 2, 600), small, font=font(34), fill=MUTED)
cx(d, "通用软件水土不服 · 大系统用不起用不惯", 820, font(34), MUTED)
save("L02_market.png", img)

img, d = gradient()
cx(d, "鞋厂不是一道工序的事", 140, font(36), MUTED)
cx(d, "多单价 · 多班组 · 多计件规则", 220, font(52), TEXT)
procs = ["裁断", "针车", "贴合", "成型", "包装"]
for i, p in enumerate(procs):
    x = 160 + i * 340
    card(d, x, 420, 300, 220)
    tw = text_w(d, p, font(56))
    d.text((x + (300 - tw) // 2, 490), p, font=font(56), fill=ACCENT)
cx(d, "普通 ERP 一落地就歇菜", 780, font(36), MUTED)
save("L03_process.png", img)

img, d = gradient()
cx(d, "中小鞋厂三大最高频痛点", 120, font(36), MUTED)
pains = [
    ("01", "跟单乱", "进度靠感觉，交期靠催"),
    ("02", "报工假", "虚报产量，月底对不上"),
    ("03", "算薪累", "核单核件，通宵改误差"),
]
for i, (n, t, s) in enumerate(pains):
    x = 120 + i * 600
    card(d, x, 280, 540, 520)
    d.ellipse([x + 40, 340, x + 140, 440], fill=DANGER if i < 2 else ACCENT)
    tw = text_w(d, n, font(40))
    d.text((x + 40 + (100 - tw) // 2, 365), n, font=font(40), fill=TEXT)
    d.text((x + 180, 360), t, font=font(56), fill=TEXT)
    d.text((x + 40, 520), s, font=font(32), fill=MUTED)
save("L04_three_pains.png", img)

img, d = gradient()
cx(d, "老板看不见的真相", 140, font(36), MUTED)
items = ["真实订单进度", "工序损耗 / 良品率", "这一单到底赚不赚钱"]
for i, t in enumerate(items):
    y = 300 + i * 160
    card(d, 360, y, 1200, 130)
    d.text((420, y + 38), f"？  {t}", font=font(48), fill=TEXT)
cx(d, "很多时候，只能凭感觉接单", 860, font(36), DANGER)
save("L05_boss.png", img)

img, d = gradient()
cx(d, "铁玉兰管家", 320, font(80), ACCENT)
cx(d, "跟单 · 报工 · 计件算薪", 460, font(52), TEXT)
cx(d, "不做重型 ERP，只做中小鞋厂每天要用的三件事", 600, font(34), MUTED)
save("L06_product.png", img)

img, d = gradient()
cx(d, "给老板的三件刚需", 120, font(36), MUTED)
sols = [
    ("进度一眼清", "今日产量 · 瓶颈 · 交期风险"),
    ("报工进系统", "扫码报工 · 配额拦截虚报"),
    ("工资自动出", "计件汇总 · 一键导出月结"),
]
for i, (t, s) in enumerate(sols):
    x = 120 + i * 600
    card(d, x, 280, 540, 480)
    d.text((x + 48, 360), t, font=font(48), fill=OK)
    d.text((x + 48, 480), s, font=font(30), fill=MUTED)
save("L07_solution.png", img)

img, d = gradient()
cx(d, "还在用表？还在通宵算薪？", 300, font(56), TEXT)
cx(d, "预约一次老板演示 · 用你们厂一款样单走一遍", 420, font(36), MUTED)
d.rounded_rectangle([660, 560, 1260, 700], radius=40, fill=ACCENT)
tw = text_w(d, "铁玉兰管家", font(48))
d.text(((W - tw) // 2, 600), "铁玉兰管家", font=font(48), fill=BG)
cx(d, "轻量 · 只做鞋厂现场刚需", 780, font(32), MUTED)
save("L08_cta.png", img)


def place_screen(canvas, src: Path, box, caption=None):
    x, y, w, h = box
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(
        [x, y, x + w, y + h],
        radius=18,
        fill=(10, 16, 14),
        outline=(55, 75, 65),
        width=2,
    )
    img = Image.open(src).convert("RGB")
    iw, ih = img.size
    scale = min((w - 16) / iw, (h - 16) / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    px = x + (w - nw) // 2
    py = y + (h - nh) // 2
    canvas.paste(img, (px, py))
    if caption:
        bar_h = 54
        d.rectangle([x, y + h - bar_h, x + w, y + h], fill=(12, 20, 16))
        tw = text_w(d, caption, font(28))
        d.text((x + (w - tw) // 2, y + h - 42), caption, font=font(28), fill=ACCENT)


def frame_title(canvas, title, subtitle=None):
    d = ImageDraw.Draw(canvas)
    d.text((48, 28), title, font=font(40), fill=TEXT)
    if subtitle:
        d.text((48, 84), subtitle, font=font(26), fill=MUTED)


def make_ui_frame(name, builder):
    img, _ = gradient()
    builder(img)
    path = WORK / name
    img.save(path, "PNG")
    print("frame", name)
    return path


def full_desktop(src, title, subtitle):
    def b(canvas):
        frame_title(canvas, title, subtitle)
        place_screen(canvas, src, (48, 130, 1824, 900))

    return b


def desk_phone(desk, phone, title, subtitle, cap_d, cap_p):
    def b(canvas):
        frame_title(canvas, title, subtitle)
        place_screen(canvas, desk, (48, 130, 1240, 900), cap_d)
        place_screen(canvas, phone, (1320, 130, 552, 900), cap_p)

    return b


def dual_desk(a, bsrc, title, subtitle, ca, cb):
    def b(canvas):
        frame_title(canvas, title, subtitle)
        place_screen(canvas, a, (48, 130, 900, 900), ca)
        place_screen(canvas, bsrc, (972, 130, 900, 900), cb)

    return b


def quad(srcs_caps, title, subtitle):
    def b(canvas):
        frame_title(canvas, title, subtitle)
        positions = [
            (48, 130, 900, 430),
            (972, 130, 900, 430),
            (48, 590, 900, 440),
            (972, 590, 900, 440),
        ]
        for box, (src, cap) in zip(positions, srcs_caps):
            place_screen(canvas, src, box, cap)

    return b


S = SCREENS
frames = {}
frames["F_dashboard"] = make_ui_frame(
    "F_dashboard.png",
    full_desktop(S / "d02_dashboard.png", "进度看板", "今日合格 · 在制订单 · 交期风险 · 工序瓶颈"),
)
frames["F_orders"] = make_ui_frame(
    "F_orders.png",
    full_desktop(S / "d03_orders.png", "订单管理", "色码明细 · 工序进度 · 派工配额"),
)
frames["F_dispatch"] = make_ui_frame(
    "F_dispatch.png",
    full_desktop(S / "d10_dispatch.png", "配额派工", "每人可报上限 · 未分配池 · 超报拦截"),
)
frames["F_worklogs"] = make_ui_frame(
    "F_worklogs.png",
    full_desktop(S / "d04_worklogs.png", "报工记录", "正报 / 返修 / 补数 · 可纠错作废"),
)
frames["F_pricing_stations"] = make_ui_frame(
    "F_pricing_stations.png",
    dual_desk(
        S / "d06_pricing.png",
        S / "d07_stations.png",
        "计价 + 工位二维码",
        "款式工序单价 · 工位扫码报工",
        "计价设置",
        "工位二维码",
    ),
)
frames["F_scan_combo"] = make_ui_frame(
    "F_scan_combo.png",
    desk_phone(
        S / "d03_orders.png",
        S / "m02_scan_filled.png",
        "现场扫码报工",
        "工位一扫 · 色码自动带出 · 提交即进系统",
        "在制订单",
        "扫码报工",
    ),
)
frames["F_mobile_grid"] = make_ui_frame(
    "F_mobile_grid.png",
    quad(
        [
            (S / "m03_home.png", "工作台"),
            (S / "m02_scan_filled.png", "扫码报工"),
            (S / "m04_salary.png", "我的工资"),
            (S / "m05_worklogs.png", "我的报工"),
        ],
        "工人手机端",
        "报工 · 查产量 · 查工资，老人也能上手",
    ),
)
frames["F_salary"] = make_ui_frame(
    "F_salary.png",
    desk_phone(
        S / "d11_salary_detail.png",
        S / "m04_salary.png",
        "计件算薪闭环",
        "财务导出月结 · 工人手机自查明细",
        "工资明细",
        "我的工资",
    ),
)
frames["F_masters"] = make_ui_frame(
    "F_masters.png",
    dual_desk(
        S / "d08_processes.png",
        S / "d09_workers.png",
        "工序与员工",
        "鞋厂工序库 · 计薪模式可配",
        "工序管理",
        "员工管理",
    ),
)
frames["F_chat"] = make_ui_frame(
    "F_chat.png",
    desk_phone(
        S / "d05_salary.png",
        S / "m06_chat.png",
        "一句话也能报工",
        "手机对话报工 · 与工资同源数据",
        "工资管理",
        "报工对话",
    ),
)


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


def make_clip(image: Path, audio: Path | None, out_mp4: Path, duration: float | None = None):
    if audio and duration is None:
        duration = ffprobe_duration(audio) + 0.12
    if duration is None:
        duration = 3.0
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(image)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += [
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30",
        "-t",
        f"{duration:.3f}",
    ]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(out_mp4)]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


timeline = [
    (ASSETS / "L01_data.png", AUDIO / "01.mp3"),
    (ASSETS / "L02_market.png", AUDIO / "02.mp3"),
    (ASSETS / "L03_process.png", AUDIO / "03.mp3"),
    (ASSETS / "L04_three_pains.png", AUDIO / "04.mp3"),
    (ASSETS / "L05_boss.png", AUDIO / "05.mp3"),
    (ASSETS / "L06_product.png", AUDIO / "06.mp3"),
    (ASSETS / "L07_solution.png", None),
    (frames["F_dashboard"], AUDIO / "07.mp3"),
    (frames["F_orders"], AUDIO / "11.mp3"),
    (frames["F_dispatch"], None),
    (frames["F_worklogs"], None),
    (frames["F_pricing_stations"], AUDIO / "12.mp3"),
    (frames["F_scan_combo"], AUDIO / "08.mp3"),
    (frames["F_mobile_grid"], AUDIO / "13.mp3"),
    (frames["F_chat"], None),
    (frames["F_salary"], AUDIO / "09.mp3"),
    (frames["F_masters"], None),
    (ASSETS / "L08_cta.png", AUDIO / "10.mp3"),
]

SILENT_DUR = {
    str(ASSETS / "L07_solution.png"): 2.4,
    str(frames["F_dispatch"]): 2.8,
    str(frames["F_worklogs"]): 2.6,
    str(frames["F_chat"]): 2.4,
    str(frames["F_masters"]): 2.5,
}

clips = []
for i, (img_path, aud) in enumerate(timeline, 1):
    clip = WORK / f"c{i:02d}.mp4"
    dur = None if aud else SILENT_DUR.get(str(img_path), 2.5)
    print(f"encode {i}/{len(timeline)} {img_path.name}")
    make_clip(img_path, aud, clip, duration=dur)
    clips.append(clip)

lst = WORK / "concat.txt"
lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
final_raw = OUT / "workshop_boss_promo_16x9_raw.mp4"
subprocess.check_call(
    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(final_raw)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

final = OUT / "workshop_boss_promo_16x9.mp4"
subprocess.check_call(
    [
        "ffmpeg",
        "-y",
        "-i",
        str(final_raw),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(final),
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

meta = {
    "output": str(final),
    "width": W,
    "height": H,
    "aspect": "16:9",
    "duration_sec": round(ffprobe_duration(final), 2),
    "clips": len(clips),
    "screens_hd": len(list(SCREENS.glob("*.png"))),
    "slides": len(list(ASSETS.glob("*.png"))),
}
(OUT / "meta_16x9.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False, indent=2))
print("DONE", final)
