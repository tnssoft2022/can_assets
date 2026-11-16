#!/usr/bin/env python3
"""
สร้างวิดีโออสังหาฯ จากรูปภาพ (แนวตั้ง 9:16 และแนวนอน 16:9)

วิธีใช้:
    python3 make_video.py projects/<ชื่อโปรเจกต์> [--style <สไตล์>] [vertical] [horizontal]

สไตล์:
    luxury    หรูหรา     — ดำ-ทอง ไม่มีกล่องข้อความ เงาไล่สี เคลื่อนไหวช้า
    modern    ทันสมัย    — แถบสีสด ตัวหนา เปลี่ยนภาพแบบสไลด์ จังหวะเร็ว
    minimal   มินิมอล    — กล่องขาว ตัวอักษรเข้ม สะอาดตา
    bold      ป้ายเซล    — เหลือง-ดำ ตัวใหญ่ ราคาเด่น จังหวะเร็วมาก
    nature    ธรรมชาติ   — เขียว-ครีม นุ่ม เฟดช้า
    corporate ทางการ     — น้ำเงินกรมท่า-ขาว เรียบ
    night     หรูกลางคืน — โทนมืด ตัวอักษรขาว สีฟ้าเรืองแสง

โครงสร้างโฟลเดอร์โปรเจกต์:
    projects/<ชื่อ>/
        config.json      ข้อมูลทรัพย์ (สร้างอัตโนมัติด้วย auto_video.py หรือเขียนเอง)
        images/          รูปภาพ .jpg/.jpeg/.png/.webp (เรียงตามชื่อไฟล์)
        music.mp3        (ไม่บังคับ) เพลงประกอบ
        logo.png         (ไม่บังคับ) โลโก้บริษัท แนะนำพื้นใส
        output/          วิดีโอที่ได้ จะถูกสร้างอัตโนมัติ
"""
import json
import os
import re
import shutil
import subprocess
import sys
import hashlib
import unicodedata
import zlib

import cleanup
import grade

FPS = 30
HERE = os.path.dirname(os.path.abspath(__file__))

# ฟอนต์: ใช้ Kanit ที่เก็บไว้ในโปรเจกต์ (fonts/) → ได้ผลเหมือนกันทุกเครื่องทั้ง Mac และ Windows
# ถ้าไม่มี จะใช้ฟอนต์ไทยของระบบแทน: (ตัวปกติ, ตัวหนา) — ตัวหนา None = ทำตัวหนาด้วยเส้นขอบ
FONT_CANDIDATES = [
    (os.path.join(HERE, "fonts", "Kanit-Regular.ttf"), os.path.join(HERE, "fonts", "Kanit-Bold.ttf")),
    ("C:/Windows/Fonts/LeelawUI.ttf", "C:/Windows/Fonts/LeelaUIb.ttf"),          # Windows
    ("/System/Library/Fonts/Supplemental/SukhumvitSet.ttc", None),                # macOS
]


def find_fonts():
    for regular, bold in FONT_CANDIDATES:
        if os.path.exists(regular):
            return regular, (bold if bold and os.path.exists(bold) else None)
    sys.exit("ไม่พบฟอนต์ภาษาไทย — วาง Kanit-Regular.ttf และ Kanit-Bold.ttf ไว้ในโฟลเดอร์ fonts/")


FONT, FONT_BOLD = find_fonts()


def _ffmpeg_version():
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        sys.exit("ไม่พบ ffmpeg — ติดตั้งก่อน (Mac: brew install ffmpeg / Windows: winget install Gyan.FFmpeg)")
    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (99, 0)  # รุ่น git/nightly ถือว่าใหม่


def filter_script_args(script):
    """ส่งไฟล์ฟิลเตอร์ให้ ffmpeg: รุ่น 7.1+ ใช้ -/filter_complex, รุ่นเก่ากว่าใช้ -filter_complex_script"""
    if FFMPEG_VERSION >= (7, 1):
        return ["-/filter_complex", script]
    return ["-filter_complex_script", script]


FFMPEG_VERSION = _ffmpeg_version()


def ff_path(path):
    """path สำหรับใส่ในฟิลเตอร์ ffmpeg: ใช้ / และ escape ':' (เช่น C:/ ของ Windows)"""
    return os.path.abspath(path).replace("\\", "/").replace(":", "\\:")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic")

FORMATS = {
    "vertical": (1080, 1920),
    "horizontal": (1920, 1080),
}

# ค่าเริ่มต้นของแต่ละสไตล์ (ค่าใน config.json จะทับค่าเหล่านี้)
THEMES = {
    "luxury": {
        "accent_color": "0xD4AF37",
        "text": "white", "sub": "white@0.85",
        "box": None, "price_box": None, "caption_box": None,
        "caption_color": "accent", "price_color": "accent",
        "bold": False, "gradient": True, "separator": True,
        "transition": "fade", "transition_seconds": 1.0, "seconds_per_image": 4.0,
        "transitions": ["fade", "smoothup", "dissolve"],
        "zoom": 0.10,
        "outro_eq": "brightness=-0.45:saturation=0.5",
        "outro_text": "white", "outro_price": "accent",
        "size_scale": 1.0,
    },
    "modern": {
        "accent_color": "0xE63946",
        "text": "white", "sub": "white",
        "box": "black@0.72", "price_box": "accent@0.95", "caption_box": "accent@0.95",
        "caption_color": "white", "price_color": "white",
        "bold": True, "gradient": False, "separator": False,
        "transition": "slideleft", "transition_seconds": 0.45, "seconds_per_image": 2.8,
        "transitions": ["slideleft", "slideup", "zoomin", "smoothleft"],
        "zoom": 0.22,
        "outro_eq": "brightness=-0.30:saturation=0.8",
        "outro_text": "white", "outro_price": "white",
        "outro_price_box": "accent@0.95",
        "size_scale": 1.08,
    },
    "minimal": {
        "accent_color": "0x2B2B2B",
        "text": "0x222222", "sub": "0x555555",
        "box": "white@0.88", "price_box": "white@0.95", "caption_box": "white@0.88",
        "caption_color": "0x222222", "price_color": "0x111111",
        "bold": False, "gradient": False, "separator": True,
        "transition": "fade", "transition_seconds": 0.8, "seconds_per_image": 3.5,
        "transitions": ["fade", "smoothup", "dissolve"],
        "zoom": 0.12,
        "outro_eq": "brightness=0.28:saturation=0.25:contrast=0.7",
        "outro_text": "0x222222", "outro_price": "0x111111",
        "size_scale": 0.95,
        "light": True, "shadow": False, "panel": "0xF7F5F2",
    },
    # ป้ายเซล: เหลือง-ดำ ตัวใหญ่ ราคาเด่น จังหวะเร็ว — ทรัพย์ราคาถูก / โปรโมชัน
    "bold": {
        "accent_color": "0xFFD400",
        "text": "white", "sub": "white",
        "box": "black@0.85", "price_box": "accent@1.0", "caption_box": "accent@1.0",
        "caption_color": "0x111111", "price_color": "0x111111",
        "bold": True, "gradient": False, "separator": False,
        "transition": "zoomin", "transition_seconds": 0.35, "seconds_per_image": 2.5,
        "transitions": ["zoomin", "slideleft", "slideup", "circleopen"],
        "zoom": 0.25,
        "outro_eq": "brightness=-0.42:saturation=0.6",
        "outro_text": "white", "outro_price": "0x111111", "outro_price_box": "accent@1.0",
        "size_scale": 1.12, "panel": "0x111111",
    },
    # ธรรมชาติ: เขียว-ครีม นุ่ม เฟดช้า — บ้านเดี่ยว บ้านสวน ที่ดิน
    "nature": {
        "accent_color": "0x5B7B4A",
        "text": "0x2F3A2A", "sub": "0x5E6B55",
        "box": "0xF3EFE3@0.9", "price_box": "accent@0.95", "caption_box": "0xF3EFE3@0.92",
        "caption_color": "accent", "price_color": "white",
        "bold": False, "gradient": False, "separator": True,
        "transition": "fade", "transition_seconds": 1.0, "seconds_per_image": 4.0,
        "transitions": ["fade", "smoothleft", "dissolve"],
        "zoom": 0.08,
        "outro_eq": "brightness=0.22:saturation=0.45:contrast=0.75",
        "outro_text": "0x2F3A2A", "outro_price": "white", "outro_price_box": "accent@0.95",
        "size_scale": 1.0,
        "light": True, "shadow": False, "panel": "0xF3EFE3",
    },
    # ทางการ: น้ำเงินกรมท่า-ขาว เรียบ — อาคารพาณิชย์ ออฟฟิศ โกดัง
    "corporate": {
        "accent_color": "0x1F3A68",
        "text": "white", "sub": "white@0.9",
        "box": "0x14213D@0.88", "price_box": "white@0.96", "caption_box": "accent@0.95",
        "caption_color": "white", "price_color": "0x14213D",
        "bold": True, "gradient": False, "separator": False,
        "transition": "wipeleft", "transition_seconds": 0.6, "seconds_per_image": 3.2,
        "transitions": ["wipeleft", "wipeup", "slideleft"],
        "zoom": 0.10,
        "outro_eq": "brightness=-0.42:saturation=0.4",
        "outro_text": "white", "outro_price": "0x14213D", "outro_price_box": "white@0.96",
        "size_scale": 1.0, "panel": "0x14213D",
    },
    # หรูกลางคืน: โทนมืด ตัวอักษรขาว สีฟ้าเรืองแสง — คอนโดหรู เพนท์เฮาส์
    "night": {
        "accent_color": "0x7FDBFF",
        "text": "white", "sub": "white@0.8",
        "box": None, "price_box": None, "caption_box": None,
        "caption_color": "accent", "price_color": "accent",
        "bold": False, "gradient": True, "separator": True,
        "transition": "fadeblack", "transition_seconds": 0.8, "seconds_per_image": 3.8,
        "transitions": ["fadeblack", "smoothup", "fade"],
        "zoom": 0.12,
        "outro_eq": "brightness=-0.58:saturation=0.3",
        "outro_text": "white", "outro_price": "accent",
        "size_scale": 1.0, "panel": "0x050505",
        "glow": True,
        "gradient_strength": {"top_alpha": "E8", "top_h": 0.42, "bottom_alpha": "F0", "bottom_h": 0.52},
    },
}
DEFAULT_STYLE = "luxury"

# การเคลื่อนกล้องแบบ Ken Burns วนใช้ทีละรูป
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]

LOGO_POSITIONS = ("top-right", "top-left", "bottom-right", "bottom-left")

# แบบจัดวางของวิดีโอ (ค่าใน config ทับได้ ไม่ระบุ = เลือกจากรหัสโปรเจกต์ → โปรเจกต์เดิมได้แบบเดิมเสมอ)
#   video_layout  classic = ชื่อบน ราคาล่าง / lower = ข้อความชิดซ้ายล่าง + แถบสี / band = แถบชื่อด้านบน
#   intro         overlay = ชื่อทับรูปแรก / card = การ์ดชื่อโครงการเต็มจอก่อนเข้ารูป
#   outro         center = รูปเบลอ + ข้อมูลกลางจอ / split = ครึ่งรูป ครึ่งข้อมูลติดต่อ
VIDEO_LAYOUTS = ("classic", "lower", "band")
INTRO_STYLES = ("overlay", "card")
OUTRO_STYLES = ("center", "split")
INTRO_CARD_SECONDS = 2.4


def variant(cfg, key, options):
    """ค่าใน config ถ้ามี (และไม่ใช่ "auto") ไม่งั้นเลือกจากชื่อโปรเจกต์แบบคงที่"""
    val = cfg.get(key)
    if val not in (None, "auto"):
        if val not in options:
            sys.exit(f"{key} ต้องเป็น: {', '.join(options)} หรือ auto")
        return val
    return options[zlib.crc32(f"{key}:{cfg.get('_name', '')}".encode("utf-8")) % len(options)]


# ---------------------------------------------------------------- ภาพเคลื่อนไหว (motion.py)
# ใช้ได้เมื่อมี .venv (ติดตั้งตาม README) — ไม่มี = ใช้การซูม/แพนของ ffmpeg แบบเดิม
# ตั้งต่อรูปใน config ได้: "motion" (push/pull/pan_left/pan_right/rise), "focus" [x, y] 0..1,
# "effects" ["water", "sky"] ([] = ปิด), "sweep" true/false, "parallax" 0..2, "with" "08.jpg" (แบ่งจอ 2 รูป)
# ปิดทั้งหมดด้วย "animate": false
MOTION_TYPES = ("push", "pull", "pan_left", "pan_right", "rise")
MOTION_VERSION = 3


def venv_python():
    for p in (os.path.join(HERE, ".venv", "bin", "python"), os.path.join(HERE, ".venv", "Scripts", "python.exe")):
        if os.path.exists(p):
            return p
    return None


def analysis_dir(cache_dir, src):
    """โฟลเดอร์ผลวิเคราะห์ (ความลึก/ฟ้า/น้ำ) ของรูป ผูกกับไฟล์ต้นฉบับ + ค่าตัดขอบ/ลบลายน้ำ
    (วิดีโอใช้รูปที่ขยายแล้ว สตอรี่บอร์ดใช้รูปเดิม — ทั้งคู่จึงหาผลเดียวกันเจอ)"""
    path, spec = src
    st = os.stat(path)
    key = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}|{spec}|v1".encode()).hexdigest()[:10]
    return os.path.join(cache_dir, f"{os.path.splitext(os.path.basename(path))[0]}-{key}")


def analysis_targets(cfg):
    """[(img, ชื่อคีย์, รูปที่ใช้จริง, โฟลเดอร์ผลวิเคราะห์)] ของทุกรูป รวมรูปแบ่งจอ"""
    out = []
    for img in cfg["_images"]:
        out.append((img, "anim", img["path"], analysis_dir(cfg["_motion_cache"], img["src"])))
        if img.get("with_path"):
            out.append((img, "with_anim", img["with_path"], analysis_dir(cfg["_motion_cache"], img["with_src"])))
    return out


def load_analysis(cfg):
    """อ่านผลวิเคราะห์ที่มีอยู่แล้วใน cache (ไม่ต้องใช้ .venv) → img["anim"]"""
    for img, key, _, d in analysis_targets(cfg):
        info = os.path.join(d, "info.json")
        if os.path.exists(info):
            with open(info, encoding="utf-8") as f:
                img[key] = dict(json.load(f), dir=d)


def scene_plan(cfg, img, i):
    """การเคลื่อนไหวของฉาก: ค่าใน config ก่อน ไม่งั้นเลือกจากผลวิเคราะห์รูป"""
    a = img.get("anim") or {}
    sky, water = a.get("sky_frac", 0), a.get("water_frac", 0)
    motion = img.get("motion")
    if motion in (None, "auto"):
        if i == 0:
            motion = "push"                                   # ฉากเปิด: ซูมเข้าหาตัวทรัพย์
        elif water > 0.05:
            motion = "pan_right" if i % 2 else "pan_left"     # สระ/ทะเล: เลื่อนข้างให้เห็นน้ำกระเพื่อม
        elif sky > 0.12:
            motion = "rise"                                   # ภายนอกเห็นฟ้า: เงยกล้องขึ้น
        else:
            motion = ("pan_right", "push", "pan_left", "pull")[i % 4]
    elif motion not in MOTION_TYPES:
        sys.exit(f"motion ต้องเป็น: {', '.join(MOTION_TYPES)} หรือ auto")
    effects = img.get("effects")
    if effects is None:
        effects = [e for e, ok in (("water", water > 0.03), ("sky", sky > 0.08)) if ok]
    return {
        "motion": motion,
        "focus": img.get("focus") or a.get("focus") or [0.5, 0.5],
        "effects": list(effects),
        "sweep": bool(img.get("sweep", i == 0)),
        "parallax": float(img.get("parallax", 1.0)) if a.get("depth") else 0.0,
        "with": img.get("with_path"),
    }


def panel_color(th):
    """สีพื้นของแถบข้อมูล (โปสต์ / ฉากปิดแบบ split / แถบชื่อ)"""
    return th.get("panel") or ("0xF7F5F2" if th.get("light") else "0x141414")


# ---------------------------------------------------------------- helpers

def even(n):
    n = int(round(n))
    return n - (n % 2)


def probe_size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("\n")[0].split(",")[:2]
    return int(w), int(h)


def visual_len(text):
    """จำนวนตัวอักษรที่กินพื้นที่แนวนอน (ไม่นับสระบน/ล่างและวรรณยุกต์)"""
    return sum(1 for c in text if unicodedata.category(c) != "Mn")


def fit_fontsize(text, base, max_width, minimum=28):
    est = visual_len(text) * 0.56 * base  # ความกว้างเฉลี่ยต่อตัวอักษรของ Kanit ≈ 0.56 เท่าของขนาดฟอนต์
    if est <= max_width:
        return base
    return max(minimum, int(base * max_width / est))


def zoompan_expr(motion, frames, zoom):
    p = f"(on/{frames - 1})"
    zp = 1 + zoom * 0.85
    if motion == "zoom_in":
        return f"z='1+{zoom}*{p}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if motion == "zoom_out":
        return f"z='{1 + zoom}-{zoom}*{p}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if motion == "pan_right":
        return f"z='{zp:.3f}':x='(iw-iw/zoom)*{p}':y='ih/2-(ih/zoom/2)'"
    return f"z='{zp:.3f}':x='(iw-iw/zoom)*(1-{p})':y='ih/2-(ih/zoom/2)'"


def fade_alpha(a, b, f=0.4):
    return (f"if(lt(t,{a:.2f}),0,if(lt(t,{a + f:.2f}),(t-{a:.2f})/{f},"
            f"if(lt(t,{b - f:.2f}),1,if(lt(t,{b:.2f}),({b:.2f}-t)/{f},0))))")


class TextLayer:
    def __init__(self, tmpdir, theme):
        self.tmpdir = tmpdir
        self.theme = theme
        self.count = 0
        self.filters = []

    def color(self, c):
        """แปลงคำว่า accent เป็นสีหลักของสไตล์"""
        if c and c.startswith("accent"):
            return self.theme["accent_color"] + c[len("accent"):]
        return c

    def add(self, text, size, x, y, start, end, color=None, box=None, bold=None):
        if not text or end <= start:
            return
        color = self.color(color or self.theme["text"])
        box = self.color(box)
        bold = self.theme["bold"] if bold is None else bold
        self.count += 1
        path = os.path.join(self.tmpdir, f"text_{self.count}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        opts = [
            f"fontfile='{ff_path(FONT_BOLD if bold and FONT_BOLD else FONT)}'",
            f"textfile='{ff_path(path)}'",
            "expansion=none",
            f"fontsize={size}",
            f"fontcolor={color}",
            f"x={x}",
            # ข้อความลอยขึ้นเข้าที่ตอนปรากฏ (รูปนิ่ง/โปสต์ start < 0 ไม่ขยับ)
            f"y='{y}+{max(8, int(size * 0.5))}*pow(max(0,1-(t-{start:.2f})/0.45),3)'" if start >= 0 and
            self.theme.get("text_motion", True) else f"y={y}",
            f"alpha='{fade_alpha(start, end)}'",
            f"enable='between(t,{start:.2f},{end:.2f})'",
        ]
        if self.theme.get("glow") and color.startswith(self.theme["accent_color"]):
            # เรืองแสง: ขอบสีเดียวกับตัวอักษรแบบโปร่ง
            opts.append(f"borderw={max(2, size // 22)}:bordercolor={self.theme['accent_color']}@0.35")
        elif self.theme.get("shadow", True) and (not box or not box.startswith("white")):
            opts.append("shadowcolor=black@0.55:shadowx=2:shadowy=2")
        if bold and not FONT_BOLD:  # ไม่มีไฟล์ตัวหนา → ใช้เส้นขอบสีเดียวกันทำให้หนาขึ้นแทน
            opts.append(f"borderw={max(1, size // 28)}:bordercolor={color}")
        if box:
            opts.append(f"box=1:boxcolor={box}:boxborderw={max(14, int(size * 0.38))}")
        self.filters.append("drawtext=" + ":".join(opts))

    def line(self, x, y, w, h, start, end, color="accent"):
        """เส้นตกแต่ง (drawbox)"""
        self.filters.append(
            f"drawbox=x={x}:y={y}:w={w}:h={h}:color={self.color(color)}:t=fill:"
            f"enable='between(t,{start:.2f},{end:.2f})'")


# ---------------------------------------------------------------- core

BRAND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand")


def load_brand():
    """ค่าประจำบริษัท (โลโก้, สี) จาก brand/brand.json ใช้กับทุกโปรเจกต์"""
    p = os.path.join(BRAND_DIR, "brand.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_project(project_dir, style_override=None, upscale_images=True):
    project_dir = os.path.abspath(project_dir)
    cfg_path = os.path.join(project_dir, "config.json")
    if not os.path.exists(cfg_path):
        sys.exit(f"ไม่พบ {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    style = style_override or cfg.get("style") or DEFAULT_STYLE
    if style not in THEMES:
        sys.exit(f"ไม่รู้จักสไตล์ {style} (ใช้ได้: {', '.join(THEMES)})")
    theme = dict(THEMES[style])
    brand = load_brand()

    def accent_from(val):  # สีหลักกำหนดได้เป็นค่าเดียว หรือแยกตามสไตล์ {"luxury": "0x..."}
        if isinstance(val, dict):
            return val.get(style)
        return val

    for src in (brand, cfg):
        acc = accent_from(src.get("accent_color"))
        if acc:
            theme["accent_color"] = acc
    for key in ("transition", "transition_seconds", "seconds_per_image"):
        if cfg.get(key) is not None:
            theme[key] = cfg[key]
    cfg["_style"] = style
    cfg["_theme"] = theme
    cfg["_name"] = os.path.basename(project_dir)

    img_dir = cfg.get("image_dir") or os.path.join(project_dir, "images")
    if not os.path.isabs(img_dir):
        img_dir = os.path.join(project_dir, img_dir)
    if cfg.get("images"):
        items = [it if isinstance(it, dict) else {"file": it} for it in cfg["images"]]
    else:
        files = sorted(f for f in os.listdir(img_dir) if f.lower().endswith(IMAGE_EXT))
        items = [{"file": f} for f in files]
    images = []
    for it in items:
        p = os.path.join(img_dir, it["file"])
        if not os.path.exists(p):
            sys.exit(f"ไม่พบรูป {p}")
        # ลบลายน้ำ/ตัดขอบตาม "remove" / "crop" ของรูปนี้ (ถ้ามี) — ทำก่อนขยายด้วย AI
        p = cleanup.clean(p, it, os.path.join(project_dir, "cache", "cleaned"))
        # "file" = ชื่อไฟล์เดิม (path อาจเปลี่ยนเป็นไฟล์ใน cache หลังลบลายน้ำ/ขยายรูปด้วย AI)
        entry = {"path": p, "file": it["file"], "caption": it.get("caption", ""),
                 "src": (os.path.join(img_dir, it["file"]),
                         json.dumps({"crop": it.get("crop"), "remove": it.get("remove")}, sort_keys=True))}
        for k in ("motion", "focus", "effects", "sweep", "parallax", "grade"):
            if k in it:
                entry[k] = it[k]
        if it.get("with"):  # แบ่งจอ: รูปที่สองในฉากเดียวกัน
            wp = os.path.join(img_dir, it["with"])
            if not os.path.exists(wp):
                sys.exit(f"ไม่พบรูป {wp}")
            entry["with_path"] = cleanup.clean(wp, {}, os.path.join(project_dir, "cache", "cleaned"))
            entry["with_src"] = (wp, json.dumps({"crop": None, "remove": None}, sort_keys=True))
        images.append(entry)
    if not images:
        sys.exit(f"ไม่มีรูปในโฟลเดอร์ {img_dir}")

    def optional(name):
        val = cfg.get(name)
        if val is None:
            for ext in ([".mp3", ".m4a", ".wav", ".aac"] if name == "music" else [".png", ".jpg"]):
                p = os.path.join(project_dir, name + ext)
                if os.path.exists(p):
                    return p
            return None
        if not val:
            return None
        p = val if os.path.isabs(val) else os.path.join(project_dir, val)
        return p if os.path.exists(p) else None

    # ขยายรูปเล็กด้วย AI ให้คมขึ้น (ปิดได้ด้วย "ai_upscale": false)
    if upscale_images and cfg.get("ai_upscale", True):
        import upscale
        if upscale.available():
            for img in images:
                img["path"] = upscale.upscale(img["path"], cache_dir=os.path.join(project_dir, "cache", "upscaled"))
                if img.get("with_path"):
                    img["with_path"] = upscale.upscale(img["with_path"], cache_dir=os.path.join(project_dir, "cache", "upscaled"))
        else:
            print(f"  ! ข้ามการขยายรูปด้วย AI: {upscale.status()}")

    # แต่งโทนสีทั้งชุดให้เข้ากัน + โทนประจำสไตล์ ("grade": false = ปิด, "match" = เฉพาะปรับให้เข้าชุด)
    grade_mode = cfg.get("grade", True)
    if grade_mode not in (True, False, "all", "match"):
        sys.exit('grade ต้องเป็น true / false / "match"')
    grade.grade_images(images, style, grade_mode, os.path.join(project_dir, "cache", "graded"))

    cfg["_images"] = images
    cfg["_motion_cache"] = os.path.join(project_dir, "cache", "motion")
    load_analysis(cfg)
    cfg["_music"] = optional("music")
    # ไม่ได้กำหนดเพลง → ใช้เพลงประจำสไตล์จาก brand/music/<สไตล์>.mp3 (ตั้ง "music": false เพื่อปิด)
    if not cfg["_music"] and cfg.get("music") is None:
        p = os.path.join(BRAND_DIR, "music", f"{style}.mp3")
        cfg["_music"] = p if os.path.exists(p) else None

    # เสียงพากย์จากบท "narration" ของแต่ละรูป + "outro_narration" (ปิดได้ด้วย "voiceover": false)
    has_script = any(it.get("narration") for it in items) or cfg.get("outro_narration")
    if has_script and cfg.get("voiceover", True):
        import voice
        if voice.available():
            vdir = os.path.join(project_dir, "cache", "voice")
            for it, img in zip(items, images):
                img["narration"] = it.get("narration", "")
                if img["narration"]:
                    img["voice"], img["voice_dur"] = voice.synth(img["narration"], vdir, cfg.get("voice"))
            if cfg.get("outro_narration"):
                cfg["_outro_voice"], cfg["_outro_voice_dur"] = voice.synth(cfg["outro_narration"], vdir, cfg.get("voice"))
        else:
            print("  ! ข้ามเสียงพากย์: ไม่พบคำสั่ง say (ใช้ได้เฉพาะ macOS)")
    cfg["_logo"] = optional("logo")
    # ไม่มีโลโก้ในโปรเจกต์ → ใช้โลโก้บริษัทจาก brand/ (ตั้ง "logo": false เพื่อไม่ใส่โลโก้)
    if not cfg["_logo"] and cfg.get("logo") is None and brand.get("logo"):
        p = os.path.join(BRAND_DIR, brand["logo"])
        cfg["_logo"] = p if os.path.exists(p) else None
    if cfg["_logo"]:
        cfg["_logo_size"] = probe_size(cfg["_logo"])
    return cfg


def clip_mode(img, W, H, fill):
    """วิธีจัดภาพของแต่ละฉาก: 'pan' แพนตามความกว้าง / 'cover' ตัดเต็มจอ+ซูม / 'fit' วางกลาง+พื้นเบลอ"""
    iw, ih = img["size"]
    img_ar, out_ar = iw / ih, W / H
    mismatch = img_ar / out_ar > 1.35 or out_ar / img_ar > 1.35
    if mismatch and fill and img_ar > out_ar:
        return "pan"
    if mismatch and not fill:
        return "fit"
    return "cover"


def build_clip(src, img, W, H, frames, motion, zoom, out_label, fill=True, idx=0):
    """ฟิลเตอร์สำหรับรูปหนึ่งรูป → คลิปขนาด WxH ยาว frames เฟรม"""
    iw, ih = img["size"]
    img_ar, out_ar = iw / ih, W / H
    zp = zoompan_expr(motion, frames, zoom)
    tail = f"fps={FPS},setsar=1,format=yuv420p"

    mode = clip_mode(img, W, H, fill)
    if mode == "pan":
        # เติมเต็มจอ: ขยายรูปให้สูงเต็มจอ แล้วเลื่อนกล้องแพนไปตามความกว้างของรูป (สลับซ้าย↔ขวา)
        sw = even(2 * H * img_ar)
        rng = sw - 2 * W
        ease = f"(1-cos(PI*n/{frames - 1}))/2"
        prog = ease if idx % 2 == 0 else f"(1-{ease})"
        return (f"[{src}]scale={sw}:{2 * H}:flags=lanczos,loop=loop={frames - 1}:size=1,setpts=N/{FPS}/TB,"
                f"crop=w={2 * W}:h={2 * H}:x='{rng}*(0.15+0.7*{prog})':y=0,"
                f"scale={W}:{H}:flags=lanczos,{tail}[{out_label}]")
    # 'cover': ตัดให้เต็มจอแล้วซูม / 'fit': วางรูปเต็มกลางจอ + พื้นหลังเบลอ (เช่น รูปแนวตั้งในวิดีโอแนวนอน)
    if mode == "cover":
        return (f"[{src}]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={W * 2}:{H * 2},zoompan={zp}:d={frames}:s={W}x{H}:fps={FPS},"
                f"{tail}[{out_label}]")

    if img_ar > out_ar:  # รูปกว้างกว่าจอ → เต็มความกว้าง
        fw, fh = W, even(W / img_ar)
    else:
        fh, fw = H, even(H * img_ar)
    t = out_label
    return (
        f"[{src}]split=2[bg{t}][fg{t}];"
        f"[bg{t}]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,"
        f"crop={W // 4}:{H // 4},gblur=sigma=12,scale={W}:{H},eq=brightness=-0.18:saturation=0.9,"
        f"loop=loop={frames - 1}:size=1,setpts=N/{FPS}/TB[bgl{t}];"
        f"[fg{t}]scale={fw * 2}:{fh * 2}:flags=lanczos,zoompan={zp}:d={frames}:s={fw}x{fh}:fps={FPS}[fgz{t}];"
        f"[bgl{t}][fgz{t}]overlay=(W-w)/2:(H-h)/2:shortest=1,{tail}[{out_label}]"
    )


VO_LEAD = 0.3        # เสียงพากย์เริ่มหลังฉากเริ่มกี่วินาที
VO_TAIL = 0.35       # เว้นท้ายหลังพูดจบ ก่อนเริ่มเปลี่ยนภาพ
OUTRO_VO_LEAD = 0.5  # เสียงพากย์ฉากปิดเริ่มหลังฉากปิดเริ่ม


def timeline(cfg, fmt):
    """เวลาของแต่ละช่วงในวิดีโอ — ใช้ร่วมกันระหว่าง render() และสตอรี่บอร์ด"""
    W, H = FORMATS[fmt]
    vertical = H > W
    th = cfg["_theme"]
    images = cfg["_images"]
    n = len(images)
    D = float(th["seconds_per_image"])
    T = float(th["transition_seconds"])
    D_OUT = float(cfg.get("outro_seconds", 4.5))
    # ความยาวแต่ละฉาก: อย่างน้อยเท่าค่าของสไตล์ และยาวพอให้เสียงพากย์ของฉากนั้นพูดจบก่อนเปลี่ยนภาพ
    durs = [max(D, img.get("voice_dur", 0) + VO_LEAD + VO_TAIL + T) if img.get("voice") else D for img in images]
    # แบบจัดวาง: ตำแหน่งข้อความใช้ได้เฉพาะแนวตั้ง / ฉากปิดแบบ split ใช้เฉพาะแนวตั้ง
    layout = variant(cfg, "video_layout", VIDEO_LAYOUTS) if vertical else "classic"
    intro = variant(cfg, "intro", INTRO_STYLES)
    outro = variant(cfg, "outro", OUTRO_STYLES) if vertical else "center"
    intro_dur = INTRO_CARD_SECONDS if intro == "card" else 0.0
    starts = [intro_dur - T if intro_dur else 0.0]
    for d in durs:
        starts.append(starts[-1] + d - T)
    outro_start = starts[n]
    if cfg.get("_outro_voice"):
        D_OUT = max(D_OUT, cfg["_outro_voice_dur"] + OUTRO_VO_LEAD + 1.2)
    intro_end = starts[1] if n > 1 else outro_start
    return {
        "W": W, "H": H, "vertical": vertical, "n": n,
        "D": D, "T": T, "D_OUT": D_OUT, "step": D - T,
        "durs": durs, "starts": starts,
        "outro_start": outro_start, "total": outro_start + D_OUT,
        "intro_end": intro_end,
        "detail_start": intro_end + 0.1 if n > 1 else starts[0] + 0.8,
        "layout": layout, "intro": intro, "outro": outro, "intro_dur": intro_dur,
        "text_start": starts[0],  # ข้อความบนรูปเริ่มเมื่อรูปแรกขึ้น (หลังการ์ดเปิด ถ้ามี)
        # แนวตั้ง: เติมภาพเต็มจอเสมอ (ปิดได้ด้วย "vertical_fill": false) / แนวนอน: รูปแนวตั้งวางกลาง + พื้นเบลอ
        "fill": bool(cfg.get("vertical_fill", True)) if vertical else bool(cfg.get("horizontal_fill", False)),
        "transition": th["transition"],
        # การเปลี่ยนภาพแต่ละรอยต่อ: ตั้ง "transition" ใน config = ใช้แบบเดียว / ไม่ตั้ง = สลับในชุดของสไตล์
        "transitions": [cfg["transition"]] * max(0, n - 1) if cfg.get("transition")
        else [th.get("transitions", [th["transition"]])[(k - 1) % len(th.get("transitions", [th["transition"]]))]
              for k in range(1, n)],
        "plans": [scene_plan(cfg, img, i) for i, img in enumerate(images)],
        "animate": bool(cfg.get("animate", True)) and venv_python() is not None,
    }


def render(cfg, fmt, out_path, tmpdir):
    tm = timeline(cfg, fmt)
    W, H, vertical = tm["W"], tm["H"], tm["vertical"]
    th = cfg["_theme"]
    images = cfg["_images"]
    n = tm["n"]
    D, T, D_OUT = tm["D"], tm["T"], tm["D_OUT"]
    durs, starts = tm["durs"], tm["starts"]
    frames_out = int(round(D_OUT * FPS))
    outro_start, total = tm["outro_start"], tm["total"]

    args = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error", "-stats"]
    clips = cfg.get("_clips")  # ภาพเคลื่อนไหวจาก motion.py (ถ้ามี)
    for i, img in enumerate(images):
        args += ["-i", clips[i] if clips and clips[i] else img["path"]]
    args += ["-i", images[-1]["path"]]  # รูปนิ่งของฉากปิด (input ลำดับ n)
    card = tm["intro"] == "card"
    if card:  # การ์ดเปิด: รูปแรกอีกชุด (input ลำดับ n+1) ทำเป็นพื้นเบลอ
        args += ["-i", images[0]["path"]]
    parts = []
    fill = tm["fill"]
    # ffmpeg อย่างเดียว: แปลงชื่อการเคลื่อนไหวเป็นการซูม/แพนเดิม
    FALLBACK = {"push": "zoom_in", "pull": "zoom_out", "pan_left": "pan_left", "pan_right": "pan_right", "rise": "zoom_in"}

    for i, img in enumerate(images):
        frames = int(round(durs[i] * FPS))
        if clips and clips[i]:
            parts.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={FPS},setsar=1,format=yuv420p,"
                         f"trim=end_frame={frames}[c{i}]")
        else:
            parts.append(build_clip(f"{i}:v", img, W, H, frames, FALLBACK[tm["plans"][i]["motion"]],
                                    th["zoom"], f"c{i}", fill=fill, idx=i))

    def blurred(src, frames, label):
        """รูปเบลอ + ปรับแสงตามสไตล์ ยาว frames เฟรม (พื้นของการ์ดเปิด / ฉากปิด)"""
        return (f"[{src}]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
                f"gblur=sigma=10,scale={W}:{H},eq={th['outro_eq']},"
                f"loop=loop={frames - 1}:size=1,setpts=N/{FPS}/TB,fps={FPS},setsar=1,format=yuv420p[{label}]")

    # ฉากปิด: center = รูปสุดท้ายเบลอ + ข้อมูลกลางจอ / split = รูปครึ่งบน + แถบข้อมูลครึ่งล่าง
    half = even(H / 2)
    if tm["outro"] == "split":
        parts.append(f"[{n}:v]scale={W}:{half}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{half},"
                     f"loop=loop={frames_out - 1}:size=1,setpts=N/{FPS}/TB,fps={FPS},setsar=1,format=yuv420p[otop]")
        parts.append(f"color=c={panel_color(th)}:s={W}x{H - half}:r={FPS}:d={frames_out / FPS:.3f},"
                     f"format=yuv420p[obot]")
        parts.append(f"[otop][obot]vstack=inputs=2,setsar=1[c{n}]")
    else:
        parts.append(blurred(f"{n}:v", frames_out, f"c{n}"))

    # ต่อคลิปด้วย xfade (การ์ดเปิด / ฉากปิดใช้ fade เสมอ)
    prev = "c0"
    if card:
        parts.append(blurred(f"{n + 1}:v", int(round(tm["intro_dur"] * FPS)), "cin"))
        parts.append(f"[cin][c0]xfade=transition=fade:duration={T}:offset={starts[0]:.3f}[x0]")
        prev = "x0"
    for k in range(1, n + 1):
        tr = tm["transitions"][k - 1] if k < n else "fade"
        parts.append(f"[{prev}][c{k}]xfade=transition={tr}:duration={T}:offset={starts[k]:.3f}[x{k}]")
        prev = f"x{k}"
    video = prev
    input_idx = n + 1 + (1 if card else 0)

    # เงาไล่สีด้านบน/ล่าง ให้ข้อความอ่านง่ายโดยไม่ต้องมีกล่อง
    if th["gradient"]:
        # ความเข้ม/ความสูงของเงาไล่สีปรับได้ต่อสไตล์ (night เข้มกว่า luxury)
        g = th.get("gradient_strength", {})
        bottom = even(H * g.get("bottom_h", 0.45 if vertical else 0.55))
        top = even(H * g.get("top_h", 0.30))
        ba, ta = g.get("bottom_alpha", "D0"), g.get("top_alpha", "A0")
        args += ["-f", "lavfi", "-i",
                 f"gradients=s={W}x{bottom}:c0=0x000000{ba}:c1=0x00000000:x0=0:y0={bottom}:x1=0:y1=0:n=2:speed=0:d={total:.2f}:r={FPS}",
                 "-f", "lavfi", "-i",
                 f"gradients=s={W}x{top}:c0=0x000000{ta}:c1=0x00000000:x0=0:y0=0:x1=0:y1={top}:n=2:speed=0:d={total:.2f}:r={FPS}"]
        parts.append(f"[{video}][{input_idx}:v]overlay=0:H-h:enable='lt(t,{outro_start + 0.5:.2f})'[vg1]")
        parts.append(f"[vg1][{input_idx + 1}:v]overlay=0:0:enable='lt(t,{outro_start + 0.5:.2f})'[vg2]")
        video = "vg2"
        input_idx += 2

    # แถบชื่อด้านบน (band) วาดก่อนโลโก้ เพื่อให้โลโก้อยู่บนแถบ
    band_h = int(H * 0.2)
    if tm["layout"] == "band":
        parts.append(f"[{video}]drawbox=x=0:y=0:w={W}:h={band_h}:color={panel_color(th)}@0.9:t=fill:"
                     f"enable='between(t,{tm['text_start']:.2f},{outro_start:.2f})'[vband]")
        video = "vband"

    # โลโก้
    logo_big_h = 0
    if cfg["_logo"]:
        lw_, lh_ = cfg["_logo_size"]
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", cfg["_logo"]]
        pos = cfg.get("logo_position", "top-right")
        if pos not in LOGO_POSITIONS:
            sys.exit(f"logo_position ต้องเป็น: {', '.join(LOGO_POSITIONS)}")
        squareish = lw_ / lh_ < 1.6  # โลโก้ทรงกลม/สี่เหลี่ยมจัตุรัส ใช้ขนาดเล็กลง
        default_size = (0.17 if vertical else 0.085) if squareish else (0.22 if vertical else 0.12)
        size = float(cfg.get("logo_size") or default_size)
        lw = even(W * size)
        m = int(W * 0.04)
        x = f"W-w-{m}" if pos.endswith("right") else str(m)
        # มุมล่างในแนวตั้งชนกับข้อความ จึงยกขึ้นเหนือพื้นที่ข้อความ
        y = str(m) if pos.startswith("top") else (f"H-h-{int(H * 0.06)}" if not vertical else f"H-h-{int(H * 0.27)}")
        corner_end = outro_start + 0.3
        logo_outro = cfg.get("logo_outro", True)
        outs = ["lg1"] + (["lg2"] if logo_outro else []) + (["lg3"] if card else [])
        parts.append(f"[{input_idx}:v]format=rgba,split={len(outs)}" + "".join(f"[{o}]" for o in outs))
        parts.append(f"[lg1]scale={lw}:-1,colorchannelmixer=aa={float(cfg.get('logo_opacity', 0.92))}[logo]")
        parts.append(f"[{video}][logo]overlay={x}:{y}:enable='between(t,{tm['text_start']:.2f},{corner_end:.2f})'[vlogo]")
        video = "vlogo"
        bw = W * (0.42 if vertical else 0.22)
        max_h = H * (0.17 if vertical else 0.20)
        if bw * lh_ / lw_ > max_h:
            bw = max_h * lw_ / lh_
        bw = even(bw)
        big_h = int(bw * lh_ / lw_)
        if card:  # โลโก้ใหญ่บนการ์ดเปิด เฟดออกพร้อมการเปลี่ยนเข้ารูปแรก
            cy = int(H * (0.20 if vertical else 0.12))
            parts.append(f"[lg3]scale={bw}:-1,fade=t=in:st=0.1:d=0.5:alpha=1,"
                         f"fade=t=out:st={starts[0]:.2f}:d={T:.2f}:alpha=1[logocard]")
            parts.append(f"[{video}][logocard]overlay=(W-w)/2:{cy}:enable='lt(t,{starts[0] + T:.2f})'[vlogo1]")
            video = "vlogo1"
        if logo_outro:
            logo_big_h = big_h
            # split: โลโก้คร่อมรอยต่อระหว่างรูปกับแถบข้อมูล
            by = half - big_h // 2 if tm["outro"] == "split" else int(H * (0.10 if vertical else 0.07))
            parts.append(f"[lg2]scale={bw}:-1,fade=t=in:st={outro_start + 0.2:.2f}:d=0.6:alpha=1[logobig]")
            parts.append(f"[{video}][logobig]overlay=(W-w)/2:{by}:enable='gte(t,{outro_start:.2f})'[vlogo2]")
            video = "vlogo2"
        input_idx += 1

    # ข้อความ
    tl = TextLayer(tmpdir, th)
    title = cfg.get("title", "")
    location = cfg.get("location", "")
    price = cfg.get("price", "")
    details = "  |  ".join(cfg.get("details", []))
    contact = cfg.get("contact", {}) or {}
    s = min(W, H) / 1080 * th["size_scale"]
    max_w = W * 0.86
    intro_end, detail_start = tm["intro_end"], tm["detail_start"]
    box, pbox, cbox = th["box"], th["price_box"], th["caption_box"]
    pcol, ccol = th["price_color"], th["caption_color"]

    t0 = tm["text_start"]
    layout = tm["layout"]
    light = th.get("light", False)
    cx = "(w-text_w)/2"
    if vertical and layout == "classic":  # ชื่อบนกลางจอ ราคาล่าง
        tl.add(title, fit_fontsize(title, int(70 * s), max_w), cx, 268, t0 + 0.3, intro_end, box=box)
        tl.add(location, fit_fontsize(location, int(44 * s), max_w), cx, 383, t0 + 0.6, intro_end,
               color=th["sub"], box=box, bold=False)
        if th["separator"]:
            tl.line(W // 2 - 60, 463, 120, 3, t0 + 0.8, intro_end)
        tl.add(price, fit_fontsize(price, int(88 * s), max_w), cx, H - 430, t0 + 0.6, outro_start, color=pcol, box=pbox)
        tl.add(details, fit_fontsize(details, int(44 * s), max_w), cx, H - 300, detail_start, outro_start,
               color=th["sub"], box=box, bold=False)
        for i, img in enumerate(images):
            st = starts[i] + (0.3 if i else 0.5)
            tl.add(img["caption"], int(42 * s), cx, H - 560 if i else 518, st, starts[i + 1],
                   color=ccol, box=cbox)
    elif vertical and layout == "lower":  # ข้อความทั้งหมดชิดซ้ายล่าง + แถบสีแนวตั้ง
        x0 = int(W * 0.085)
        lw_max = W - x0 - int(W * 0.06)
        tl.line(x0 - int(W * 0.035), H - 660, max(6, int(8 * s)), 420, t0 + 0.3, outro_start)
        tl.add(title, fit_fontsize(title, int(70 * s), lw_max), x0, H - 650, t0 + 0.3, intro_end, box=box)
        tl.add(location, fit_fontsize(location, int(42 * s), lw_max), x0, H - 545, t0 + 0.6, intro_end,
               color=th["sub"], box=box, bold=False)
        tl.add(price, fit_fontsize(price, int(84 * s), lw_max), x0, H - 430, t0 + 0.6, outro_start, color=pcol, box=pbox)
        tl.add(details, fit_fontsize(details, int(40 * s), lw_max), x0, H - 300, detail_start, outro_start,
               color=th["sub"], box=box, bold=False)
        for i, img in enumerate(images):  # ฉากแรกป้ายอยู่บน (ล่างมีชื่อแล้ว) ฉากต่อไปใช้ที่ของชื่อ
            st = starts[i] + (0.3 if i else 0.5)
            tl.add(img["caption"], fit_fontsize(img["caption"], int(42 * s), lw_max), x0, H - 650 if i else 268,
                   st, starts[i + 1], color=ccol, box=cbox)
    elif vertical:  # band: แถบชื่อโครงการด้านบนตลอดวิดีโอ
        bh = band_h
        x0 = int(W * 0.055)
        logo_room = (even(W * float(cfg.get("logo_size") or 0.17)) + int(W * 0.07)) if cfg["_logo"] else x0
        bmax = W - x0 - logo_room
        tl.line(0, bh - 8, W, 8, t0, outro_start)
        band_text, band_sub = (th["outro_text"], th["sub"]) if light else ("white", "white@0.8")
        ft = fit_fontsize(title, int(64 * s), bmax)
        fl = fit_fontsize(location, int(38 * s), bmax)
        block = int(ft * 1.3) + (12 + int(fl * 1.3) if location else 0)
        ty = (bh - 8 - block) // 2
        tl.add(title, ft, x0, ty, t0 + 0.3, outro_start, color=band_text)
        tl.add(location, fl, x0, ty + int(ft * 1.3) + 12, t0 + 0.5, outro_start, color=band_sub, bold=False)
        lmax = W - 2 * x0
        tl.add(price, fit_fontsize(price, int(84 * s), lmax), x0, H - 430, t0 + 0.6, outro_start, color=pcol, box=pbox)
        tl.add(details, fit_fontsize(details, int(40 * s), lmax), x0, H - 300, t0 + 0.8, outro_start,
               color=th["sub"], box=box, bold=False)
        for i, img in enumerate(images):
            tl.add(img["caption"], fit_fontsize(img["caption"], int(42 * s), lmax), x0, H - 560,
                   starts[i] + 0.4, starts[i + 1], color=ccol, box=cbox)
    else:
        x0 = int(80 * s)
        tl.add(title, fit_fontsize(title, int(68 * s), max_w), x0, H - 385, t0 + 0.3, intro_end, box=box)
        tl.add(location, fit_fontsize(location, int(40 * s), max_w), x0, H - 268, t0 + 0.6, intro_end,
               color=th["sub"], box=box, bold=False)
        tl.add(price, fit_fontsize(price, int(64 * s), W * 0.5), x0, H - 160, t0 + 0.6, outro_start, color=pcol, box=pbox)
        tl.add(details, fit_fontsize(details, int(40 * s), max_w), x0, H - 268, detail_start, outro_start,
               color=th["sub"], box=box, bold=False)
        if th["separator"] and not pbox:
            tl.line(x0, H - 185, 90, 3, t0 + 0.8, outro_start)
        for i, img in enumerate(images):
            st = starts[i] + 0.3
            tl.add(img["caption"], int(40 * s), x0, int(70 * s), st, starts[i + 1], color=ccol, box=cbox)

    ot, op = th["outro_text"], th["outro_price"]
    opbox = th.get("outro_price_box")

    # การ์ดเปิด: ชื่อ ทำเล ราคา กลางจอ (ใต้โลโก้ใหญ่)
    if card:
        ca, cb = 0.3, starts[0] + T * 0.6
        fct = fit_fontsize(title, int(72 * s), W * 0.86)
        y = int(H * 0.45)
        tl.add(title, fct, cx, y, ca, cb, color=ot)
        y += int(fct * 1.45)
        if location:
            fcl = fit_fontsize(location, int(44 * s), W * 0.86)
            tl.add(location, fcl, cx, y, ca + 0.2, cb, color=ot, bold=False)
            y += int(fcl * 1.5)
        if th["separator"]:
            tl.line(W // 2 - 70, y + int(10 * s), 140, 3, ca + 0.3, cb, color="accent" if ot == "white" else "0x222222")
            y += int(40 * s)
        fcp = fit_fontsize(price, int(80 * s), W * 0.86)
        tl.add(price, fcp, cx, y + (int(fcp * 0.38) if opbox else 0) + int(10 * s), ca + 0.4, cb, color=op, box=opbox)

    # ฉากปิด
    a, b = outro_start + 0.3, total
    name = contact.get("name", "")
    phone = contact.get("phone", "")
    phone_txt = ("โทร " + phone) if phone else ""
    line = contact.get("line", "")
    line_txt = ("LINE: " + line) if line else ""
    if tm["outro"] == "split":  # ข้อมูลเรียงในครึ่งล่าง ใต้โลโก้ที่คร่อมรอยต่อ
        y = half + (logo_big_h // 2 + int(40 * s) if logo_big_h else int(70 * s))
        ft = fit_fontsize(title, int(62 * s), W * 0.86)
        tl.add(title, ft, cx, y, a, b, color=ot)
        y += int(ft * 1.35) + int(24 * s)
        fp = fit_fontsize(price, int(84 * s), W * 0.86)
        bp = int(fp * 0.38) if opbox else 0
        tl.add(price, fp, cx, y + bp, a + 0.2, b, color=op, box=opbox)
        y += fp + 2 * bp + int(34 * s)
        fn = fit_fontsize(name, int(46 * s), W * 0.86)
        tl.add(name, fn, cx, y, a + 0.4, b, color=ot, bold=False)
        y += int(fn * 1.4) + int(10 * s)
        fph = fit_fontsize(phone_txt, int(62 * s), W * 0.86)
        tl.add(phone_txt, fph, cx, y, a + 0.5, b, color=ot)
        y += int(fph * 1.4)
        tl.add(line_txt, fit_fontsize(line_txt, int(46 * s), W * 0.86), cx, y, a + 0.6, b, color=ot, bold=False)
    else:  # center: เลื่อนข้อความลงถ้ามีโลโก้ใหญ่
        if vertical:
            ys = [0.30, 0.40, 0.55, 0.63, 0.72] if logo_big_h else [0.27, 0.37, 0.52, 0.60, 0.69]
        else:
            ys = [0.32, 0.43, 0.59, 0.68, 0.78] if logo_big_h else [0.20, 0.33, 0.52, 0.62, 0.73]
        tl.add(title, fit_fontsize(title, int(62 * s), W * 0.86), cx, int(H * ys[0]), a, b, color=ot)
        tl.add(price, fit_fontsize(price, int(84 * s), W * 0.86), cx, int(H * ys[1]), a + 0.2, b, color=op, box=opbox)
        if th["separator"]:
            sep_y = int(H * (ys[1] + ys[2]) / 2) + int(30 * s)
            tl.line(W // 2 - 70, sep_y, 140, 3, a + 0.3, b, color="accent" if th["outro_text"] == "white" else "0x222222")
        tl.add(name, fit_fontsize(name, int(46 * s), W * 0.86), cx, int(H * ys[2]), a + 0.4, b, color=ot, bold=False)
        tl.add(phone_txt, fit_fontsize(phone_txt, int(62 * s), W * 0.86), cx, int(H * ys[3]), a + 0.5, b, color=ot)
        tl.add(line_txt, fit_fontsize(line_txt, int(46 * s), W * 0.86), cx, int(H * ys[4]), a + 0.6, b, color=ot, bold=False)

    if tl.filters:
        parts.append(f"[{video}]" + ",".join(tl.filters) + "[vtxt]")
        video = "vtxt"
    parts.append(f"[{video}]fade=t=in:st=0:d=0.5,fade=t=out:st={total - 0.8:.2f}:d=0.8[vout]")

    # เสียง
    # เสียงพากย์: วางแต่ละท่อนตามเวลาเริ่มของฉาก แล้วรวมเป็นแทร็กเดียว
    vo = [(img["voice"], starts[i] + VO_LEAD) for i, img in enumerate(images) if img.get("voice")]
    if cfg.get("_outro_voice"):
        vo.append((cfg["_outro_voice"], outro_start + OUTRO_VO_LEAD))
    voice_label = None
    if vo:
        labels = []
        for k, (path, at) in enumerate(vo):
            args += ["-i", path]
            ms = int(at * 1000)
            parts.append(f"[{input_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                         f"adelay={ms}|{ms},apad=whole_dur={total:.2f}[vo{k}]")
            labels.append(f"[vo{k}]")
            input_idx += 1
        parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,"
                     f"atrim=0:{total:.2f}[voice]")
        voice_label = "voice"

    if cfg["_music"]:
        args += ["-stream_loop", "-1", "-i", cfg["_music"]]
        vol = float(cfg.get("music_volume", 0.8 if not voice_label else 0.55))
        parts.append(f"[{input_idx}:a]atrim=0:{total:.2f},asetpts=N/SR/TB,"
                     f"aformat=sample_rates=44100:channel_layouts=stereo,volume={vol},"
                     f"afade=t=in:st=0:d=1,afade=t=out:st={total - 2:.2f}:d=2[music]")
        if voice_label:
            # ลดเสียงเพลงลงอัตโนมัติตอนมีเสียงพูด (ducking)
            parts.append("[voice]asplit=2[vkey][vmix]")
            parts.append("[music][vkey]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450[duck]")
            parts.append("[duck][vmix]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[aout]")
        else:
            parts.append("[music]anull[aout]")
    elif voice_label:
        parts.append("[voice]alimiter=limit=0.95[aout]")
    else:
        args += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        parts.append(f"[{input_idx}:a]anull[aout]")

    script = os.path.join(tmpdir, f"filter_{fmt}.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(parts))

    args += filter_script_args(script) + ["-map", "[vout]", "-map", "[aout]",
             "-t", f"{total:.2f}", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path]
    print(f"▶ กำลังสร้าง {fmt} สไตล์ {cfg['_style']} ({W}x{H}, {total:.1f} วินาที, {n} รูป) "
          f"แบบ {tm['layout']} / เปิด {tm['intro']} / ปิด {tm['outro']} ...")
    subprocess.run(args, check=True)
    print(f"✓ เสร็จแล้ว: {out_path}")


def animate(cfg, fmt, tmpdir):
    """สร้างคลิปภาพเคลื่อนไหวของทุกฉากด้วย motion.py (.venv) คืนรายการไฟล์ หรือ None ถ้าใช้ไม่ได้"""
    py = venv_python()
    if not cfg.get("animate", True):
        return None
    if not py:
        print("  ! ไม่มี .venv → ใช้การซูม/แพนแบบเดิม (ติดตั้งภาพเคลื่อนไหวตาม README)")
        return None
    script = os.path.join(HERE, "motion.py")
    pairs = [f"{d}::{path}" for _, _, path, d in analysis_targets(cfg)]
    subprocess.run([py, script, "analyze"] + pairs, check=True)
    load_analysis(cfg)
    tm = timeline(cfg, fmt)
    W, H = tm["W"], tm["H"]
    clip_dir = os.path.join(os.path.dirname(cfg["_motion_cache"]), "clips")
    os.makedirs(clip_dir, exist_ok=True)
    jobs, outs = [], []
    th = cfg["_theme"]
    for i, img in enumerate(cfg["_images"]):
        plan = tm["plans"][i]
        if not plan["with"] and clip_mode(img, W, H, tm["fill"]) == "fit":
            outs.append(None)  # รูปแนวตั้งในวิดีโอแนวนอน: วางกลาง + พื้นเบลอ แบบเดิม (ffmpeg)
            continue

        def pane(path, anim, pl, phase=0.0):
            return {"image": path, "analysis": (anim or {}).get("dir"), "motion": pl["motion"],
                    "focus": pl["focus"], "zoom": th["zoom"] * 1.2, "parallax": pl["parallax"],
                    "water": "water" in pl["effects"], "sky": "sky" in pl["effects"],
                    "sweep": pl["sweep"], "phase": phase}
        panes = [pane(img["path"], img.get("anim"), plan)]
        if plan["with"]:
            wa = img.get("with_anim") or {}
            panes.append(pane(plan["with"], wa, {
                "motion": "pan_left" if plan["motion"] != "pan_left" else "pan_right",
                "focus": wa.get("focus") or [0.5, 0.5], "parallax": plan["parallax"] if wa.get("depth") else 0.0,
                "effects": [e for e, ok in (("water", wa.get("water_frac", 0) > 0.03),
                                            ("sky", wa.get("sky_frac", 0) > 0.08)) if ok],
                "sweep": False}, phase=1.3))
        job = {"W": W, "H": H, "fps": FPS, "frames": int(round(tm["durs"][i] * FPS)), "panes": panes,
               "split": ("v" if tm["vertical"] else "h") if plan["with"] else None,
               "accent": th["accent_color"], "bg": panel_color(th), "delay": tm["T"] if i else 0.0,
               "v": MOTION_VERSION}
        key = hashlib.sha1(json.dumps(job, sort_keys=True).encode()).hexdigest()[:16]
        job["out"] = os.path.join(clip_dir, f"{key}.mp4")
        jobs.append(job)
        outs.append(job["out"])
    jobs_path = os.path.join(tmpdir, f"motion_{fmt}.json")
    with open(jobs_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f)
    if jobs:
        subprocess.run([py, script, "render", jobs_path], check=True)
    return outs


def make(project_dir, style=None, fmts=None, skip_existing=False):
    """สร้างวิดีโอของโปรเจกต์ คืนค่ารายการไฟล์ที่ได้"""
    project_dir = os.path.abspath(project_dir)
    cfg = load_project(project_dir, style)
    out_dir = os.path.join(project_dir, "output")
    name = cfg.get("output_name") or os.path.basename(project_dir)
    fmts = fmts or cfg.get("formats") or list(FORMATS)
    for fmt in fmts:
        if fmt not in FORMATS:
            raise ValueError(f"ไม่รู้จักรูปแบบ {fmt} (ใช้ได้: {', '.join(FORMATS)})")
    jobs = [(fmt, os.path.join(out_dir, f"{name}_{cfg['_style']}_{fmt}.mp4")) for fmt in fmts]
    if skip_existing:
        jobs = [(f, p) for f, p in jobs if not os.path.exists(p)]
    if not jobs:
        return []
    for img in cfg["_images"]:
        img["size"] = probe_size(img["path"])
    tmpdir = os.path.join(out_dir, ".tmp")
    os.makedirs(tmpdir, exist_ok=True)
    try:
        for fmt, path in jobs:
            cfg["_clips"] = animate(cfg, fmt, tmpdir)
            render(cfg, fmt, path, tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return [p for _, p in jobs]


def main():
    if hasattr(sys.stdout, "reconfigure"):  # คอนโซล Windows บางแบบพิมพ์สัญลักษณ์ ✓ ✗ ไม่ได้
        sys.stdout.reconfigure(errors="replace")
    argv = sys.argv[1:]
    style = None
    if "--style" in argv:
        i = argv.index("--style")
        if i + 1 >= len(argv):
            sys.exit("--style ต้องตามด้วย " + " / ".join(THEMES))
        style = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        sys.exit(1)
    try:
        make(argv[0], style, argv[1:] or None)
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
