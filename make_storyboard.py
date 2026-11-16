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
STYLE_NAMES = {"luxury": "หรูหรา", "modern": "ทันสมัย", "minimal": "มินิมอล",
               "bold": "ป้ายเซล", "nature": "ธรรมชาติ", "corporate": "ทางการ", "night": "หรูกลางคืน"}
MOTION_NAMES = {
    "push": "ซูมเข้าหาจุดโฟกัส",
    "pull": "ซูมออกจากจุดโฟกัส",
    "pan_right": "เลื่อนไปทางขวา",
    "pan_left": "เลื่อนไปทางซ้าย",
    "rise": "เงยกล้องขึ้น",
}
EFFECT_NAMES = {"water": "น้ำกระเพื่อม", "sky": "เมฆเลื่อน"}
TRANSITION_NAMES = {
    "fade": "เฟด",
    "slideleft": "สไลด์ไปซ้าย",
    "slideright": "สไลด์ไปขวา",
    "wipeleft": "ปาดไปซ้าย",
    "dissolve": "ละลาย",
    "zoomin": "ซูมเข้า",
    "fadeblack": "เฟดผ่านสีดำ",
    "slideup": "สไลด์ขึ้น",
    "smoothleft": "เลื่อนนุ่มไปซ้าย",
    "smoothup": "เลื่อนนุ่มขึ้น",
    "wipeup": "ปาดขึ้น",
    "circleopen": "วงกลมเปิด",
}


def camera_text(img, idx, tm):
    plan = tm["plans"][idx]
    if not tm["animate"]:  # ไม่มี .venv: ffmpeg ซูม/แพนแบบเดิม
        mode = mv.clip_mode(img, tm["W"], tm["H"], tm["fill"])
        if mode == "pan":
            direction = "ซ้าย → ขวา" if idx % 2 == 0 else "ขวา → ซ้าย"
            return f"แพนตามความกว้างรูป ({direction})"
        return MOTION_NAMES[plan["motion"]]
    parts = [MOTION_NAMES[plan["motion"]]]
    if plan["motion"] in ("push", "pull"):
        parts[0] += f" ({plan['focus'][0]:.2f}, {plan['focus'][1]:.2f})"
    if plan["parallax"] > 0:
        parts.append("ภาพมีมิติ 2.5D")
    parts += [EFFECT_NAMES[e] for e in plan["effects"] if e in EFFECT_NAMES]
    if plan["sweep"]:
        parts.append("แสงวิ่งผ่าน")
    if plan["with"]:
        parts.append(f"แบ่งจอกับ `{os.path.basename(plan['with'])}`")
    return ", ".join(parts)


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


LAYOUT_NAMES = {"classic": "ชื่อบน ราคาล่าง", "lower": "ชิดซ้ายล่าง + แถบสี", "band": "แถบชื่อด้านบน"}
INTRO_NAMES = {"overlay": "ชื่อทับรูปแรก", "card": "การ์ดชื่อโครงการ"}
OUTRO_NAMES = {"center": "ข้อมูลกลางจอ", "split": "ครึ่งรูป ครึ่งข้อมูล"}


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
    trs = list(dict.fromkeys(tm["transitions"])) or [tm["transition"]]
    tr = " / ".join(TRANSITION_NAMES.get(x, x) for x in trs)
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
        f"| ต่อฉาก | อย่างน้อย {tm['D']:g} วินาที (ยาวขึ้นตามเสียงพากย์), เปลี่ยนภาพแบบ {tr} {tm['T']:g} วินาที |",
        f"| ภาพเคลื่อนไหว | {'กล้องนุ่ม + 2.5D + เอฟเฟกต์ (motion.py)' if tm['animate'] else 'ซูม/แพน ffmpeg (ไม่มี .venv)'} |",
        f"| เพลง | {os.path.basename(cfg['_music']) if cfg['_music'] else 'ไม่มี (แทร็กเงียบ)'}"
        f"{' (เบาลงอัตโนมัติตอนมีเสียงพากย์)' if cfg['_music'] and has_vo else ''} |",
        f"| เสียงพากย์ | {vo_line} |",
        f"| โลโก้ | {'มุมขวาบนตลอดวิดีโอ + โลโก้ใหญ่ในฉากปิด' if cfg['_logo'] else 'ไม่มี'} |",
        f"| แบบจัดวาง | ข้อความ: {LAYOUT_NAMES[tm['layout']]} (`{tm['layout']}`) · "
        f"ฉากเปิด: {INTRO_NAMES[tm['intro']]} (`{tm['intro']}`) · ฉากปิด: {OUTRO_NAMES[tm['outro']]} (`{tm['outro']}`) |",
        "",
        "## ข้อความที่แสดงตลอดวิดีโอ",
        "",
        "| ข้อความ | ช่วงเวลา (วินาที) |",
        "|---|---|",
    ]
    t0 = tm["text_start"]
    title_end = tm["outro_start"] if tm["layout"] == "band" else tm["intro_end"]
    if title:
        lines.append(f"| ชื่อโครงการ: {cell(title)} | {t(t0 + 0.3)} – {t(title_end)} |")
    if location:
        lines.append(f"| ทำเล: {cell(location)} | {t(t0 + 0.6)} – {t(title_end)} |")
    if price:
        lines.append(f"| ราคา: **{cell(price)}** | {t(t0 + 0.6)} – {t(tm['outro_start'])} |")
    if details:
        lines.append(f"| รายละเอียด: {cell(details)} | {t(tm['detail_start'])} – {t(tm['outro_start'])} |")

    lines += [
        "",
        "## ฉาก",
        "",
        "| ฉาก | ภาพ | เวลา (วินาที) | รูป / กล้อง | ข้อความบนจอ | เสียงพากย์ |",
        "|---|---|---|---|---|---|",
    ]
    if tm["intro"] == "card":
        card_texts = [x for x in ["โลโก้ใหญ่" if cfg["_logo"] else "", f"**{title}**" if title else "",
                                  location, f"**{price}**" if price else ""] if x]
        lines.append(f"| เปิด | — | 0.0 – {t(tm['intro_dur'])} | การ์ดชื่อโครงการบนรูปแรกแบบเบลอ<br>→ เฟดเข้าฉาก 1 | "
                     f"{cell('<br>'.join(card_texts))} | — |")
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
        nxt = (f"<br>→ {TRANSITION_NAMES.get(tm['transitions'][i], tm['transitions'][i])}"
               if i < len(images) - 1 else "<br>→ เฟดเข้าฉากปิด")
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
        f"{'รูปสุดท้ายครึ่งบน + แถบข้อมูลครึ่งล่าง' if tm['outro'] == 'split' else 'รูปสุดท้ายแบบเบลอ + มืดลง'}<br>เฟดดำตอนจบ | {cell('<br>'.join(outro_texts))} | "
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
        "| ตำแหน่งข้อความ / ฉากเปิด / ฉากปิด | `video_layout` (classic/lower/band), `intro` (overlay/card), `outro` (center/split) |",
        "| การเคลื่อนไหวของแต่ละรูป | `images[].motion` (push/pull/pan_left/pan_right/rise), `focus` [x, y], `effects`, `sweep`, `parallax`, `with` |",
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
