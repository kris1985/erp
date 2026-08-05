#!/usr/bin/env python3
"""Generate vertical (1080x1920) promo slide cards for boss-facing video."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1080, 1920

# Workshop-ish palette: deep forest + warm amber (avoid purple/cream AI clichés)
BG = (18, 32, 28)
BG2 = (28, 52, 44)
ACCENT = (232, 168, 56)
TEXT = (245, 242, 235)
MUTED = (170, 185, 175)
DANGER = (220, 96, 80)
OK = (90, 190, 140)

def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size, index=0)
        except Exception:
            continue
    return ImageFont.load_default()

def gradient_bg():
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(BG[0] * (1 - t) + BG2[0] * t)
        g = int(BG[1] * (1 - t) + BG2[1] * t)
        b = int(BG[2] * (1 - t) + BG2[2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    # soft amber glow top-right
    for i in range(40):
        a = 18 - i // 3
        if a <= 0:
            break
        draw.ellipse([700 - i * 8, -200 - i * 8, 1400 + i * 8, 500 + i * 8], outline=(ACCENT[0], ACCENT[1], ACCENT[2]))
    return img, draw

def center_text(draw, text, y, f, fill=TEXT, max_w=960):
    bbox = draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    x = (W - tw) // 2
    draw.text((x, y), text, font=f, fill=fill)
    return y + (bbox[3] - bbox[1]) + 16

def wrap_center(draw, text, y, f, fill=MUTED, line_gap=12):
    # simple wrap by chars for CJK
    max_chars = 16
    lines = []
    cur = ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    for line in lines:
        y = center_text(draw, line, y, f, fill=fill) + line_gap - 16
    return y

def card_stat(draw, x, y, w, h, big, small, big_color=ACCENT):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=28, fill=(255, 255, 255, ), outline=(60, 80, 70))
    # use darker panel
    draw.rounded_rectangle([x, y, x + w, y + h], radius=28, fill=(35, 55, 48))
    fb, fs = font(72, True), font(34)
    bbox = draw.textbbox((0, 0), big, font=fb)
    tw = bbox[2] - bbox[0]
    draw.text((x + (w - tw) // 2, y + 36), big, font=fb, fill=big_color)
    bbox2 = draw.textbbox((0, 0), small, font=fs)
    tw2 = bbox2[2] - bbox2[0]
    draw.text((x + (w - tw2) // 2, y + 130), small, font=fs, fill=MUTED)

def save(name, img):
    path = OUT / name
    img.save(path, "PNG")
    print("wrote", path)

# --- slides ---
slides = []

# 01 data hint
img, d = gradient_bg()
y = 280
y = center_text(d, "中小鞋厂现状", y, font(42), MUTED)
y = center_text(d, "十家里面，九家", y + 40, font(56), TEXT)
y = center_text(d, "还在用 Excel", y + 10, font(72), ACCENT)
card_stat(d, 90, 780, 420, 220, "≈90%", "仍靠表格跟单")
card_stat(d, 560, 780, 420, 220, "3–7天", "月底算薪耗时", DANGER)
y = center_text(d, "财务通宵 · 工人还在群里吵", 1120, font(36), MUTED)
save("01_data_excel.png", img)

# 02 data hint 2
img, d = gradient_bg()
y = 320
y = center_text(d, "隐性成本，每个月都在涨", y, font(40), MUTED)
y = center_text(d, "计件工厂数字化", y + 50, font(56), TEXT)
y = center_text(d, "一年比一年多", y + 10, font(68), ACCENT)
card_stat(d, 90, 820, 420, 220, "~10%", "年普及增速")
card_stat(d, 560, 820, 420, 220, "几万起", "大型鞋业ERP", DANGER)
y = center_text(d, "通用软件水土不服 · 大系统用不起", 1160, font(34), MUTED)
save("02_data_market.png", img)

# 03 pain processes
img, d = gradient_bg()
y = 260
y = center_text(d, "鞋厂不是一道工序的事", y, font(40), MUTED)
procs = ["裁断", "针车", "贴合", "成型", "包装"]
for i, p in enumerate(procs):
    x0 = 90 + (i % 3) * 300
    y0 = 480 + (i // 3) * 200
    d.rounded_rectangle([x0, y0, x0 + 260, y0 + 140], radius=24, fill=(35, 55, 48))
    center_like = True
    fb = font(48)
    bbox = d.textbbox((0, 0), p, font=fb)
    tw = bbox[2] - bbox[0]
    d.text((x0 + (260 - tw) // 2, y0 + 42), p, font=fb, fill=ACCENT)
y = center_text(d, "多单价 · 多班组 · 多计件规则", 980, font(40), TEXT)
y = center_text(d, "普通 ERP 一落地就歇菜", y + 20, font(36), MUTED)
save("03_pain_process.png", img)

# 04 three pains
img, d = gradient_bg()
y = 240
y = center_text(d, "中小鞋厂三大最高频痛点", y, font(40), MUTED)
pains = [
    ("跟单乱", "进度靠感觉，交期靠催"),
    ("报工假", "虚报产量，月底对不上"),
    ("算薪累", "核单核件，通宵改误差"),
]
for i, (t, s) in enumerate(pains):
    y0 = 420 + i * 320
    d.rounded_rectangle([100, y0, 980, y0 + 260], radius=32, fill=(35, 55, 48))
    d.ellipse([140, y0 + 70, 260, y0 + 190], fill=DANGER if i < 2 else ACCENT)
    d.text((168, y0 + 100), str(i + 1), font=font(56), fill=TEXT)
    d.text((300, y0 + 70), t, font=font(64), fill=TEXT)
    d.text((300, y0 + 160), s, font=font(36), fill=MUTED)
save("04_pain_three.png", img)

# 05 boss blind
img, d = gradient_bg()
y = 300
y = center_text(d, "老板看不见的真相", y, font(42), MUTED)
items = ["真实订单进度", "工序损耗 / 良品率", "这一单到底赚不赚钱"]
for i, t in enumerate(items):
    y0 = 520 + i * 180
    d.rounded_rectangle([120, y0, 960, y0 + 140], radius=24, fill=(35, 55, 48))
    d.text((180, y0 + 42), "？  " + t, font=font(44), fill=TEXT)
y = center_text(d, "很多时候，只能凭感觉接单", 1200, font(36), DANGER)
save("05_pain_boss.png", img)

# 06 product intro
img, d = gradient_bg()
y = 420
y = center_text(d, "铁玉兰管家", y, font(72), ACCENT)
y = center_text(d, "跟单 · 报工 · 计件算薪", y + 40, font(48), TEXT)
y = center_text(d, "不做重型 ERP", y + 80, font(40), MUTED)
y = center_text(d, "只做中小鞋厂每天要用的三件事", y + 10, font(36), MUTED)
save("06_product.png", img)

# 07 solution bullets
img, d = gradient_bg()
y = 280
y = center_text(d, "给老板的三件刚需", y, font(44), MUTED)
sols = [
    ("进度一眼清", "今日产量 · 瓶颈 · 交期风险"),
    ("报工进系统", "扫码报工 · 配额拦截虚报"),
    ("工资自动出", "计件汇总 · 一键导出月结"),
]
for i, (t, s) in enumerate(sols):
    y0 = 460 + i * 300
    d.rounded_rectangle([100, y0, 980, y0 + 240], radius=32, fill=(35, 55, 48))
    d.text((160, y0 + 50), t, font=font(56), fill=OK)
    d.text((160, y0 + 140), s, font=font(34), fill=MUTED)
save("07_solution.png", img)

# 08 CTA
img, d = gradient_bg()
y = 520
y = center_text(d, "还在用表？", y, font(56), TEXT)
y = center_text(d, "还在通宵算薪？", y + 20, font(56), ACCENT)
y = center_text(d, "预约一次老板演示", y + 100, font(48), TEXT)
y = center_text(d, "用你们厂一款样单走一遍", y + 20, font(36), MUTED)
d.rounded_rectangle([220, 1200, 860, 1340], radius=40, fill=ACCENT)
bbox = d.textbbox((0, 0), "铁玉兰管家", font=font(48))
tw = bbox[2] - bbox[0]
d.text(((W - tw) // 2, 1235), "铁玉兰管家", font=font(48), fill=BG)
y = center_text(d, "轻量 · 只做鞋厂现场", 1420, font(34), MUTED)
save("08_cta.png", img)

print("done", len(list(OUT.glob('*.png'))), "slides")
