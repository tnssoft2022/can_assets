#!/usr/bin/env python3
"""
ตัดขอบ / ลบลายน้ำออกจากรูป ก่อนขยายด้วย AI และนำไปทำวิดีโอ/โปสต์

กำหนดใน config.json ที่รูปแต่ละรูป (ตัวเลขเป็นสัดส่วน 0–1 ของความกว้าง/สูงรูปต้นฉบับ):

    { "file": "01.webp",
      "crop":   [x, y, w, h],              ตัดเก็บเฉพาะส่วนนี้ (เช่น ตัดแถบข้อความบน/ล่างทิ้ง)
      "remove": [[x, y, w, h], ...] }      ลบลายน้ำ/โลโก้เล็กๆ ในกรอบนี้ (เติมจากพื้นที่รอบๆ)

- "crop" เหมาะกับแถบ/ข้อความที่อยู่ริมรูป — ได้ภาพคมที่สุด
- "remove" ใช้ฟิลเตอร์ delogo ของ ffmpeg — เหมาะกับลายน้ำขนาดเล็ก ถ้ากรอบใหญ่จะเห็นเป็นรอยเบลอ
- ผลเก็บไว้ใน projects/<โครงการ>/cache/cleaned/ ใช้ซ้ำได้

ใช้ลบเฉพาะลายน้ำ/แบรนด์ของบริษัทเอง — ลายน้ำของบริษัทอื่นบอกความเป็นเจ้าของรูป
ไม่ควรลบออก ให้ใช้รูปอื่นแทนหรือขออนุญาตเจ้าของก่อน
"""
import hashlib
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "cache", "cleaned")  # ค่าสำรองถ้าไม่ได้ระบุ cache_dir


def _size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("\n")[0].split(",")[:2]
    return int(w), int(h)


def _px(box, W, H):
    x, y, w, h = box
    return int(round(x * W)), int(round(y * H)), int(round(w * W)), int(round(h * H))


def needs_cleanup(item):
    return bool(item.get("crop") or item.get("remove"))


def clean(path, item, cache_dir=None):
    """คืนค่า path ของรูปที่ลบลายน้ำ/ตัดขอบแล้ว (หรือรูปเดิมถ้าไม่ได้กำหนด)"""
    if not needs_cleanup(item):
        return path
    cache_dir = cache_dir or CACHE_DIR
    spec = json.dumps({"crop": item.get("crop"), "remove": item.get("remove")}, sort_keys=True)
    with open(path, "rb") as f:  # ชื่อไฟล์ cache จากเนื้อหารูป + ค่าที่ตั้ง (ไม่ขึ้นกับตำแหน่งไฟล์)
        key = hashlib.sha1(f.read() + spec.encode()).hexdigest()[:16]
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, key + ".png")
    if os.path.exists(out):
        return out

    W, H = _size(path)
    filters = []
    # ลบลายน้ำก่อน (พิกัดอ้างอิงรูปต้นฉบับ) แล้วค่อยตัดขอบ
    for box in item.get("remove") or []:
        x, y, w, h = _px(box, W, H)
        # delogo ต้องการกรอบที่อยู่ในรูปทั้งหมด (ห่างขอบอย่างน้อย 1px)
        x, y = max(1, x), max(1, y)
        w, h = min(w, W - x - 1), min(h, H - y - 1)
        if w > 1 and h > 1:
            filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
    if item.get("crop"):
        x, y, w, h = _px(item["crop"], W, H)
        w, h = min(w, W - x), min(h, H - y)
        filters.append(f"crop={w - w % 2}:{h - h % 2}:{x}:{y}")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path,
                    "-vf", ",".join(filters), "-frames:v", "1", out], check=True)
    print(f"  ✂ ลบลายน้ำ/ตัดขอบ: {os.path.basename(path)}")
    return out
