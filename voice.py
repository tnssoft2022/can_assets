#!/usr/bin/env python3
"""
สร้างเสียงพากย์ภาษาไทยจากบทพากย์ (narration) ใน config.json

ตอนนี้ใช้เสียง Kanya ของ macOS (คำสั่ง `say`) — ฟรี ไม่ต้องใช้เน็ต / ไม่มีบน Windows (ระบบจะข้ามเสียงพากย์)

ตั้งค่าใน config.json (ไม่บังคับ):
    "voice": {"name": "Kanya", "rate": 200}      rate = คำต่อนาที (ยิ่งมากยิ่งเร็ว)
    "voiceover": false                            ปิดเสียงพากย์ทั้งวิดีโอ

ทดสอบฟังเสียง:
    python3 voice.py "ทาวน์เฮาส์ 2 ชั้น ให้เช่าเดือนละ ฿15,000"
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VOICE = {"name": "Kanya", "rate": 200}
THAI_DIGITS = "ศูนย์ หนึ่ง สอง สาม สี่ ห้า หก เจ็ด แปด เก้า".split()


def _phone_words(m):
    """064-535-9426 → 'ศูนย์หกสี่ ห้าสามห้า เก้าสี่สองหก' (อ่านทีละตัว แบ่งกลุ่มตามขีด)"""
    return " ".join("".join(THAI_DIGITS[int(d)] for d in g) for g in m.group(0).split("-"))


def available():
    return shutil.which("say") is not None


def speakable(text):
    """แปลงข้อความให้อ่านออกเสียงถูก: คำย่อ, สกุลเงิน, เบอร์โทร, เครื่องหมาย"""
    t = text
    # เบอร์โทร 064-594-1426 → อ่านทีละตัวเป็นคำไทย
    t = re.sub(r"\b0\d{1,2}-\d{3}-\d{3,4}\b", _phone_words, t)
    t = re.sub(r"฿\s*([\d,\.]+)\s*ล้าน", r"\1 ล้านบาท", t)
    t = re.sub(r"฿\s*([\d,\.]+)", r"\1 บาท", t)
    for a, b in [("ตร.ม.", "ตารางเมตร"), ("ตร.ว.", "ตารางวา"), ("ตรม.", "ตารางเมตร"),
                 ("กม.", "กิโลเมตร"), ("/ด.", "ต่อเดือน"), ("/ เดือน", "ต่อเดือน"), ("/เดือน", "ต่อเดือน"),
                 ("ลบ.", "ล้านบาท"), ("•", ","), ("|", ","), ("+", " และ ")]:
        t = t.replace(a, b)
    # "1–3 ห้องนอน" → "1 ถึง 3" / ขีดในชื่อ เช่น "รัตนาธิเบศร์ – งามวงศ์วาน" → เว้นวรรค
    t = re.sub(r"(\d)\s*[–-]\s*(\d)", r"\1 ถึง \2", t)
    t = t.replace("–", " ")
    return re.sub(r"\s+", " ", t).strip()


def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def synth(text, cache_dir, settings=None):
    """สร้างไฟล์เสียง (wav) จากบทพากย์ คืนค่า (path, ความยาววินาที) — เก็บ cache ตามข้อความ+เสียง"""
    v = dict(DEFAULT_VOICE, **(settings or {}))
    spoken = speakable(text)
    key = hashlib.sha1(json.dumps([spoken, v], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, key + ".wav")
    if not os.path.exists(out):
        aiff = out[:-4] + ".aiff"
        subprocess.run(["say", "-v", v["name"], "-r", str(v["rate"]), "-o", aiff, spoken], check=True)
        # ปรับความดังเสียงพูดให้สม่ำเสมอ + ตัดช่วงเงียบหัว/ท้าย
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", aiff, "-af",
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "loudnorm=I=-16:TP=-1.5:LRA=7,aresample=44100",
                        "-ac", "1", out], check=True)
        os.remove(aiff)
    return out, _duration(out)


def main():
    if not available():
        sys.exit("ไม่พบคำสั่ง say (ใช้ได้เฉพาะ macOS)")
    text = " ".join(sys.argv[1:]) or "สวัสดีค่ะ ยินดีต้อนรับสู่ อัพทาวน์ แอสเซ็ทส์"
    print("อ่านว่า:", speakable(text))
    path, dur = synth(text, os.path.join(HERE, "cache", "voice"))
    print(f"{path} ({dur:.1f} วินาที)")
    subprocess.run(["afplay", path])


if __name__ == "__main__":
    main()
