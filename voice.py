#!/usr/bin/env python3
"""
สร้างเสียงพากย์ภาษาไทยจากบทพากย์ (narration) ใน config.json

ลำดับที่ใช้ (ตัวแรกที่ใช้ได้):
1. Botnoi Voice (เสียงไทยธรรมชาติ, เสียค่าแต้ม) — ต้องมี token: ใส่ "botnoi_token" ใน settings.json
   หรือตัวแปรแวดล้อม BOTNOI_TOKEN (รับ token ที่ https://voice.botnoi.ai/developer/api)
   ค่าเริ่มต้น: Premium V2 ผู้พูด "8" (Ava V2) — ดูรายชื่อผู้พูด: python3 voice.py --speakers
2. edge-tts (เสียง Neural ของ Microsoft, ฟรี) — ติดตั้ง: python3 -m pip install edge-tts
   เสียงไทย: th-TH-PremwadeeNeural (หญิง), th-TH-AcharaNeural (หญิง), th-TH-NiwatNeural (ชาย)
3. เสียง Kanya ของ macOS (คำสั่ง `say`) — ฟรี ไม่ใช้เน็ต
ถ้าตัวที่เลือกใช้ไม่ได้ (ไม่มีเน็ต / แต้มหมด) จะใช้ตัวถัดไปแทนและแจ้งเตือน

ตั้งค่าใน config.json (ไม่บังคับ):
    "voice": {"speaker": "13", "speed": 1.1}                 Botnoi: ผู้พูด / ความเร็ว 0.5–2.0
    "voice": {"engine": "edge", "name": "th-TH-NiwatNeural", "rate": "+10%"}
    "voice": {"engine": "say", "name": "Kanya", "rate": 200}  rate = คำต่อนาที
    "voiceover": false                                        ปิดเสียงพากย์ทั้งวิดีโอ

ทดสอบฟังเสียง:
    python3 voice.py "ทาวน์เฮาส์ 2 ชั้น ให้เช่าเดือนละ ฿15,000"
    python3 voice.py --speaker 13 "..."                   ลองผู้พูด Botnoi คนอื่น
    python3 voice.py --engine edge --voice th-TH-NiwatNeural "..."
    python3 voice.py --engine say "..."                   ฟังเสียง macOS แบบเดิม
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BOTNOI_API = "https://api-voice.botnoi.ai/openapi/v1"
DEFAULT_VOICES = {
    "botnoi": {"version": "v2", "speaker": "8", "speed": 1, "volume": 1},
    "edge": {"name": "th-TH-PremwadeeNeural", "rate": "+0%"},
    "say": {"name": "Kanya", "rate": 200},
}
THAI_DIGITS = "ศูนย์ หนึ่ง สอง สาม สี่ ห้า หก เจ็ด แปด เก้า".split()


def _phone_words(m):
    """064-535-9426 → 'ศูนย์หกสี่ ห้าสามห้า เก้าสี่สองหก' (อ่านทีละตัว แบ่งกลุ่มตามขีด)"""
    return " ".join("".join(THAI_DIGITS[int(d)] for d in g) for g in m.group(0).split("-"))


def _has_edge():
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def _has_say():
    return shutil.which("say") is not None


def botnoi_token():
    tok = os.environ.get("BOTNOI_TOKEN")
    if not tok:
        try:
            with open(os.path.join(HERE, "settings.json"), encoding="utf-8") as f:
                tok = json.load(f).get("botnoi_token")
        except (OSError, ValueError):
            pass
    return (tok or "").strip()


def available():
    return bool(botnoi_token()) or _has_edge() or _has_say()


def _settings(settings, engine):
    """รวมค่าเริ่มต้นของ engine กับค่าใน config — ค่าที่เป็นของ engine อื่น (เช่น rate 200 ของ say) ถูกข้าม"""
    v = dict(DEFAULT_VOICES[engine])
    for k, val in (settings or {}).items():
        if k == "engine":
            continue
        if engine == "botnoi":
            if k == "speaker":
                v[k] = str(val)
            elif k in ("speed", "volume") and isinstance(val, (int, float)):
                v[k] = val
            elif k == "version" and val in ("v1", "v2"):
                v[k] = val
            continue
        if k in ("speaker", "speed", "volume", "version"):
            continue
        if engine == "edge" and k == "name" and not str(val).endswith("Neural"):
            continue
        if engine == "edge" and k == "rate" and not (isinstance(val, str) and val.endswith("%")):
            continue
        if engine == "say" and k == "name" and str(val).endswith("Neural"):
            continue
        if engine == "say" and k == "rate" and not isinstance(val, (int, float)):
            continue
        v[k] = val
    v["engine"] = engine
    return v


def _engines(settings):
    want = (settings or {}).get("engine")
    order = ["botnoi", "edge", "say"]
    if want in order:  # engine ที่เลือกก่อน แล้วตามด้วยตัวสำรอง
        order.remove(want)
        order.insert(0, want)
    ok = {"botnoi": bool(botnoi_token()), "edge": _has_edge(), "say": _has_say()}
    return [e for e in order if ok[e]]


last_points = None  # แต้ม Botnoi ที่เหลือหลังเรียกครั้งล่าสุด


def _botnoi_request(method, path, body=None, timeout=90):
    req = urllib.request.Request(BOTNOI_API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"botnoi-token": botnoi_token(), "Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < 4:  # ยุ่ง/เกินโควตาต่อนาที → รอแล้วลองใหม่
                time.sleep(min(float(e.headers.get("Retry-After") or 5 * (attempt + 1)), 60))
                continue
            msg = {401: "token ไม่ถูกต้อง", 403: "แต้มไม่พอ", 404: "แต้มไม่พอ หรือไม่พบผู้พูด",
                   422: "ข้อมูลไม่ถูกต้อง หรือข้อความยาวเกิน 500 ตัวอักษร"}.get(e.code, "")
            raise RuntimeError(f"Botnoi HTTP {e.code} {msg}".strip()) from None


def _botnoi(v, spoken, raw):
    global last_points
    res = _botnoi_request("POST", "/generate_audio_v2" if v["version"] == "v2" else "/generate_audio", {
        "text": spoken, "speaker": v["speaker"], "volume": v["volume"], "speed": v["speed"],
        "type_media": "mp3", "save_file": "True", "language": "th"})
    if not res.get("audio_url"):
        raise RuntimeError(f"Botnoi ไม่ได้ส่งไฟล์เสียงกลับมา: {res}")
    last_points = res.get("point")
    with urllib.request.urlopen(res["audio_url"], timeout=90) as r, open(raw, "wb") as f:
        f.write(r.read())


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


def _raw(engine, v, spoken, base):
    """สร้างไฟล์เสียงดิบจาก engine ที่เลือก คืนค่า path"""
    if engine == "botnoi":
        raw = base + ".mp3"
        _botnoi(v, spoken, raw)
    elif engine == "edge":
        import asyncio
        import edge_tts
        raw = base + ".mp3"
        asyncio.run(edge_tts.Communicate(spoken, v["name"], rate=v["rate"]).save(raw))
        if not os.path.getsize(raw):
            raise RuntimeError("edge-tts ไม่ได้ส่งเสียงกลับมา")
    else:
        raw = base + ".aiff"
        subprocess.run(["say", "-v", v["name"], "-r", str(v["rate"]), "-o", raw, spoken], check=True)
    return raw


_warned = set()


def synth(text, cache_dir, settings=None):
    """สร้างไฟล์เสียง (wav) จากบทพากย์ คืนค่า (path, ความยาววินาที) — เก็บ cache ตามข้อความ+เสียง
    ใช้ Botnoi → edge-tts → say ของ macOS ตามลำดับ (ตัวไหนใช้ไม่ได้ข้ามไปตัวถัดไป)"""
    spoken = speakable(text)
    os.makedirs(cache_dir, exist_ok=True)
    engines = _engines(settings)
    if not engines:
        raise RuntimeError("ไม่พบเครื่องมือสร้างเสียง (ใส่ botnoi_token ใน settings.json / ติดตั้ง edge-tts / ใช้ macOS)")
    err = None
    for engine in engines:
        v = _settings(settings, engine)
        key = hashlib.sha1(json.dumps([spoken, v], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        out = os.path.join(cache_dir, key + ".wav")
        if os.path.exists(out):
            return out, _duration(out)
        try:
            raw = _raw(engine, v, spoken, out[:-4])
        except Exception as e:  # เน็ตหลุด / เสียงไม่มี → ลอง engine ถัดไป
            err = e
            if engine not in _warned:
                _warned.add(engine)
                print(f"  ! สร้างเสียงด้วย {engine} ไม่ได้ ({e}) — ลองวิธีถัดไป")
            continue
        # ปรับความดังเสียงพูดให้สม่ำเสมอ + ตัดช่วงเงียบหัว/ท้าย
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", raw, "-af",
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "loudnorm=I=-16:TP=-1.5:LRA=7,aresample=44100",
                        "-ac", "1", out], check=True)
        os.remove(raw)
        return out, _duration(out)
    raise RuntimeError(f"สร้างเสียงพากย์ไม่ได้: {err}")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="ทดลองฟังเสียงพากย์")
    ap.add_argument("text", nargs="*")
    ap.add_argument("--engine", choices=["botnoi", "edge", "say"])
    ap.add_argument("--speaker", help="ผู้พูด Botnoi เช่น 8, 13")
    ap.add_argument("--speakers", action="store_true", help="แสดงรายชื่อผู้พูดภาษาไทยของ Botnoi V2")
    ap.add_argument("--voice", help="ชื่อเสียง เช่น th-TH-NiwatNeural / Kanya")
    ap.add_argument("--rate", help='ความเร็ว เช่น "+10%%" (edge) / 200 (say)')
    a = ap.parse_args()
    if a.speakers:
        if not botnoi_token():
            sys.exit("ยังไม่มี botnoi_token ใน settings.json")
        data = _botnoi_request("GET", "/get_speaker_data_v2")
        rows = data if isinstance(data, list) else data.get("data") or data
        for sp in rows if isinstance(rows, list) else [rows]:
            if not isinstance(sp, dict) or str(sp.get("language", "")).lower() != "th":
                continue
            styles = ", ".join((sp.get("speech_style") or []) + (sp.get("voice_style") or []))
            print(f'{sp.get("speaker_id"):>4}  {sp.get("eng_name", ""):<18} {sp.get("thai_name", ""):<16} '
                  f'{sp.get("gender", ""):<8} {sp.get("age_style", ""):<10} {styles}')
        return
    settings = {}
    if a.speaker:
        settings["speaker"] = a.speaker
    if a.engine:
        settings["engine"] = a.engine
    if a.voice:
        settings["name"] = a.voice
    if a.rate:
        settings["rate"] = int(a.rate) if a.rate.isdigit() else a.rate
    if not _engines(settings):
        sys.exit("ไม่พบเครื่องมือสร้างเสียง — ใส่ botnoi_token ใน settings.json หรือติดตั้ง edge-tts")
    text = " ".join(a.text) or "สวัสดีค่ะ ยินดีต้อนรับสู่ อัพทาวน์ แอสเซ็ทส์"
    print("อ่านว่า:", speakable(text))
    path, dur = synth(text, os.path.join(HERE, "cache", "voice"), settings)
    print(f"{path} ({dur:.1f} วินาที)")
    if last_points is not None:
        print(f"Botnoi: เหลือ {last_points} แต้ม")
    player = shutil.which("afplay") or shutil.which("ffplay")
    if player:
        subprocess.run([player] + (["-nodisp", "-autoexit", "-loglevel", "error"] if player.endswith("ffplay") else []) + [path])


if __name__ == "__main__":
    main()
