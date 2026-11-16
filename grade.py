#!/usr/bin/env python3
"""
แต่งโทนสีรูปทั้งชุดให้เข้ากัน (ใช้ ffmpeg อย่างเดียว ไม่ต้องติดตั้งอะไรเพิ่ม) — make_video.py / make_poster.py เรียกใช้เอง

2 ชั้น:
  1. ปรับให้เข้าชุด (match) — ดึงความสว่าง คอนทราสต์ และสมดุลแสงขาวของแต่ละรูป เข้าหาค่ากลางของทั้งชุด
     แบบครึ่งทาง (ไม่บังคับให้เหมือนกันเป๊ะ) และจำกัดการปรับสีแต่ละช่องไม่เกิน ±6%
     สมดุลแสงขาวคิดจากส่วนที่ไม่ใช่ท้องฟ้า (ฟ้าสีฟ้าจะไม่ถูกดึงให้อุ่นตามรูปในห้อง)
     → สีผนัง/พื้น/วัสดุ ยังเป็นสีจริง (บ้านสีชมพูยังเป็นสีชมพู)
  2. โทนประจำสไตล์ (look) — แต่งอ่อน ๆ เช่น ธรรมชาติ = อุ่น ออกเขียว, หรูกลางคืน = เย็น ออกฟ้า

ปิดได้ใน config.json:  "grade": false (ทั้งหมด)  /  "grade": "match" (เฉพาะปรับให้เข้าชุด)
                       ต่อรูป: images[].grade = false
ผลเก็บใน projects/<โครงการ>/cache/graded/ (ใช้ซ้ำ)
"""
import hashlib
import math
import os
import subprocess

GRADE_VERSION = 2
STRENGTH = 0.6        # ปรับเข้าหาค่ากลางของชุดกี่ส่วน (1 = เท่ากันหมด)
MAX_GAIN = 0.06       # ปรับสีแต่ละช่องได้ไม่เกิน ±6%
MID_RANGE = (0.40, 0.56)  # ความสว่างกลางของชุดที่ยอมรับ (ชุดที่มืด/สว่างเกินจะถูกดึงเข้าช่วงนี้)

# โทนประจำสไตล์ (ฟิลเตอร์ ffmpeg) — ตั้งใจให้อ่อน ไม่เปลี่ยนสีของจริง
LOOKS = {
    "modern": "eq=contrast=1.05:saturation=1.08",
    "luxury": "colorbalance=rs=0.03:bs=-0.03:rm=0.02:bm=-0.02,eq=contrast=1.08:saturation=0.95",
    "minimal": "eq=brightness=0.02:contrast=0.96:saturation=0.86",
    "bold": "eq=contrast=1.08:saturation=1.15",
    "nature": "colorbalance=rm=0.03:gm=0.02:bm=-0.03,eq=saturation=1.04",
    "corporate": "colorbalance=bs=0.02:bm=0.01,eq=contrast=1.04:saturation=0.95",
    "night": "colorbalance=rs=-0.02:bs=0.05:bm=0.03,eq=contrast=1.06:saturation=0.9",
}


def _stats(path):
    """ค่าเฉลี่ย R G B และเปอร์เซ็นไทล์ความสว่าง 5/50/95 (0..1) จากรูปย่อ 64x64"""
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
                          "-vf", "scale=64:64:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    px = [raw[i:i + 3] for i in range(0, len(raw) - 2, 3)]
    luma = sorted((0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]) / 255 for p in px)
    # สีเฉลี่ยไม่นับท้องฟ้า (ฟ้าคราม/ฟ้าสว่าง) — ไม่งั้นรูปภายนอกจะถูกปรับให้อุ่นเกิน
    body = [p for p in px if not (p[2] > p[0] + 25 and p[2] >= p[1])] or px
    n = len(body)
    r = sum(p[0] for p in body) / n / 255
    g = sum(p[1] for p in body) / n / 255
    b = sum(p[2] for p in body) / n / 255
    pick = lambda q: luma[min(len(luma) - 1, int(q * len(luma)))]
    return {"r": r, "g": g, "b": b, "y": 0.2126 * r + 0.7152 * g + 0.0722 * b,
            "p5": pick(0.05), "p50": pick(0.5), "p95": pick(0.95)}


def _median(xs):
    xs = sorted(xs)
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def match_filter(st, target):
    """ฟิลเตอร์ที่ดึงรูปหนึ่งเข้าหาค่ากลางของชุด"""
    k = STRENGTH
    parts = []
    # สมดุลแสงขาว: สัดส่วนสีต่อความสว่าง เข้าหาค่ากลางของชุด (คงโทนรวมของชุดไว้ ไม่บังคับเป็นสีเทา)
    gains = []
    for ch in ("r", "g", "b"):
        want = target[ch + "_ratio"] * st["y"]
        gain = (want / max(st[ch], 1e-3)) ** k
        gains.append(_clamp(gain, 1 - MAX_GAIN, 1 + MAX_GAIN))
    if any(abs(g - 1) > 0.005 for g in gains):
        parts.append(f"colorchannelmixer=rr={gains[0]:.4f}:gg={gains[1]:.4f}:bb={gains[2]:.4f}")
    # คอนทราสต์: ช่วงเงา-ไฮไลต์ (p5..p95) เข้าหาช่วงของชุด
    lo = st["p5"] + (target["p5"] - st["p5"]) * k
    hi = st["p95"] + (target["p95"] - st["p95"]) * k
    span = max(st["p95"] - st["p5"], 0.05)
    a = _clamp((hi - lo) / span, 0.85, 1.25)
    b = lo - a * st["p5"]
    if abs(a - 1) > 0.01 or abs(b) > 0.01:
        imin = _clamp(-b / a, 0, 0.3) if b < 0 else 0.0
        imax = _clamp((1 - b) / a, 0.7, 1) if a + b > 1 else 1.0
        omin, omax = _clamp(a * imin + b, 0, 0.3), _clamp(a * imax + b, 0.7, 1)
        parts.append("colorlevels=" + ":".join(
            f"{c}imin={imin:.4f}:{c}imax={imax:.4f}:{c}omin={omin:.4f}:{c}omax={omax:.4f}" for c in "rgb"))
    # ความสว่างกลางภาพ: gamma ดึง p50 เข้าหาค่ากลางของชุด
    mid = _clamp(a * st["p50"] + b, 0.02, 0.98)
    tm = mid + (target["p50"] - mid) * k
    if abs(tm - mid) > 0.01:
        gamma = _clamp(math.log(mid) / math.log(tm), 0.8, 1.3)
        parts.append(f"eq=gamma={gamma:.4f}")
    return ",".join(parts)


def grade_images(images, style, mode, cache_dir):
    """images: รายการ dict ที่มี "path" (และอาจมี "with_path", "grade": False)
    แทนที่ path ด้วยรูปที่แต่งแล้ว — mode: True/"all" = ปรับเข้าชุด + โทนสไตล์, "match" = เฉพาะปรับเข้าชุด"""
    if mode is False or not images:
        return
    targets = [(img, key) for img in images if img.get("grade", True)
               for key in ("path", "with_path") if img.get(key)]
    if not targets:
        return
    stats = {img[key]: _stats(img[key]) for img, key in targets}
    vals = list(stats.values())
    target = {
        "p5": _median([s["p5"] for s in vals]),
        "p50": _clamp(_median([s["p50"] for s in vals]), *MID_RANGE),
        "p95": _median([s["p95"] for s in vals]),
    }
    for ch in ("r", "g", "b"):
        target[ch + "_ratio"] = _median([s[ch] / max(s["y"], 1e-3) for s in vals])
    look = LOOKS.get(style, "") if mode in (True, "all") else ""
    os.makedirs(cache_dir, exist_ok=True)
    for img, key in targets:
        src = img[key]
        # รูปเดียวไม่มีชุดให้เทียบ: ใช้เฉพาะโทนสไตล์
        filt = ",".join(f for f in (match_filter(stats[src], target) if len(stats) > 1 else "", look) if f)
        if not filt:
            continue
        st = os.stat(src)
        h = hashlib.sha1(f"{os.path.abspath(src)}|{st.st_size}|{int(st.st_mtime)}|{filt}|{GRADE_VERSION}"
                         .encode()).hexdigest()[:16]
        out = os.path.join(cache_dir, f"{h}.jpg")
        if not os.path.exists(out):
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                            "-vf", f"format=rgb24,{filt}", "-q:v", "2", out], check=True)
        img[key] = out
