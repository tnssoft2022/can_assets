#!/usr/bin/env python3
"""คิวงาน — ใส่ลิงก์ / รูป / ข้อมูลทรัพย์ได้หลายรายการ แสดงขั้นตอนของแต่ละรายการ และยกเลิกทีละรายการได้

    python3 queue_app.py [--port 8790] [--parallel 1]

เปิด http://localhost:8790 (หรือเปิดในแผงเบราว์เซอร์ข้างแชทของ Claude)

แต่ละรายการรัน `claude -p` (Claude Code แบบไม่มีหน้าจอ) ทำตามขั้นตอนใน CLAUDE.md
→ วิดีโอแนวตั้ง + สตอรี่บอร์ด + รูปโปสต์ ใน projects/<รหัส>_<ชื่อ>/output/
ขั้นตอนดูจากคำสั่งที่ Claude เรียก (make_video.py ฯลฯ) และบรรทัด @@STEP ที่ Claude พิมพ์
ยกเลิก = หยุด process ของรายการนั้น (รายการอื่นทำต่อ)
สถานะ + log เก็บใน queue/ (ไม่เก็บใน git)
"""
import base64
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
QDIR = os.path.join(ROOT, "queue")
UI = os.path.join(ROOT, "queue_ui", "index.html")
STATE = os.path.join(QDIR, "state.json")

STEPS = [
    ("fetch", "ดึงข้อมูล"),
    ("images", "ดึงรูป"),
    ("write", "ตรวจลายน้ำ / เขียนบท"),
    ("choose", "เลือกสไตล์ / รูป"),
    ("video", "วิดีโอ"),
    ("storyboard", "สตอรี่บอร์ด"),
    ("poster", "รูปโปสต์"),
]
STEP_KEYS = [k for k, _ in STEPS]

# เครื่องมือที่ Claude ใช้ได้ในคิว (ไม่ต้องกดอนุญาต)
ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "WebFetch",
    "Bash(python3:*)", "Bash(.venv/bin/python:*)", "Bash(curl:*)", "Bash(mkdir:*)", "Bash(ls:*)",
    "Bash(cp:*)", "Bash(mv:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(file:*)", "Bash(ffprobe:*)",
    "Bash(ffmpeg:*)", "Bash(sips:*)", "Bash(echo:*)", "Bash(cd:*)", "Bash(grep:*)", "Bash(sed:*)",
    "Bash(wc:*)", "Bash(find:*)", "Bash(rm:*)", "Bash(for:*)",
]

PROMPT = """คุณกำลังทำงานในคิวงานอัตโนมัติ (ไม่มีผู้ใช้ตอบคำถาม) — ทำตามขั้นตอน 1–7 ใน CLAUDE.md เองให้ครบจนได้ 3 ชิ้น
(ห้ามส่งเข้าคิวซ้ำด้วย queue_add.py)
(วิดีโอแนวตั้ง + สตอรี่บอร์ด + รูปโปสต์) ห้ามถามผู้ใช้ ตัดสินใจเองตาม CLAUDE.md

ก่อนเริ่มแต่ละขั้น ให้พิมพ์บรรทัดข้อความ (ไม่ต้องรันคำสั่ง) ว่า `@@STEP <ขั้น>` โดย <ขั้น> คือหนึ่งใน:
fetch (ดึงข้อมูล), images (ดึงรูป/เตรียมรูป), write (ตรวจลายน้ำ + เขียนคำบรรยาย/บทพากย์), choose (choose.py --apply),
video, storyboard, poster

เมื่อเสร็จ ให้จบด้วยบรรทัด `@@RESULT projects/<โฟลเดอร์โครงการ>` แล้วตามด้วยข้อมูลโครงการสั้น ๆ
(ชื่อ, ทำเล, ราคา, รายละเอียด, เบอร์โทร) และหมายเหตุบรรทัดเดียวถ้ามีเรื่องที่ผู้ใช้ต้องรู้
(เช่น ไม่มีราคา, รูปที่ตัดทิ้งเพราะลายน้ำบริษัทอื่น)

งานนี้:
"""

lock = threading.Lock()
items = []          # รายการทั้งหมด (dict)
procs = {}          # id → Popen
opts = {"port": 8790, "parallel": 1}


# ---------- หา claude ----------

def find_claude():
    try:
        with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as f:
            b = json.load(f).get("claude_bin")
        if b and os.path.exists(b):
            return b
    except (OSError, ValueError):
        pass
    b = shutil.which("claude")
    if b:
        return b
    for pat in (
        "~/.claude/local/claude",
        "~/.local/bin/claude",
        "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude",
    ):
        hits = sorted(glob.glob(os.path.expanduser(pat)), key=os.path.getmtime, reverse=True)
        if hits:
            return hits[0]
    return None


# ---------- สถานะ ----------

def save():
    os.makedirs(QDIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def load():
    global items
    try:
        with open(STATE, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        items = []
    for it in items:  # เซิร์ฟเวอร์ปิดไประหว่างทำ
        if it["status"] == "running" and it.get("worker") != "agent":  # subagent ยังทำต่อได้
            it["status"] = "error"
            it["error"] = "เซิร์ฟเวอร์คิวถูกปิดระหว่างทำ — กดลองใหม่ได้"


def find(item_id):
    return next((it for it in items if it["id"] == item_id), None)


def log_event(it, text):
    it["log"].append({"t": time.time(), "text": text[:400]})
    it["log"] = it["log"][-60:]


def set_step(it, key):
    if key in STEP_KEYS:
        i = STEP_KEYS.index(key)
        if i > it["step"]:
            it["step"] = i


# ---------- ดูขั้นตอนจาก stream-json ----------

def detect_from_tool(it, name, inp):
    cmd = inp.get("command", "") if isinstance(inp, dict) else ""
    fp = inp.get("file_path", "") if isinstance(inp, dict) else ""
    if name == "WebFetch" or (name == "Bash" and "curl" in cmd and "uptownassets" in cmd and "storage/images" not in cmd):
        set_step(it, "fetch")
    if "storage/images/projects" in cmd or "/images/" in fp and name == "Write":
        set_step(it, "images")
    if name in ("Write", "Edit") and fp.endswith("config.json"):
        set_step(it, "write")
    if name == "Read" and re.search(r"\.(webp|jpe?g|png)$", fp, re.I) and it["step"] >= 1:
        set_step(it, "write")
    for script, key in (("choose.py", "choose"), ("make_video.py", "video"),
                        ("make_storyboard.py", "storyboard"), ("make_poster.py", "poster")):
        if script in cmd:
            set_step(it, key)
    m = re.search(r"projects/([^/\s'\"]+)", cmd + " " + fp)
    if m and not it.get("project"):
        it["project"] = "projects/" + m.group(1)


def short_tool(name, inp):
    if not isinstance(inp, dict):
        return name
    s = inp.get("command") or inp.get("file_path") or inp.get("url") or inp.get("pattern") or ""
    return f"{name}: {s}" if s else name


def handle_line(it, line):
    try:
        ev = json.loads(line)
    except ValueError:
        return
    t = ev.get("type")
    if t == "assistant":
        for c in ev.get("message", {}).get("content", []):
            if c.get("type") == "text":
                txt = c.get("text", "")
                for m in re.finditer(r"@@STEP\s+(\w+)", txt):
                    set_step(it, m.group(1))
                m = re.search(r"@@RESULT\s+(projects/[^\s`]+)", txt)
                if m:
                    it["project"] = m.group(1).rstrip("/")
                if txt.strip():
                    log_event(it, txt.strip())
            elif c.get("type") == "tool_use":
                detect_from_tool(it, c.get("name", ""), c.get("input", {}))
                log_event(it, "▸ " + short_tool(c.get("name", ""), c.get("input", {})))
    elif t == "result":
        it["summary"] = ev.get("result", "") or ""
        it["cost"] = ev.get("total_cost_usd")
        m = re.search(r"@@RESULT\s+(projects/[^\s`]+)", it["summary"])
        if m:
            it["project"] = m.group(1).rstrip("/")
        if ev.get("is_error"):
            it["error"] = it["summary"][:500] or "Claude แจ้งข้อผิดพลาด"


# ---------- ทำงาน ----------

def outputs_of(project):
    if not project:
        return {}
    out = os.path.join(ROOT, project, "output")
    def newest(pat):
        hits = sorted(glob.glob(os.path.join(out, pat)), key=os.path.getmtime, reverse=True)
        return os.path.relpath(hits[0], ROOT) if hits else None
    return {
        "video": newest("*.mp4"),
        "poster": newest("*_poster_*.jpg") or newest("*_poster_*.png"),
        "storyboard": newest("*_storyboard.md"),
    }


def build_prompt(it):
    parts = []
    if it.get("url"):
        parts.append(f"ลิงก์: {it['url']}")
    if it.get("uploads"):
        parts.append("รูปที่ผู้ใช้อัปโหลด (ไม่มีหน้าเว็บสำหรับรูปเหล่านี้ — คัดลอกเข้า images/ ของโครงการ"
                     " เรียงตามลำดับนี้ แล้วทำต่อตามขั้นตอน):\n" + "\n".join("- " + u for u in it["uploads"]))
        if not it.get("url"):
            parts.append("ไม่มีลิงก์ — ตั้งชื่อโฟลเดอร์เป็น projects/up<เวลา>_<ชื่อโครงการภาษาอังกฤษ>/"
                         " และใช้ข้อมูลด้านล่างแทนหน้าเว็บ (ข้อที่ไม่มีให้ใส่ \"สอบถามราคา\" ฯลฯ ห้ามแต่งเอง)")
    if it.get("notes"):
        parts.append("ข้อมูลเพิ่มเติม/คำสั่งจากผู้ใช้ (ใช้ตามนี้ก่อนค่าเริ่มต้น):\n" + it["notes"])
    return PROMPT + "\n\n".join(parts)


def run_item(it):
    claude = find_claude()
    with lock:
        if not claude:
            it["status"], it["error"] = "error", "ไม่พบคำสั่ง claude — ใส่ \"claude_bin\" ใน settings.json"
            save()
            return
    d = os.path.join(QDIR, it["id"])
    os.makedirs(d, exist_ok=True)
    cmd = [claude, "-p", build_prompt(it), "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS]
    raw = open(os.path.join(d, "stream.jsonl"), "w", encoding="utf-8")
    err = open(os.path.join(d, "stderr.txt"), "w", encoding="utf-8")
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
                             text=True, encoding="utf-8", start_new_session=True,
                             env={**os.environ, "QUEUE_WORKER": "1"})  # กันส่งเข้าคิวซ้ำ (queue_add.py)
    except OSError as e:
        with lock:
            it["status"], it["error"] = "error", f"เปิด claude ไม่ได้: {e}"
            save()
        return
    with lock:
        procs[it["id"]] = p
        it["pid"] = p.pid
        save()
    last_save = 0
    for line in p.stdout:
        raw.write(line)
        with lock:
            handle_line(it, line)
            if time.time() - last_save > 1:
                save()
                last_save = time.time()
    rc = p.wait()
    raw.close()
    err.close()
    with lock:
        procs.pop(it["id"], None)
        it["finished"] = time.time()
        it["outputs"] = outputs_of(it.get("project"))
        if it["status"] == "cancelling":
            it["status"] = "cancelled"
        elif rc == 0 and not it.get("error") and it["outputs"].get("video") and it["outputs"].get("poster"):
            it["status"], it["step"] = "done", len(STEPS)
        else:
            it["status"] = "error"
            if not it.get("error"):
                try:
                    tail = open(os.path.join(d, "stderr.txt"), encoding="utf-8").read()[-400:].strip()
                except OSError:
                    tail = ""
                it["error"] = tail or ("ไม่พบวิดีโอ/รูปโปสต์ใน output" if rc == 0 else f"claude จบด้วยรหัส {rc}")
        save()


def scheduler():
    while True:
        with lock:
            running = sum(1 for it in items if it["status"] in ("running", "cancelling"))
            nxt = next((it for it in items if it["status"] == "queued" and it.get("worker") != "agent"), None)
            if nxt and running < opts["parallel"]:
                nxt["status"], nxt["started"] = "running", time.time()
                save()
                threading.Thread(target=run_item, args=(nxt,), daemon=True).start()
                continue
        time.sleep(0.5)


def cancel(it):
    if it["status"] == "queued" or it.get("worker") == "agent":
        it["status"] = "cancelled"  # subagent เห็นตอนรายงานขั้นถัดไป แล้วหยุดเอง
    elif it["status"] == "running":
        it["status"] = "cancelling"
        p = procs.get(it["id"])
        if p:
            try:
                os.killpg(p.pid, signal.SIGTERM)  # หยุดทั้ง claude และ ffmpeg/python ที่มันเรียก
            except ProcessLookupError:
                pass
            threading.Timer(5, lambda: _kill_hard(p)).start()


def _kill_hard(p):
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def new_item(url, notes, images, paths=()):
    """images = [{name, data(base64)}] จากหน้าเว็บ / paths = ไฟล์รูปในเครื่อง (จากแชท)"""
    it = {"id": time.strftime("%y%m%d-%H%M%S-") + uuid.uuid4().hex[:4], "url": url.strip(),
          "notes": notes.strip(), "uploads": [], "status": "queued", "step": -1, "log": [],
          "created": time.time(), "project": None, "outputs": {}, "error": None, "summary": ""}
    if images or paths:
        d = os.path.join(QDIR, it["id"], "uploads")
        os.makedirs(d, exist_ok=True)
        n = 0
        for img in images:
            n += 1
            name = re.sub(r"[^\w.\-]", "_", img.get("name", f"{n}.jpg"))[-60:]
            fp = os.path.join(d, f"{n:02d}_{name}")
            with open(fp, "wb") as f:
                f.write(base64.b64decode(img["data"].split(",", 1)[-1]))
            it["uploads"].append(os.path.relpath(fp, ROOT))
        for src in paths:
            n += 1
            name = re.sub(r"[^\w.\-]", "_", os.path.basename(src))[-60:]
            fp = os.path.join(d, f"{n:02d}_{name}")
            shutil.copyfile(src, fp)
            it["uploads"].append(os.path.relpath(fp, ROOT))
    return it


# ---------- รูปย่อสำหรับแผงในแอป (queue-toggle mod) ----------

def thumb_b64(rel, width):
    """รูปย่อ JPEG (base64) ของรูป หรือเฟรมจากวิดีโอ — เก็บไว้ใน queue/thumbs/"""
    full = os.path.normpath(os.path.join(ROOT, rel))
    if not full.startswith(os.path.join(ROOT, "projects") + os.sep) or not os.path.isfile(full):
        return None
    key = re.sub(r"[^\w.-]", "_", rel) + f"_{width}_{int(os.path.getmtime(full))}.jpg"
    out = os.path.join(QDIR, "thumbs", key)
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if full.lower().endswith(".mp4"):  # เฟรมที่ 3 วินาที
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", "3", "-i", full, "-frames:v", "1",
                   "-vf", f"scale={width}:-2", "-q:v", "6", out]
        else:
            cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "60", "--resampleWidth", str(width),
                   full, "--out", out]
        if subprocess.run(cmd, capture_output=True).returncode != 0 or not os.path.exists(out):
            return None
    with open(out, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ---------- วิดีโอทั้งหมด (หน้า /videos) ----------

def all_videos():
    """ทุกไฟล์ .mp4 ใน projects/*/output/ ใหม่สุดก่อน + ข้อมูลโครงการไว้ค้นหา"""
    vids = []
    for full in glob.glob(os.path.join(ROOT, "projects", "*", "output", "*.mp4")):
        proj = os.path.basename(os.path.dirname(os.path.dirname(full)))
        cfg = {}
        try:
            with open(os.path.join(ROOT, "projects", proj, "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            pass
        out = os.path.dirname(full)
        posters = sorted(glob.glob(os.path.join(out, "*_poster_*.jpg")) + glob.glob(os.path.join(out, "*_poster_*.png")),
                         key=os.path.getmtime, reverse=True)
        details = cfg.get("details") if isinstance(cfg.get("details"), list) else []
        vids.append({
            "path": os.path.relpath(full, ROOT),
            "file": os.path.basename(full),
            "project": proj,
            "title": cfg.get("title") or proj,
            "location": cfg.get("location", ""),
            "price": cfg.get("price", ""),
            "details": [str(d) for d in details],
            "style": cfg.get("style", ""),
            "poster": os.path.relpath(posters[0], ROOT) if posters else None,
            "mtime": os.path.getmtime(full),
            "size": os.path.getsize(full),
        })
    vids.sort(key=lambda v: v["mtime"], reverse=True)
    return vids


# ---------- HTTP ----------

def public(it):
    return {k: v for k, v in it.items() if k not in ("pid",)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path_ = unquote(urlparse(self.path).path)
        if path_ == "/":
            with open(UI, "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if path_ == "/videos":
            with open(os.path.join(ROOT, "queue_ui", "videos.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if path_ == "/api/videos":
            return self.send(200, {"videos": all_videos()})
        if path_ == "/api/thumb":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            data = thumb_b64(q.get("path", [""])[0], max(80, min(600, int(q.get("w", ["300"])[0]))))
            return self.send(200 if data else 404, {"data": data})
        if path_ == "/api/items":
            with lock:
                return self.send(200, {"items": [public(i) for i in items], "steps": STEPS, "root": ROOT,
                                       "parallel": opts["parallel"], "claude": bool(find_claude())})
        if path_.startswith("/files/"):  # เฉพาะไฟล์ใน projects/ และ queue/
            rel = os.path.normpath(path_[len("/files/"):])
            full = os.path.join(ROOT, rel)
            if rel.split(os.sep)[0] not in ("projects", "queue") or ".." in rel or not os.path.isfile(full):
                return self.send(404, {"error": "not found"})
            return self.send_file(full)
        self.send(404, {"error": "not found"})

    def send_file(self, full):
        ext = os.path.splitext(full)[1].lower()
        ctype = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".webp": "image/webp", ".md": "text/markdown; charset=utf-8"}.get(ext, "application/octet-stream")
        size = os.path.getsize(full)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):  # วิดีโอเลื่อนได้
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = min(int(b), size - 1) if b else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(full, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_POST(self):
        path_ = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad json"})
        with lock:
            if path_ == "/api/add":
                urls = [u for u in re.split(r"\s+", data.get("urls", "")) if u.startswith("http")]
                images, notes = data.get("images") or [], data.get("notes", "")
                paths = [os.path.expanduser(p) for p in data.get("image_paths") or []]
                bad = [p for p in paths if not os.path.isfile(p)]
                if bad:
                    return self.send(400, {"error": "ไม่พบไฟล์รูป: " + ", ".join(bad)})
                if not urls and not images and not paths:
                    return self.send(400, {"error": "ใส่ลิงก์ หรือ รูปอย่างน้อย 1 อย่าง"})
                added = []
                worker = "agent" if data.get("worker") == "agent" else "cli"
                if images or paths:  # รูป + ข้อมูล = 1 รายการ (ใช้ลิงก์แรกถ้ามี)
                    added.append(new_item(urls.pop(0) if urls else "", notes, images, paths))
                for u in urls:  # ลิงก์ที่เหลือ = รายการละลิงก์
                    added.append(new_item(u, notes, []))
                for a in added:
                    a["worker"] = worker
                    a["session"] = str(data.get("session") or "")  # session ของ Claude ที่เพิ่ม (แผงคิวกรองตามนี้)
                items.extend(added)
                save()
                return self.send(200, {"added": [a["id"] for a in added]})
            if path_ == "/api/report":  # subagent ใน Claude Code รายงานความคืบหน้า
                it = find(data.get("id", ""))
                if not it:
                    return self.send(404, {"error": "ไม่พบรายการ"})
                if it["status"] in ("cancelled", "cancelling"):
                    return self.send(200, {"cancelled": True, "status": it["status"]})
                if data.get("step"):
                    if it["status"] == "queued":
                        it["status"], it["started"] = "running", time.time()
                    set_step(it, data["step"])
                    log_event(it, "@@STEP " + data["step"])
                if data.get("log"):
                    log_event(it, data["log"])
                if data.get("project"):
                    it["project"] = data["project"].rstrip("/")
                if data.get("summary"):
                    it["summary"] = data["summary"]
                if data.get("status") == "done":
                    it["outputs"] = outputs_of(it.get("project"))
                    it["status"], it["step"], it["finished"] = "done", len(STEPS), time.time()
                elif data.get("status") == "error":
                    it["status"], it["error"], it["finished"] = "error", data.get("error") or "ผิดพลาด", time.time()
                save()
                return self.send(200, {"cancelled": False, "status": it["status"]})
            if path_ == "/api/parallel":
                opts["parallel"] = max(1, min(4, int(data.get("parallel", 1))))
                return self.send(200, {"parallel": opts["parallel"]})
            it = find(data.get("id", ""))
            if not it:
                return self.send(404, {"error": "ไม่พบรายการ"})
            if path_ == "/api/cancel":
                cancel(it)
            elif path_ == "/api/retry" and it["status"] in ("error", "cancelled") and it.get("worker") != "agent":
                it.update(status="queued", step=-1, error=None, log=[], summary="", outputs={})
            elif path_ == "/api/remove" and it["status"] not in ("running", "cancelling"):
                items.remove(it)
            else:
                return self.send(400, {"error": "ทำไม่ได้ในสถานะนี้"})
            save()
            return self.send(200, {"ok": True})


def main():
    args = sys.argv[1:]
    for flag in ("--port", "--parallel"):
        if flag in args:
            opts[flag[2:]] = int(args[args.index(flag) + 1])
    load()
    threading.Thread(target=scheduler, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", opts["port"]), Handler)
    print(f"คิวงาน: http://localhost:{opts['port']}/  (claude: {find_claude() or 'ไม่พบ'})", flush=True)

    def stop(*_):
        with lock:
            for p in procs.values():
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.serve_forever()


if __name__ == "__main__":
    main()
