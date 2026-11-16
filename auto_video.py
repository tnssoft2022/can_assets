#!/usr/bin/env python3
"""
สร้างวิดีโออัตโนมัติจากโฟลเดอร์ทรัพย์ของ Uptown Assets (มีรูป + รายละเอียด.txt)

วิธีใช้:
    # ทรัพย์เดียว (ระบุโฟลเดอร์ หรือรหัสทรัพย์)
    python3 auto_video.py "<โฟลเดอร์ทรัพย์>"
    python3 auto_video.py 205 1327

    # ทุกทรัพย์ในโฟลเดอร์หลัก
    python3 auto_video.py --all

ตัวเลือก:
    --source DIR      โฟลเดอร์หลักที่เก็บทรัพย์ทั้งหมด (ค่าเริ่มต้นอ่านจาก settings.json → "source_dir")
    --style S         luxury / modern / minimal (ค่าเริ่มต้น modern)
    --formats F       vertical,horizontal (ค่าเริ่มต้นทั้งสองแบบ)
    --max-images N    จำนวนรูปสูงสุดต่อวิดีโอ (ค่าเริ่มต้น 8)
    --music FILE      ไฟล์เพลงประกอบ
    --type T          เฉพาะ rent (เช่า) / sale (ขาย)
    --limit N         ทำแค่ N ทรัพย์แรก (ใช้ทดสอบ)
    --force           สร้างใหม่แม้มีวิดีโออยู่แล้ว (ปกติจะข้าม)
    --config-only     สร้างแค่ config.json ไม่ render (เอาไปแก้ข้อความก่อนได้)
    --make W          สิ่งที่จะสร้าง คั่นด้วย , ได้หลายอย่าง:
                      video (วิดีโอ, ค่าเริ่มต้น) / poster (รูปโปสต์) / storyboard (สตอรี่บอร์ด)
                      both = video,poster   เช่น --make storyboard,video
    --poster-size S   post 1080x1350 (ค่าเริ่มต้น) / square 1080x1080 / story 1080x1920

ผลลัพธ์อยู่ที่ projects/<รหัส>_<ชื่อโครงการ>/  (config.json + output/*.mp4)
config.json ที่สร้างแล้วจะไม่ถูกเขียนทับ — แก้ข้อความในนั้นแล้วรันใหม่ได้เลย
"""
import json
import os
import re
import sys
import time

import make_poster
import make_storyboard
import make_video

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "settings.json")


def load_settings():
    """ค่าที่ต่างกันในแต่ละเครื่อง (เช่น ตำแหน่งโฟลเดอร์ทรัพย์) เก็บใน settings.json"""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


SOURCE_DIR = load_settings().get("source_dir", "")
OUT_ROOT = os.path.join(HERE, "projects")
DETAIL_FILE = "รายละเอียด.txt"

ROOM_TYPES = {
    "Studio": "ห้องสตูดิโอ",
    "Villa": "วิลล่า",
    "Penthouse": "เพนท์เฮาส์",
    "Other": "",
}
DIRECTIONS = {"N": "เหนือ", "S": "ใต้", "E": "ตะวันออก", "W": "ตะวันตก",
              "NE": "ตะวันออกเฉียงเหนือ", "NW": "ตะวันตกเฉียงเหนือ",
              "SE": "ตะวันออกเฉียงใต้", "SW": "ตะวันตกเฉียงใต้"}
MAX_TITLE = 42  # ตัวอักษร (ไม่นับสระบน/ล่าง) ชื่อยาวกว่านี้จะถูกตัดที่ช่องว่าง


# ---------------------------------------------------------------- parsing

def clean(v):
    v = (v or "").strip()
    return "" if v in ("-", ":") else v


def money(text):
    digits = re.sub(r"[^\d.]", "", text or "")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def section(lines, start, stops):
    """บรรทัดหลังหัวข้อ start จนถึงหัวข้อถัดไป"""
    if start not in lines:
        return []
    i = lines.index(start) + 1
    out = []
    while i < len(lines) and lines[i] not in stops:
        if lines[i].strip():
            out.append(lines[i].strip())
        i += 1
    return out


def parse_listing(folder):
    with open(os.path.join(folder, DETAIL_FILE), encoding="utf-8") as f:
        lines = [l.rstrip() for l in f.read().split("\n")]

    info = {"folder": folder, "rent": None, "sale": None, "fields": {}}
    for l in lines[:4]:
        if l.startswith("รหัสอ้างอิง:"):
            info["ref"] = l.split(":", 1)[1].strip()
        if l.startswith("ลิงก์:"):
            info["url"] = l.split(":", 1)[1].strip()
    m = re.match(r"(\d+)_", os.path.basename(folder.rstrip("/")))
    info["id"] = m.group(1) if m else info.get("ref", "").lstrip("0")
    info["project"] = lines[4].strip() if len(lines) > 4 else ""

    end = lines.index("ติดต่อฝ่ายขาย:") if "ติดต่อฝ่ายขาย:" in lines else len(lines)
    i = 5
    while i < end:
        k = lines[i].strip()
        v = lines[i + 1].strip() if i + 1 < end else ""
        if k == "เช่า":
            info["rent"] = money(v)
        elif k == "ขาย":
            info["sale"] = money(v)
        elif k:
            info["fields"][k] = clean(v)
        i += 2

    # ฝ่ายขาย: "ชื่อ (เบอร์)"
    phones = []
    for l in lines[end + 1:]:
        m = re.search(r"\(([\d\-\s]+)\)", l)
        if not m:
            break
        ph = m.group(1).strip()
        if ph not in phones:
            phones.append(ph)
    info["phones"] = phones

    stops = {"รูปภาพ", "เฟอร์นิเจอร์", "รายละเอียดโครงการ", "สถานที่สำคัญใกล้เคียง",
             "สิ่งอำนวยความสะดวก"}
    # หมายเหตุ: รายการเฟอร์นิเจอร์/สิ่งอำนวยความสะดวกในไฟล์เหมือนกันทุกทรัพย์ (เป็นไอคอนทั้งชุดจากเว็บ)
    # จึงไม่นำมาใช้ ใช้ "รายละเอียดห้อง" ที่ฝ่ายขายเขียนเองแทน
    info["description"] = section(lines, "รายละเอียดห้อง", stops)
    info["nearby"] = [p for p in (parse_place(l) for l in section(lines, "สถานที่สำคัญใกล้เคียง", stops)) if p]

    exts = (".jpg", ".jpeg", ".png", ".webp")
    info["images"] = sorted(f for f in os.listdir(folder)
                            if f.lower().endswith(exts) and not f.startswith("."))
    return info


def parse_place(line):
    """แปลงบรรทัดสถานที่ใกล้เคียงหลายรูปแบบ → (ชื่อ, ระยะทาง)
    'นวมินทร์พลาซ่า ห่างจากคอนโด 1.5 กิโลเมตร (ขับรถ 8 นาที)' / 'ท็อปส์เดลี่ – 2.1 กิโลเมตร'
    '– Central West Gate : 9.2 กม.' / '- 7-11 : 30 ม.' / 'รพ.เมโย'"""
    line = line.strip().lstrip("–-•* ").strip()
    if not line or line in (":", "-", "–"):
        return None
    dist = ""
    m = re.search(r"([\d.,]+)\s*(กิโลเมตร|กม\.?|km|เมตร|ม\.)", line)
    if m:
        unit = "กม." if m.group(2).startswith(("กิโล", "กม", "km")) else "ม."
        dist = f"{m.group(1)} {unit}"
        line = line[:m.start()]
    name = re.split(r"\s+ห่าง|\s+[–:]\s*|\s+-\s+|\s*:\s*$", line)[0].strip(" :–-")
    if not name or len(name) > 40:
        return None
    return name, dist


def description_highlights(info):
    """ดึงจุดขายจากข้อความที่ฝ่ายขายเขียน เช่น (วิวทะเล), โอน 50:50, *มีน้ำอุ่น*"""
    out = []
    for i, line in enumerate(info["description"]):
        if "**" in line or re.search(r"line@|co-?broker|เอเจน|นายหน้า|ห้าม|ไม่รับ", line, re.I):
            continue
        if line.startswith("*") and line.endswith("*"):
            out.append(line.strip("* "))
            continue
        # วงเล็บในบรรทัดชื่อประกาศ: (วิวสระว่ายน้ำ)(ขายพร้อมผู้เช่า)
        if re.match(r"(ให้เช่า|ขาย|สำหรับ|เช่า)", line):
            for p in re.findall(r"\(([^)]{2,40})\)", line):
                if not re.search(r"ห้าม|ไม่รับ", p):
                    out.append(p.strip())
        if re.search(r"โอน\s*50\s*:\s*50|โอนคนละครึ่ง", line):
            out.append("ค่าโอนคนละครึ่ง (50:50)")
        if re.search(r"ฟรีค่าโอน|ฟรีโอน", line):
            out.append("ฟรีค่าโอน")
    f = info["fields"]
    if f.get("วิว"):
        out.append(f"วิว{f['วิว']}" if not f["วิว"].startswith("วิว") else f["วิว"])
    if f.get("ทิศ"):
        d = f["ทิศ"].replace("ทิศ", "").strip()
        out.append("ทิศ" + DIRECTIONS.get(d.upper(), d))
    seen, uniq = set(), []
    for h in out:
        if h and h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def is_land(info):
    text = info["project"] + " " + " ".join(info["description"][:3])
    return bool(re.search(r"ที่ดิน|ที่นา|ไร่", text))


def short_title(title):
    title = title.split(" / ")[0].strip()
    if make_video.visual_len(title) <= MAX_TITLE:
        return title
    words, out = title.split(" "), ""
    for w in words:
        nxt = (out + " " + w).strip()
        if make_video.visual_len(nxt) > MAX_TITLE:
            break
        out = nxt
    return out or title[:MAX_TITLE]


# ---------------------------------------------------------------- content

def fmt_baht(v):
    if v >= 1_000_000:
        s = f"{v / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"฿{s} ล้าน"
    return f"฿{v:,.0f}"


def price_text(info):
    rent, sale = info["rent"], info["sale"]
    if sale and rent:
        return f"ขาย {fmt_baht(sale)} | เช่า {fmt_baht(rent)}/ด."
    if sale:
        return f"ขาย {fmt_baht(sale)}"
    if rent:
        return f"ให้เช่า {fmt_baht(rent)} / เดือน"
    return "สอบถามราคา"


def room_text(room):
    if not room:
        return ""
    if room in ROOM_TYPES:
        return ROOM_TYPES[room]
    m = re.match(r"(Duplex\s+)?(\d+)\s+Bedrooms?", room)
    if m:
        return ("ดูเพล็กซ์ " if m.group(1) else "") + f"{m.group(2)} ห้องนอน"
    return room


def build_config(info, style, max_images, music, formats):
    f = info["fields"]
    building, floor = f.get("อาคาร", ""), f.get("ชั้นห้อง", "")
    size, bath = f.get("ขนาดห้อง", ""), f.get("ห้องน้ำ", "")

    loc = []
    if building:
        loc.append(f"ตึก {building}")
    if floor:
        loc.append(f"ชั้น {floor}")
    location = " ".join(loc)
    station = f.get("สถานีใกล้เคียง", "")
    near = station or (info["nearby"][0][0] if info["nearby"] else "")
    near = re.sub(r"\s*\(.*?\)", "", near).strip()
    if near:
        location = f"{location} | ใกล้ {near}" if location else f"ใกล้ {near}"

    land = is_land(info)
    details = []
    if not land:
        details.append(room_text(f.get("ประเภทห้อง", "")))
        if bath and bath != "0":
            details.append(f"{bath} ห้องน้ำ")
    if size and money(size) and not land:  # ขนาดของที่ดินในไฟล์ไม่น่าเชื่อถือ (เช่น 1) จึงไม่แสดง
        details.append(f"{size} ตร.ม.")
    if floor and not land:
        details.append(f"ชั้น {floor}")
    details = [d for d in details if d]

    # คำบรรยายรูป: ไม่รู้ว่ารูปไหนคือห้องอะไร จึงใช้จุดขายของทรัพย์วนแสดงแทน
    highlights = description_highlights(info)
    for name, dist in info["nearby"][:3]:
        highlights.append(f"ใกล้ {name}" + (f" {dist}" if dist else ""))
    if info["sale"] and info["rent"]:
        highlights.append("ขายหรือเช่าก็ได้")

    imgs = info["images"][:max_images]
    images = [{"file": im, "caption": highlights[i] if i < len(highlights) else ""}
              for i, im in enumerate(imgs)]
    # รูปแรกเป็นฉากเปิด (มีชื่อโครงการแล้ว) ไม่ต้องมีคำบรรยาย → เลื่อนจุดเด่นไปเริ่มรูปที่ 2
    if len(images) > 1:
        for i in range(len(images) - 1, 0, -1):
            images[i]["caption"] = images[i - 1]["caption"]
        images[0]["caption"] = ""

    # บทพากย์พื้นฐาน: ฉากแรก = ชื่อ + ราคา, ฉากอื่น = คำบรรยายของรูป, ฉากปิด = ช่องทางติดต่อ
    # (แก้ใน config.json ได้ — สตอรี่บอร์ดแสดงบทพากย์ทุกฉาก)
    if images:
        images[0]["narration"] = f"{short_title(info['project'])} {price_text(info)}"
    for im in images[1:]:
        im["narration"] = im["caption"]
    first_phone = info["phones"][0] if info["phones"] else ""
    outro_narration = "สนใจติดต่อ อัพทาวน์ แอสเซ็ทส์" + (f" โทร {first_phone}" if first_phone else "")

    ref = info.get("ref") or info["id"]
    cfg = {
        "title": short_title(info["project"]),
        "location": location,
        "price": price_text(info),
        "details": details,
        "contact": {
            "name": f"Uptown Assets  รหัสทรัพย์ {ref}",
            "phone": " / ".join(info["phones"][:2]),
            "line": "",
        },
        "style": style,
        "image_dir": info["folder"],
        "images": images,
        "outro_seconds": 4.5,
        **({"music": music} if music else {}),  # ไม่ระบุ = เพลงประจำสไตล์ใน brand/music/
        "outro_narration": outro_narration,
        "formats": formats,
        "_source": info.get("url", ""),
    }
    return cfg


# ---------------------------------------------------------------- main

def safe_name(text):
    text = re.sub(r"[\\/:*?\"<>|]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:60]


def find_listing(arg, source):
    if os.path.isdir(arg):
        return os.path.abspath(arg)
    if arg.isdigit():
        for d in os.listdir(source):
            if d.split("_", 1)[0] == arg:
                return os.path.join(source, d)
    return None


def parse_args(argv):
    opts = {"source": SOURCE_DIR, "style": "modern", "formats": ["vertical", "horizontal"],
            "max_images": 8, "music": None, "type": None, "limit": None,
            "force": False, "all": False, "config_only": False, "targets": [],
            "make": "video", "poster_size": "post"}
    it = iter(argv)
    for a in it:
        if a == "--all":
            opts["all"] = True
        elif a == "--force":
            opts["force"] = True
        elif a == "--config-only":
            opts["config_only"] = True
        elif a == "--source":
            opts["source"] = next(it)
        elif a == "--style":
            opts["style"] = next(it)
        elif a == "--formats":
            opts["formats"] = next(it).split(",")
        elif a == "--max-images":
            opts["max_images"] = int(next(it))
        elif a == "--music":
            opts["music"] = os.path.abspath(next(it))
        elif a == "--type":
            opts["type"] = next(it)
        elif a == "--make":
            opts["make"] = next(it)
        elif a == "--poster-size":
            opts["poster_size"] = next(it)
        elif a == "--limit":
            opts["limit"] = int(next(it))
        elif a.startswith("--"):
            sys.exit(f"ไม่รู้จักตัวเลือก {a}")
        else:
            opts["targets"].append(a)
    return opts


def main():
    if hasattr(sys.stdout, "reconfigure"):  # คอนโซล Windows บางแบบพิมพ์สัญลักษณ์ ✓ ✗ ไม่ได้
        sys.stdout.reconfigure(errors="replace")
    opts = parse_args(sys.argv[1:])
    needs_source = opts["all"] or any(not os.path.isdir(t) for t in opts["targets"])
    if needs_source and (not opts["source"] or not os.path.isdir(opts["source"])):
        sys.exit("ไม่พบโฟลเดอร์ทรัพย์ — ตั้งค่า \"source_dir\" ใน settings.json (ดู settings.example.json) "
                 "หรือระบุด้วย --source <โฟลเดอร์>"
                 + (f"\n  (ค่าปัจจุบัน: {opts['source']})" if opts["source"] else ""))
    kinds = set()
    for k in opts["make"].split(","):
        k = k.strip()
        kinds |= {"video", "poster"} if k == "both" else {k}
    if not kinds or not kinds <= {"video", "poster", "storyboard"}:
        sys.exit("--make ต้องเป็น video / poster / storyboard / both (คั่นด้วย , ได้)")
    opts["kinds"] = kinds
    if opts["poster_size"] not in make_poster.SIZES:
        sys.exit(f"--poster-size ต้องเป็น: {', '.join(make_poster.SIZES)}")
    if opts["style"] not in make_video.THEMES:
        sys.exit(f"สไตล์ต้องเป็น: {', '.join(make_video.THEMES)}")

    if opts["all"]:
        folders = sorted(
            (os.path.join(opts["source"], d) for d in os.listdir(opts["source"])
             if os.path.isfile(os.path.join(opts["source"], d, DETAIL_FILE))),
            key=lambda p: int(re.match(r"(\d+)", os.path.basename(p)).group(1))
            if re.match(r"\d+", os.path.basename(p)) else 0)
    elif opts["targets"]:
        folders = []
        for t in opts["targets"]:
            f = find_listing(t, opts["source"])
            if not f:
                sys.exit(f"ไม่พบทรัพย์ {t}")
            folders.append(f)
    else:
        print(__doc__)
        sys.exit(1)

    done, skipped, failed = 0, 0, []
    count = 0
    t0 = time.time()
    for folder in folders:
        if opts["limit"] is not None and count >= opts["limit"]:
            break
        try:
            info = parse_listing(folder)
        except Exception as e:  # noqa: BLE001
            failed.append((folder, f"อ่านไฟล์ไม่ได้: {e}"))
            continue
        if opts["type"] == "rent" and not info["rent"]:
            continue
        if opts["type"] == "sale" and not info["sale"]:
            continue
        if not info["images"]:
            failed.append((folder, "ไม่มีรูป"))
            continue
        count += 1

        proj = os.path.join(OUT_ROOT, f"{info['id']}_{safe_name(short_title(info['project']))}")
        cfg_path = os.path.join(proj, "config.json")
        os.makedirs(proj, exist_ok=True)
        if not os.path.exists(cfg_path) or opts["force"]:
            cfg = build_config(info, opts["style"], opts["max_images"], opts["music"], opts["formats"])
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        label = f"[{count}] {info['id']} {info['project']}"
        if opts["config_only"]:
            print(f"✎ {label} → {cfg_path}")
            continue
        print(f"\n=== {label}")
        try:
            made = []
            if "storyboard" in opts["kinds"]:
                for fmt in opts["formats"]:
                    p = make_storyboard.make(proj, opts["style"], fmt, skip_existing=not opts["force"])
                    made += [p] if p else []
            if "video" in opts["kinds"]:
                made += make_video.make(proj, opts["style"], opts["formats"], skip_existing=not opts["force"])
            if "poster" in opts["kinds"]:
                p = make_poster.make(proj, opts["style"], opts["poster_size"], skip_existing=not opts["force"])
                made += [p] if p else []
            if made:
                done += 1
            else:
                skipped += 1
                print("  (มีไฟล์อยู่แล้ว ข้าม — ใช้ --force เพื่อสร้างใหม่)")
        except (Exception, SystemExit) as e:  # noqa: BLE001
            failed.append((folder, str(e)))
            print(f"  ✗ ล้มเหลว: {e}")

    mins = (time.time() - t0) / 60
    print(f"\nสรุป: สร้างใหม่ {done} | ข้าม {skipped} | ล้มเหลว {len(failed)} | ใช้เวลา {mins:.1f} นาที")
    for folder, err in failed:
        print(f"  ✗ {os.path.basename(folder)}: {err}")


if __name__ == "__main__":
    main()
