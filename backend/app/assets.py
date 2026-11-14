"""Generates demo documents (PDF) and damage photos (JPEG with EXIF) for scenarios.
Photos are stylised renders, not real photographs: replace them with real images in
data/assets/<scenario>/ for a live demo; EXIF and hashing work on any JPEG."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# ------------------------------------------------------------------ PDF
def pdf(path: Path, title: str, issuer: str, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFillColor(HexColor("#0F172A"))
    c.rect(0, h - 70, w, 70, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, h - 42, issuer)
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 40, h - 42, "Synthetic document — demonstration only")
    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, h - 105, title)
    c.setStrokeColor(HexColor("#CBD5E1"))
    c.line(40, h - 113, w - 40, h - 113)
    y = h - 138
    for ln in lines:
        if ln.startswith("## "):
            y -= 6
            c.setFont("Helvetica-Bold", 10.5)
            c.drawString(40, y, ln[3:])
        else:
            c.setFont("Helvetica", 10)
            c.drawString(40, y, ln)
        y -= 16
        if y < 60:
            c.showPage()
            y = h - 60
    c.save()
    return path


# ------------------------------------------------------------------ photos
def _to_dms(v: float) -> tuple:
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60, 2)
    return (d, m, s)


def photo(path: Path, *, seed: int, body: str, damage: str, taken_at: str | None, lat: float | None = None,
          lon: float | None = None, flood: bool = False, software: str | None = None, view: str = "side") -> Path:
    """Render a car with damage at `damage` (front|rear|side|windshield|none) and write EXIF."""
    rnd = random.Random(seed)
    W, H = 1280, 860
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    sky_top = (rnd.randint(120, 170), rnd.randint(150, 190), rnd.randint(190, 230))
    for y in range(H):
        t = y / H
        if y < H * 0.55:
            col = tuple(int(sky_top[i] * (1 - t) + 230 * t) for i in range(3))
        else:
            g = rnd.randint(70, 78)
            col = (g + 8, g + 8, g + 10)
        d.line([(0, y), (W, y)], fill=col)
    # buildings
    x = 0
    while x < W:
        bw, bh = rnd.randint(90, 200), rnd.randint(120, 300)
        shade = rnd.randint(150, 200)
        d.rectangle([x, int(H * 0.55) - bh, x + bw, int(H * 0.55)], fill=(shade, shade - 6, shade - 14))
        for wy in range(int(H * 0.55) - bh + 15, int(H * 0.55) - 10, 32):
            for wx in range(x + 12, x + bw - 18, 28):
                d.rectangle([wx, wy, wx + 14, wy + 18], fill=(110, 130, 150))
        x += bw + rnd.randint(4, 20)
    body_rgb = {"white": (232, 234, 238), "red": (176, 32, 38), "blue": (34, 70, 140), "grey": (120, 124, 130),
                "black": (30, 32, 36), "silver": (190, 194, 200)}[body]
    ox, oy = 210, 380
    # car body
    d.rounded_rectangle([ox, oy + 90, ox + 860, oy + 260], radius=50, fill=body_rgb, outline=(20, 20, 20), width=3)
    d.polygon([(ox + 170, oy + 95), (ox + 300, oy - 5), (ox + 600, oy - 5), (ox + 720, oy + 95)], fill=body_rgb,
              outline=(20, 20, 20))
    d.polygon([(ox + 200, oy + 92), (ox + 310, oy + 15), (ox + 440, oy + 15), (ox + 440, oy + 92)], fill=(90, 120, 150))
    d.polygon([(ox + 460, oy + 92), (ox + 460, oy + 15), (ox + 590, oy + 15), (ox + 690, oy + 92)], fill=(90, 120, 150))
    for wx in (ox + 190, ox + 670):
        d.ellipse([wx - 70, oy + 200, wx + 70, oy + 340], fill=(25, 25, 25))
        d.ellipse([wx - 35, oy + 235, wx + 35, oy + 305], fill=(150, 150, 155))
    d.rectangle([ox + 830, oy + 140, ox + 860, oy + 170], fill=(250, 220, 120))  # headlamp (front = right)
    d.rectangle([ox, oy + 140, ox + 25, oy + 170], fill=(200, 30, 30))  # tail lamp (rear = left)
    # damage
    crack = (25, 25, 25)
    if damage in ("front", "rear", "side"):
        cx = {"front": ox + 800, "rear": ox + 60, "side": ox + 430}[damage]
        cy = oy + 175
        d.ellipse([cx - 85, cy - 55, cx + 85, cy + 60], fill=tuple(max(0, c - 55) for c in body_rgb))
        for _ in range(14):
            a = (cx + rnd.randint(-70, 70), cy + rnd.randint(-45, 45))
            b = (a[0] + rnd.randint(-40, 40), a[1] + rnd.randint(-30, 30))
            d.line([a, b], fill=crack, width=3)
        for _ in range(40):
            px, py = cx + rnd.randint(-90, 90), cy + rnd.randint(-60, 60)
            d.point((px, py), fill=(200, 200, 200))
    elif damage == "windshield":
        cx, cy = ox + 360, oy + 50
        for _ in range(22):
            ang = rnd.uniform(0, 6.28)
            import math
            ln = rnd.randint(20, 85)
            d.line([(cx, cy), (cx + int(ln * math.cos(ang)), cy + int(ln * math.sin(ang)))], fill=(240, 240, 240), width=2)
    if flood:
        water = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wd = ImageDraw.Draw(water)
        wd.rectangle([0, oy + 210, W, H], fill=(96, 82, 52, 185))
        for y in range(oy + 215, H, 18):
            wd.line([(0, y), (W, y + rnd.randint(-4, 4))], fill=(140, 125, 90, 120), width=2)
        img = Image.alpha_composite(img.convert("RGBA"), water).convert("RGB")
    # sensor noise so every render hashes differently
    noise = Image.effect_noise((W, H), 18).convert("RGB")
    img = Image.blend(img, noise, 0.06).filter(ImageFilter.GaussianBlur(0.6))
    exif = Image.Exif()
    exif[271] = "Samsung"
    exif[272] = "Galaxy S23"
    if software:
        exif[305] = software
    if taken_at:
        exif[306] = taken_at
        exif.get_ifd(0x8769)[36867] = taken_at
    if lat is not None and lon is not None:
        exif.get_ifd(0x8825).update({1: "N" if lat >= 0 else "S", 2: _to_dms(lat), 3: "E" if lon >= 0 else "W",
                                     4: _to_dms(lon)})
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=88, exif=exif)
    return path


def recompress(src: Path, dst: Path, taken_at: str, lat: float, lon: float) -> Path:
    """Re-save an existing photo (as a fraudster re-using an old image would) with new EXIF."""
    img = Image.open(src).convert("RGB").resize((1200, 806))
    exif = Image.Exif()
    exif[306] = taken_at
    exif.get_ifd(0x8769)[36867] = taken_at
    exif.get_ifd(0x8825).update({1: "N", 2: _to_dms(lat), 3: "E", 4: _to_dms(lon)})
    img.save(dst, "JPEG", quality=80, exif=exif)
    return dst
