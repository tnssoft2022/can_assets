#!/usr/bin/env python3
"""
ขยายรูปด้วย AI (Real-ESRGAN x4plus) ให้คมขึ้นก่อนนำไปทำวิดีโอ/โปสต์

- ขยายเฉพาะรูปที่ด้านยาวเล็กกว่า MIN_LONG_SIDE (รูปใหญ่พออยู่แล้วจะใช้ต้นฉบับ)
- เก็บผลไว้ใน projects/<โครงการ>/cache/upscaled/ ใช้ซ้ำได้ ไม่ต้องขยายใหม่
  (ชื่อไฟล์คำนวณจากเนื้อหารูป → ย้าย/เปลี่ยนชื่อโฟลเดอร์ได้, ถ้ารูปต้นฉบับเปลี่ยนจะขยายใหม่เอง)
- ถ้าไม่มีโปรแกรมใน tools/realesrgan/ จะข้ามขั้นตอนนี้และใช้รูปต้นฉบับ

ใช้เดี่ยว ๆ ได้:
    python3 upscale.py รูป1.jpg รูป2.jpg ...
"""
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.join(HERE, "tools", "realesrgan")
# Windows ใช้ไฟล์ .exe จาก realesrgan-ncnn-vulkan-<วันที่>-windows.zip / Mac ใช้รุ่น macos
BIN = os.path.join(TOOL_DIR, "realesrgan-ncnn-vulkan" + (".exe" if os.name == "nt" else ""))
MODEL = "realesrgan-x4plus"
CACHE_DIR = os.path.join(HERE, "cache", "upscaled")  # ใช้เฉพาะตอนรัน upscale.py เดี่ยว ๆ
MIN_LONG_SIDE = 1920  # ด้านยาวของวิดีโอ 1080p


def available():
    exe_ok = os.path.isfile(BIN) and (os.name == "nt" or os.access(BIN, os.X_OK))
    return exe_ok and os.path.exists(os.path.join(TOOL_DIR, "models", MODEL + ".bin"))


def status():
    """ข้อความบอกสถานะ ใช้แจ้งเตือนเมื่อขยายรูปไม่ได้"""
    if available():
        return "พร้อมใช้งาน"
    if not os.path.isfile(BIN):
        return f"ไม่พบโปรแกรม {os.path.basename(BIN)} ใน {TOOL_DIR}"
    return f"ไม่พบโมเดล {MODEL} ใน {os.path.join(TOOL_DIR, 'models')}"


def _key(path):
    """ชื่อไฟล์ cache จากเนื้อหารูป (ไม่ขึ้นกับตำแหน่งไฟล์)"""
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:16]


def _size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("\n")[0].split(",")[:2]
    return int(w), int(h)


def upscale(path, quiet=False, cache_dir=None):
    """คืนค่า path ของรูปที่ขยายแล้ว (หรือรูปเดิมถ้าไม่ต้อง/ทำไม่ได้)"""
    cache_dir = cache_dir or CACHE_DIR
    if not available():
        return path
    try:
        if max(_size(path)) >= MIN_LONG_SIDE:
            return path
    except (subprocess.CalledProcessError, ValueError):
        return path

    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, _key(path) + ".jpg")
    if os.path.exists(out):
        return out

    tmp_png = out[:-4] + ".tmp.png"
    # Real-ESRGAN อ่าน webp/png/jpg ได้ แต่ชื่อไฟล์ภาษาไทยบางกรณีมีปัญหา → แปลงเป็น png ชั่วคราวก่อน
    src_png = out[:-4] + ".src.png"
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path, src_png], check=True)
        r = subprocess.run([BIN, "-i", src_png, "-o", tmp_png, "-n", MODEL,
                            "-m", os.path.join(TOOL_DIR, "models")],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(tmp_png):
            if not quiet:
                print(f"  ! ขยายรูปไม่สำเร็จ ใช้รูปเดิม: {os.path.basename(path)}")
            return path
        # เก็บเป็น JPG คุณภาพสูง (PNG ขนาด x4 ใหญ่เกินไป)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", tmp_png,
                        "-q:v", "2", out], check=True)
    finally:
        for p in (tmp_png, src_png):
            if os.path.exists(p):
                os.remove(p)
    if not quiet:
        print(f"  ✦ ขยายรูปด้วย AI: {os.path.basename(path)}")
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if not available():
        sys.exit(status())
    for p in sys.argv[1:]:
        print(upscale(p))


if __name__ == "__main__":
    main()
