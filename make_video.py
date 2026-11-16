#!/usr/bin/env python3
"""
สร้างวิดีโออสังหาฯ จากรูปภาพ (แนวตั้ง 9:16 และแนวนอน 16:9)

วิธีใช้:
    python3 make_video.py projects/<ชื่อโปรเจกต์> [--style luxury|modern|minimal] [vertical] [horizontal]

สไตล์:
    luxury   หรูหรา   — ดำ-ทอง ไม่มีกล่องข้อความ เงาไล่สี เคลื่อนไหวช้า
    modern   ทันสมัย  — แถบสีสด ตัวหนา เปลี่ยนภาพแบบสไลด์ จังหวะเร็ว
    minimal  มินิมอล  — กล่องขาว ตัวอักษรเข้ม สะอาดตา

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
import unicodedata

import cleanup

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
        "zoom": 0.12,
        "outro_eq": "brightness=0.28:saturation=0.25:contrast=0.7",
        "outro_text": "0x222222", "outro_price": "0x111111",
        "size_scale": 0.95,
    },
}
DEFAULT_STYLE = "luxury"

# การเคลื่อนกล้องแบบ Ken Burns วนใช้ทีละรูป
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]

LOGO_POSITIONS = ("top-right", "top-left", "bottom-right", "bottom-left")


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
            f"y={y}",
            f"alpha='{fade_alpha(start, end)}'",
            f"enable='between(t,{start:.2f},{end:.2f})'",
        ]
        if not box or not box.startswith("white"):
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
        images.append({"path": p, "file": it["file"], "caption": it.get("caption", "")})
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
        else:
            print(f"  ! ข้ามการขยายรูปด้วย AI: {upscale.status()}")

    cfg["_images"] = images
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
    starts = [0.0]
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
        "detail_start": intro_end + 0.1 if n > 1 else 0.8,
        # แนวตั้ง: เติมภาพเต็มจอเสมอ (ปิดได้ด้วย "vertical_fill": false) / แนวนอน: รูปแนวตั้งวางกลาง + พื้นเบลอ
        "fill": bool(cfg.get("vertical_fill", True)) if vertical else bool(cfg.get("horizontal_fill", False)),
        "transition": th["transition"],
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
    for img in images:
        args += ["-i", img["path"]]
    parts = []
    last = n - 1
    parts.append(f"[{last}:v]split=2[last_a][last_b]")
    fill = tm["fill"]

    for i, img in enumerate(images):
        src = "last_a" if i == last else f"{i}:v"
        parts.append(build_clip(src, img, W, H, int(round(durs[i] * FPS)), MOTIONS[i % len(MOTIONS)],
                                th["zoom"], f"c{i}", fill=fill, idx=i))

    # ฉากปิด: รูปสุดท้ายเบลอ + ข้อมูลติดต่อ
    parts.append(
        f"[last_b]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
        f"gblur=sigma=10,scale={W}:{H},eq={th['outro_eq']},"
        f"loop=loop={frames_out - 1}:size=1,setpts=N/{FPS}/TB,fps={FPS},setsar=1,format=yuv420p[c{n}]"
    )

    # ต่อคลิปด้วย xfade (ฉากปิดใช้ fade เสมอ)
    prev = "c0"
    for k in range(1, n + 1):
        tr = th["transition"] if k < n else "fade"
        parts.append(f"[{prev}][c{k}]xfade=transition={tr}:duration={T}:offset={starts[k]:.3f}[x{k}]")
        prev = f"x{k}"
    video = prev
    input_idx = n

    # เงาไล่สีด้านบน/ล่าง ให้ข้อความอ่านง่ายโดยไม่ต้องมีกล่อง
    if th["gradient"]:
        bottom = int(H * (0.45 if vertical else 0.55))
        top = int(H * (0.30 if vertical else 0.30))
        args += ["-f", "lavfi", "-i",
                 f"gradients=s={W}x{bottom}:c0=0x000000D0:c1=0x00000000:x0=0:y0={bottom}:x1=0:y1=0:n=2:speed=0:d={total:.2f}:r={FPS}",
                 "-f", "lavfi", "-i",
                 f"gradients=s={W}x{top}:c0=0x000000A0:c1=0x00000000:x0=0:y0=0:x1=0:y1={top}:n=2:speed=0:d={total:.2f}:r={FPS}"]
        parts.append(f"[{video}][{input_idx}:v]overlay=0:H-h:enable='lt(t,{outro_start + 0.5:.2f})'[vg1]")
        parts.append(f"[vg1][{input_idx + 1}:v]overlay=0:0:enable='lt(t,{outro_start + 0.5:.2f})'[vg2]")
        video = "vg2"
        input_idx += 2

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
        parts.append(f"[{input_idx}:v]format=rgba,split=2[lg1][lg2]")
        parts.append(f"[lg1]scale={lw}:-1,colorchannelmixer=aa={float(cfg.get('logo_opacity', 0.92))}[logo]")
        parts.append(f"[{video}][logo]overlay={x}:{y}:enable='lt(t,{corner_end:.2f})'[vlogo]")
        video = "vlogo"
        if cfg.get("logo_outro", True):
            bw = W * (0.42 if vertical else 0.22)
            max_h = H * (0.17 if vertical else 0.20)
            if bw * lh_ / lw_ > max_h:
                bw = max_h * lw_ / lh_
            bw = even(bw)
            logo_big_h = int(bw * lh_ / lw_)
            by = int(H * (0.10 if vertical else 0.07))
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

    if vertical:
        cx = "(w-text_w)/2"
        tl.add(title, fit_fontsize(title, int(70 * s), max_w), cx, 268, 0.3, intro_end, box=box)
        tl.add(location, fit_fontsize(location, int(44 * s), max_w), cx, 383, 0.6, intro_end,
               color=th["sub"], box=box, bold=False)
        if th["separator"]:
            tl.line(W // 2 - 60, 463, 120, 3, 0.8, intro_end)
        tl.add(price, fit_fontsize(price, int(88 * s), max_w), cx, H - 430, 0.6, outro_start, color=pcol, box=pbox)
        tl.add(details, fit_fontsize(details, int(44 * s), max_w), cx, H - 300, detail_start, outro_start,
               color=th["sub"], box=box, bold=False)
        for i, img in enumerate(images):
            st = starts[i] + (0.3 if i else 0.5)
            tl.add(img["caption"], int(42 * s), cx, H - 560 if i else 518, st, starts[i + 1],
                   color=ccol, box=cbox)
    else:
        x0 = int(80 * s)
        tl.add(title, fit_fontsize(title, int(68 * s), max_w), x0, H - 385, 0.3, intro_end, box=box)
        tl.add(location, fit_fontsize(location, int(40 * s), max_w), x0, H - 268, 0.6, intro_end,
               color=th["sub"], box=box, bold=False)
        tl.add(price, fit_fontsize(price, int(64 * s), W * 0.5), x0, H - 160, 0.6, outro_start, color=pcol, box=pbox)
        tl.add(details, fit_fontsize(details, int(40 * s), max_w), x0, H - 268, detail_start, outro_start,
               color=th["sub"], box=box, bold=False)
        if th["separator"] and not pbox:
            tl.line(x0, H - 185, 90, 3, 0.8, outro_start)
        for i, img in enumerate(images):
            st = starts[i] + 0.3
            tl.add(img["caption"], int(40 * s), x0, int(70 * s), st, starts[i + 1], color=ccol, box=cbox)

    # ฉากปิด (เลื่อนข้อความลงถ้ามีโลโก้ใหญ่)
    a, b = outro_start + 0.3, total
    cx = "(w-text_w)/2"
    if vertical:
        ys = [0.30, 0.40, 0.55, 0.63, 0.72] if logo_big_h else [0.27, 0.37, 0.52, 0.60, 0.69]
    else:
        ys = [0.32, 0.43, 0.59, 0.68, 0.78] if logo_big_h else [0.20, 0.33, 0.52, 0.62, 0.73]
    ot, op = th["outro_text"], th["outro_price"]
    opbox = th.get("outro_price_box")
    tl.add(title, fit_fontsize(title, int(62 * s), W * 0.86), cx, int(H * ys[0]), a, b, color=ot)
    tl.add(price, fit_fontsize(price, int(84 * s), W * 0.86), cx, int(H * ys[1]), a + 0.2, b, color=op, box=opbox)
    if th["separator"]:
        sep_y = int(H * (ys[1] + ys[2]) / 2) + int(30 * s)
        tl.line(W // 2 - 70, sep_y, 140, 3, a + 0.3, b, color="accent" if th["outro_text"] == "white" else "0x222222")
    name = contact.get("name", "")
    tl.add(name, fit_fontsize(name, int(46 * s), W * 0.86), cx, int(H * ys[2]), a + 0.4, b, color=ot, bold=False)
    phone = contact.get("phone", "")
    phone_txt = ("โทร " + phone) if phone else ""
    tl.add(phone_txt, fit_fontsize(phone_txt, int(62 * s), W * 0.86), cx, int(H * ys[3]), a + 0.5, b, color=ot)
    line = contact.get("line", "")
    line_txt = ("LINE: " + line) if line else ""
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
    print(f"▶ กำลังสร้าง {fmt} สไตล์ {cfg['_style']} ({W}x{H}, {total:.1f} วินาที, {n} รูป) ...")
    subprocess.run(args, check=True)
    print(f"✓ เสร็จแล้ว: {out_path}")


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
