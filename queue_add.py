#!/usr/bin/env python3
"""ส่งงานเข้าคิว (queue_app.py) จากแชท / command line — เปิดเซิร์ฟเวอร์คิวให้เองถ้ายังไม่เปิด

    python3 queue_add.py <ลิงก์> [<ลิงก์> ...] [--image <ไฟล์> ...] [--notes "ข้อความ"]
    python3 queue_add.py --list                 ดูสถานะทุกรายการ
    python3 queue_add.py --cancel <id>          ยกเลิกรายการ
    python3 queue_add.py --agent <ลิงก์> ...     เพิ่มรายการที่ subagent ในแชททำ (คิวไม่รัน claude -p เอง)

subagent รายงานความคืบหน้า (ถ้าผู้ใช้กดยกเลิกแล้ว → พิมพ์ CANCELLED และจบด้วยรหัส 3 = ต้องหยุดทำทันที):
    python3 queue_add.py --report <id> --step fetch|images|write|choose|video|storyboard|poster
    python3 queue_add.py --report <id> --project projects/<โฟลเดอร์>
    python3 queue_add.py --report <id> --done --project projects/<โฟลเดอร์> --summary "ข้อมูลโครงการ"
    python3 queue_add.py --report <id> --fail "สาเหตุ"

- ลิงก์ละ 1 รายการ / รูปทั้งหมด (+ ลิงก์แรกถ้ามี) รวมเป็น 1 รายการ / --notes ใช้กับทุกรายการที่เพิ่มรอบนี้
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("QUEUE_PORT", 8790))
BASE = f"http://127.0.0.1:{PORT}"


def call(path_, body=None):
    req = urllib.request.Request(BASE + path_, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit("ผิดพลาด: " + json.loads(e.read() or b"{}").get("error", str(e)))


def ensure_server():
    try:
        call("/api/items")
        return
    except (urllib.error.URLError, ConnectionError):
        pass
    os.makedirs(os.path.join(ROOT, "queue"), exist_ok=True)
    log = open(os.path.join(ROOT, "queue", "server.log"), "a")
    subprocess.Popen([sys.executable, os.path.join(ROOT, "queue_app.py"), "--port", str(PORT)], cwd=ROOT,
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        time.sleep(0.25)
        try:
            call("/api/items")
            print(f"เปิดเซิร์ฟเวอร์คิว: http://localhost:{PORT}/")
            return
        except (urllib.error.URLError, ConnectionError):
            pass
    sys.exit("เปิดเซิร์ฟเวอร์คิวไม่ได้ — ดู queue/server.log")


def main():
    args = sys.argv[1:]
    if os.environ.get("QUEUE_WORKER"):
        sys.exit("กำลังทำงานในคิวอยู่แล้ว — ทำขั้นตอนใน CLAUDE.md เอง ห้ามส่งเข้าคิวซ้ำ")
    ensure_server()
    if "--list" in args:
        j = call("/api/items")
        if not j["claude"]:
            print("⚠ ไม่พบคำสั่ง claude")
        for it in j["items"]:
            step = j["steps"][it["step"]][1] if 0 <= it["step"] < len(j["steps"]) else ""
            print(f"{it['id']}  {it['status']:<10} {step:<22} {it.get('project') or it['url'] or 'รูป'}"
                  + (f"\n    ! {it['error'][:200]}" if it.get("error") and it["status"] == "error" else ""))
        return
    if "--report" in args:
        def val(flag):
            return args[args.index(flag) + 1] if flag in args else None
        body = {"id": val("--report"), "step": val("--step"), "project": val("--project"),
                "summary": val("--summary"), "log": val("--log")}
        if "--done" in args:
            body["status"] = "done"
        if "--fail" in args:
            body["status"], body["error"] = "error", val("--fail")
        j = call("/api/report", body)
        if j.get("cancelled"):
            print("CANCELLED — ผู้ใช้ยกเลิกรายการนี้แล้ว หยุดทำทันที")
            sys.exit(3)
        print("ok", j["status"])
        return
    if "--cancel" in args:
        call("/api/cancel", {"id": args[args.index("--cancel") + 1]})
        print("ยกเลิกแล้ว")
        return
    urls, images, notes = [], [], ""
    worker = "agent" if "--agent" in args else "cli"
    args = [a for a in args if a != "--agent"]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--notes":
            notes, i = args[i + 1], i + 2
        elif a == "--image":
            images.append(os.path.abspath(os.path.expanduser(args[i + 1])))
            i += 2
        else:
            urls.append(a)
            i += 1
    j = call("/api/add", {"urls": "\n".join(urls), "notes": notes, "image_paths": images, "worker": worker,
                                "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")})
    print(f"เพิ่มเข้าคิว {len(j['added'])} รายการ: " + ", ".join(j["added"]))


if __name__ == "__main__":
    main()
