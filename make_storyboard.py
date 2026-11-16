#!/usr/bin/env python3
"""
สร้างสตอรี่บอร์ด (Markdown + รูปย่อแต่ละฉาก) จาก config.json เดียวกับวิดีโอ
ใช้ตรวจลำดับฉาก ข้อความ และเวลา ก่อน render วิดีโอจริง

วิธีใช้:
    python3 make_storyboard.py projects/<ชื่อโปรเจกต์> [--style luxury|modern|minimal] [vertical|horizontal]

ผลลัพธ์:
    projects/<ชื่อ>/output/<ชื่อ>_<สไตล์>_<ขนาด>_storyboard.md
    projects/<ชื่อ>/output/storyboard/<สไตล์>_<ขนาด>/sceneNN.jpg   (รูปย่อ)

สตอรี่บอร์ดสร้างจาก config.json — ถ้าจะแก้ ให้แก้ config.json แล้วสร้างใหม่
(เวลาและการจัดภาพคำนวณด้วยฟังก์ชันเดียวกับ make_video.py จึงตรงกับวิดีโอจริง)
"""
import os
import subprocess
import sys

import make_video as mv

THUMB_W = {"vertical": 270, "horizontal": 400}

FORMAT_NAMES = {"vertical": "แนวตั้ง", "horizontal": "แนวนอน"}
STYLE_NAMES = {"luxury": "หรูหรา", "modern": "ทันสมัย", "minimal": "มินิมอล"}
MOTION_NAMES = {
    "zoom_in": "ซูมเข้าช้า ๆ",
    "zoom_out": "ซูมออกช้า ๆ",
    "pan_right": "เลื่อนไปทางขวา",
    "pan_left": "เลื่อนไปทางซ้าย",
}
TRANSITION_NAMES = {
    "fade": "เฟด",
    "slideleft": "สไลด์ไปซ้าย",
    "slideright": "สไลด์ไปขวา",
    "wipeleft": "ปาดไปซ้าย",
    "dissolve": "ละลาย",
}


def camera_text(img, idx, tm):
    mode = mv.clip_mode(img, tm["W"], tm["H"], tm["fill"])
    motion = mv.MOTIONS[idx % len(mv.MOTIONS)]
    if mode == "pan":
        direction = "ซ้าย → ขวา" if idx % 2 == 0 else "ขวา → ซ้าย"
        return f"แพนตามความกว้างรูป ({direction})"
    if mode == "fit":
        return f"วางรูปกลางจอ + พื้นหลังเบลอ, {MOTION_NAMES[motion]}"
    return MOTION_NAMES[motion]


def make_thumb(img, idx, tm, out_path, outro=False):
    """รูปย่อของฉาก: ตัดตามสัดส่วนจอแบบเดียวกับวิดีโอ (ฉากแพน/วางกลาง ใช้ภาพกลางรูป)"""
    W, H = tm["W"], tm["H"]
    tw = THUMB_W["vertical" if tm["vertical"] else "horizontal"]
    th_ = mv.even(tw * H / W)
    mode = mv.clip_mode(img, W, H, tm["fill"])
    if outro:
        vf = (f"scale={tw}:{th_}:force_original_aspect_ratio=increase,crop={tw}:{th_},"
              f"gblur=sigma=6,eq=brightness=-0.35:saturation=0.6")
    elif mode == "fit":
        vf = (f"split[a][b];[a]scale={tw}:{th_}:force_original_aspect_ratio=increase,crop={tw}:{th_},"
              f"gblur=sigma=6,eq=brightness=-0.18[bg];[b]scale={tw}:{th_}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    else:
        vf = f"scale={tw}:{th_}:force_original_aspect_ratio=increase,crop={tw}:{th_}"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", img["path"],
                    "-filter_complex", vf, "-frames:v", "1", "-q:v", "3", out_path], check=True)


def t(sec):
    return f"{sec:.1f}"


def narr_cell(text, dur):
    """ช่องเสียงพากย์: บท + ความยาวเสียง"""
    if not text:
        return "—"
    return f"🔊 {cell(text)}" + (f"<br>({dur:.1f} วิ)" if dur else "")


def cell(text):
    """ข้อความในตาราง Markdown: กัน | และขึ้นบรรทัดใหม่"""
    return text.replace("|", "\\|").replace("\n", "<br>")


def build_markdown(cfg, fmt, name, thumb_rel, thumb_dir):
    tm = mv.timeline(cfg, fmt)
    th = cfg["_theme"]
    images = cfg["_images"]
    title = cfg.get("title", "")
    location = cfg.get("location", "")
    price = cfg.get("price", "")
    details = " | ".join(cfg.get("details", []))
    contact = cfg.get("contact", {}) or {}
    style = cfg["_style"]
    tr = TRANSITION_NAMES.get(tm["transition"], tm["transition"])
    has_vo = any(img.get("voice") for img in images) or bool(cfg.get("_outro_voice"))
    has_script = any(img.get("narration") for img in images) or bool(cfg.get("outro_narration"))
    if has_vo:
        v = cfg.get("voice") or {}
        vo_line = f"มี — เสียง {v.get('name', 'Kanya')} (macOS) ความเร็ว {v.get('rate', 200)}"
    elif has_script:
        vo_line = "มีบท แต่ยังสร้างเสียงไม่ได้ (ไม่มีคำสั่ง say / ปิดด้วย voiceover: false)"
    else:
        vo_line = "ไม่มี — ใส่บทได้ที่ `images[].narration` และ `outro_narration`"

    lines = [
        f"# สตอรี่บอร์ด — {title}",
        "",
        "| | |",
        "|---|---|",
        f"| ขนาด | {FORMAT_NAMES[fmt]} {tm['W']}×{tm['H']} |",
        f"| สไตล์ | {STYLE_NAMES.get(style, style)} (`{style}`) |",
        f"| ความยาวรวม | **{t(tm['total'])} วินาที** ({tm['n']} ฉากรูป + ฉากปิด {t(tm['D_OUT'])} วินาที) |",
        f"| ต่อฉาก | อย่างน้อย {tm['D']:g} วินาที (ยาวขึ้นตามเสียงพากย์), เปลี่ยนภาพแบบ{tr} {tm['T']:g} วินาที |",
        f"| เพลง | {os.path.basename(cfg['_music']) if cfg['_music'] else 'ไม่มี (แทร็กเงียบ)'}"
        f"{' (เบาลงอัตโนมัติตอนมีเสียงพากย์)' if cfg['_music'] and has_vo else ''} |",
        f"| เสียงพากย์ | {vo_line} |",
        f"| โลโก้ | {'มุมขวาบนตลอดวิดีโอ + โลโก้ใหญ่ในฉากปิด' if cfg['_logo'] else 'ไม่มี'} |",
        "",
        "## ข้อความที่แสดงตลอดวิดีโอ",
        "",
        "| ข้อความ | ช่วงเวลา (วินาที) |",
        "|---|---|",
    ]
    if title:
        lines.append(f"| ชื่อโครงการ: {cell(title)} | {t(0.3)} – {t(tm['intro_end'])} |")
    if location:
        lines.append(f"| ทำเล: {cell(location)} | {t(0.6)} – {t(tm['intro_end'])} |")
    if price:
        lines.append(f"| ราคา: **{cell(price)}** | {t(0.6)} – {t(tm['outro_start'])} |")
    if details:
        lines.append(f"| รายละเอียด: {cell(details)} | {t(tm['detail_start'])} – {t(tm['outro_start'])} |")

    lines += [
        "",
        "## ฉาก",
        "",
        "| ฉาก | ภาพ | เวลา (วินาที) | รูป / กล้อง | ข้อความบนจอ | เสียงพากย์ |",
        "|---|---|---|---|---|---|",
    ]
    for i, img in enumerate(images):
        thumb = f"scene{i + 1:02d}.jpg"
        make_thumb(img, i, tm, os.path.join(thumb_dir, thumb))
        start, end = tm["starts"][i], tm["starts"][i] + tm["durs"][i]
        texts = []
        if i == 0 and title:
            texts.append(f"**{title}**")
        if i == 0 and location:
            texts.append(location)
        if img.get("caption"):
            texts.append(f"ป้าย: {img['caption']}")
        src = img.get("file", os.path.basename(img["path"]))
        cam = camera_text(img, i, tm)
        nxt = f"<br>→ {tr}" if i < len(images) - 1 else "<br>→ เฟดเข้าฉากปิด"
        lines.append(
            f"| {i + 1} | ![ฉาก {i + 1}]({thumb_rel}/{thumb}) | {t(start)} – {t(end)} | "
            f"`{cell(src)}`<br>{cam}{nxt} | {cell('<br>'.join(texts)) if texts else '—'} | "
            f"{narr_cell(img.get('narration'), img.get('voice_dur'))} |")

    # ฉากปิด
    outro_texts = [t_ for t_ in [
        "โลโก้ใหญ่" if cfg["_logo"] else "",
        f"**{title}**" if title else "",
        f"**{price}**" if price else "",
        contact.get("name", ""),
        f"โทร {contact['phone']}" if contact.get("phone") else "",
        f"LINE: {contact['line']}" if contact.get("line") else "",
    ] if t_]
    make_thumb(images[-1], len(images) - 1, tm, os.path.join(thumb_dir, "outro.jpg"), outro=True)
    lines.append(
        f"| ปิด | ![ฉากปิด]({thumb_rel}/outro.jpg) | {t(tm['outro_start'])} – {t(tm['total'])} | "
        f"รูปสุดท้ายแบบเบลอ + มืดลง<br>เฟดดำตอนจบ | {cell('<br>'.join(outro_texts))} | "
        f"{narr_cell(cfg.get('outro_narration'), cfg.get('_outro_voice_dur'))} |")

    lines += [
        "",
        "## แก้ไขสตอรี่บอร์ด",
        "",
        "แก้ใน `config.json` แล้วสร้างสตอรี่บอร์ดใหม่:",
        "",
        "| ต้องการ | แก้ที่ |",
        "|---|---|",
        "| เปลี่ยนลำดับ / ตัดรูป | `images` (เรียงตามลำดับฉาก) |",
        "| ข้อความป้ายของแต่ละฉาก | `images[].caption` |",
        "| บทพากย์ของแต่ละฉาก / ฉากปิด | `images[].narration`, `outro_narration` (ฉากยาวขึ้นเองตามเสียง) |",
        "| ความเร็ว / ปิดเสียงพากย์ | `voice.rate` / `\"voiceover\": false` |",
        "| เพลง | `music` (ไฟล์ หรือ `false`) — ไม่ระบุ = เพลงประจำสไตล์ใน `brand/music/` |",
        "| ชื่อ / ทำเล / ราคา / รายละเอียด | `title`, `location`, `price`, `details` |",
        "| ความยาวต่อฉาก / การเปลี่ยนภาพ | `seconds_per_image`, `transition`, `transition_seconds` |",
        "| ความยาวฉากปิด / ข้อมูลติดต่อ | `outro_seconds`, `contact` |",
        "",
        f"สร้างวิดีโอจริงตามสตอรี่บอร์ดนี้: `python3 make_video.py <โฟลเดอร์โปรเจกต์> --style {style} {fmt}`",
        "",
    ]
    return "\n".join(lines)


def make(project_dir, style=None, fmt="vertical", skip_existing=False):
    """สร้างสตอรี่บอร์ดของโปรเจกต์ คืนค่า path ของไฟล์ .md (หรือ None ถ้าข้าม)"""
    if fmt not in mv.FORMATS:
        raise ValueError(f"ขนาดต้องเป็น: {', '.join(mv.FORMATS)}")
    project_dir = os.path.abspath(project_dir)
    # สตอรี่บอร์ดใช้แค่รูปย่อ ไม่ต้องขยายรูปด้วย AI
    cfg = mv.load_project(project_dir, style, upscale_images=False)
    for img in cfg["_images"]:
        img["size"] = mv.probe_size(img["path"])
    out_dir = os.path.join(project_dir, "output")
    name = cfg.get("output_name") or os.path.basename(project_dir)
    md_path = os.path.join(out_dir, f"{name}_{cfg['_style']}_{fmt}_storyboard.md")
    if skip_existing and os.path.exists(md_path):
        return None
    thumb_rel = f"storyboard/{cfg['_style']}_{fmt}"
    thumb_dir = os.path.join(out_dir, thumb_rel)
    os.makedirs(thumb_dir, exist_ok=True)
    md = build_markdown(cfg, fmt, name, thumb_rel, thumb_dir)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✓ สตอรี่บอร์ด: {md_path}")
    return md_path


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    argv = sys.argv[1:]
    style = None
    if "--style" in argv:
        i = argv.index("--style")
        if i + 1 >= len(argv):
            sys.exit("--style ต้องมีค่า")
        style = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        sys.exit(1)
    fmts = argv[1:] or ["vertical"]
    try:
        for fmt in fmts:
            make(argv[0], style, fmt)
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
