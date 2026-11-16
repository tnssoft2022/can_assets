#!/usr/bin/env python3
"""
สร้างรูปโปสต์โฆษณาทรัพย์ (รูปนิ่ง) จาก config.json เดียวกับวิดีโอ

วิธีใช้:
    python3 make_poster.py projects/<ชื่อโปรเจกต์> [--style luxury|modern|minimal] [--size post|square|story]

ขนาด:
    post    1080x1350 (4:5)  ฟีด Facebook / Instagram  ← ค่าเริ่มต้น
    square  1080x1080 (1:1)
    story   1080x1920 (9:16) Story / Reels cover

รูปแบบ (ค่าเริ่มต้น collage ถ้าทรัพย์มีมากกว่า 1 รูป):
    collage  รูปหลักใหญ่ + รูปเล็กเรียงแถว + แถบข้อมูลด้านล่าง
    single   รูปเดียวเต็มกรอบ ข้อความทับบนรูป

ค่าใน config.json ที่ใช้เพิ่ม (ไม่บังคับ):
    "poster_layout": "collage"            collage / single
    "poster_images": ["03.jpeg", "04.jpeg", "05.jpeg", "02.jpeg"]
                                          รูปที่ใช้ (รูปแรก = รูปหลัก, ที่เหลือ = รูปเล็กสูงสุด 3 รูป)
    "poster_image": "03.jpeg"             รูปหลัก (ถ้าไม่ได้กำหนด poster_images)
    "poster_tag": "ห้องใหม่"               ป้ายเล็กมุมซ้ายบน (ค่าเริ่มต้น = คำบรรยายแรกที่มี)
"""
import os
import shutil
import subprocess
import sys

import make_video as mv

SIZES = {
    "post": (1080, 1350),
    "square": (1080, 1080),
    "story": (1080, 1920),
}


def pick_image(cfg):
    want = cfg.get("poster_image")
    if want:
        for img in cfg["_images"]:
            if img.get("file", os.path.basename(img["path"])) == want:
                return img
    return cfg["_images"][0]


def pick_images(cfg, count=4):
    """รูปหลัก + รูปเล็ก: จาก poster_images ถ้ามี ไม่งั้นรูปหลักตาม poster_image แล้วตามด้วยรูปถัดไป"""
    by_name = {i.get("file", os.path.basename(i["path"])): i for i in cfg["_images"]}
    if cfg.get("poster_images"):
        chosen = [by_name[n] for n in cfg["poster_images"] if n in by_name]
        if chosen:
            return chosen[:count]
    main = pick_image(cfg)
    rest = [i for i in cfg["_images"] if i is not main]
    return ([main] + rest)[:count]


def poster_texts(cfg):
    contact = cfg.get("contact", {}) or {}
    phone, line_id = contact.get("phone", ""), contact.get("line", "")
    tag = cfg.get("poster_tag")
    if tag is None:
        tag = next((i["caption"] for i in cfg["_images"] if i.get("caption")), "")
    return {
        "title": cfg.get("title", ""),
        "location": cfg.get("location", ""),
        "price": cfg.get("price", ""),
        "details": "  |  ".join(cfg.get("details", [])),
        "contact": "  ".join(t for t in [("โทร " + phone) if phone else "",
                                         ("LINE: " + line_id) if line_id else ""] if t),
        "ref": contact.get("name", ""),
        "tag": tag,
    }


# สัดส่วนของ collage: (ความสูงรูปหลัก, ความสูงแถวรูปเล็ก) เทียบกับความสูงทั้งหมด
COLLAGE = {
    "post": (0.585, 0.165),
    "square": (0.545, 0.185),
    "story": (0.53, 0.14),
}


def render_collage(cfg, size, out_path, tmpdir):
    W, H = SIZES[size]
    th = cfg["_theme"]
    imgs = pick_images(cfg)
    main, thumbs = imgs[0], imgs[1:]
    light = th["outro_text"] == "0x222222"  # มินิมอล = แถบข้อมูลสีขาว
    panel = "0xF7F5F2" if light else "0x141414"
    gap = 8
    m = int(W * 0.045)
    main_h = mv.even(H * COLLAGE[size][0])
    thumb_h = mv.even(H * COLLAGE[size][1])
    thumb_y = main_h + gap
    panel_y = thumb_y + thumb_h + gap
    bottom_safe = int(H * 0.11) if size == "story" else 0

    args = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={panel}:s={W}x{H},format=yuv420p"]
    parts = []
    args += ["-i", main["path"]]
    parts.append(f"[1:v]scale={W}:{main_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                 f"crop={W}:{main_h},setsar=1[main]")
    parts.append("[0:v][main]overlay=0:0[v0]")
    video, idx = "v0", 2

    # รูปเล็กเรียงแถว
    if thumbs:
        n = len(thumbs)
        tw = mv.even((W - gap * (n - 1)) / n)
        for k, t in enumerate(thumbs):
            args += ["-i", t["path"]]
            x = k * (tw + gap) if k < n - 1 else W - tw  # ชิดขอบขวาพอดี
            parts.append(f"[{idx}:v]scale={tw}:{thumb_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                         f"crop={tw}:{thumb_h},setsar=1[t{k}]")
            parts.append(f"[{video}][t{k}]overlay={x}:{thumb_y}[vt{k}]")
            video, idx = f"vt{k}", idx + 1

    # เงาไล่สีท้ายรูปหลัก ให้ชื่อโครงการอ่านง่าย
    if not light:
        gh = mv.even(main_h * 0.45)
        args += ["-f", "lavfi", "-i",
                 f"gradients=s={W}x{gh}:c0=0x000000C8:c1=0x00000000:x0=0:y0={gh}:x1=0:y1=0:n=2:speed=0"]
        parts.append(f"[{video}][{idx}:v]overlay=0:{main_h - gh}[vg]")
        video, idx = "vg", idx + 1

    # โลโก้
    if cfg["_logo"]:
        lw_, lh_ = cfg["_logo_size"]
        lw = mv.even(W * (0.17 if lw_ / lh_ < 1.6 else 0.24))
        args += ["-i", cfg["_logo"]]
        parts.append(f"[{idx}:v]scale={lw}:-1:flags=lanczos,format=rgba[logo]")
        parts.append(f"[{video}][logo]overlay=W-w-{m}:{m}[vl]")
        video, idx = "vl", idx + 1

    t = poster_texts(cfg)
    tl = mv.TextLayer(tmpdir, th)
    a, b = -1.0, 10.0
    s = th["size_scale"] * {"square": 0.92, "story": 1.1}.get(size, 1.0)
    max_w = W - 2 * m
    box = th["box"]

    # ชื่อโครงการ + ทำเล ท้ายรูปหลัก
    fs_title = mv.fit_fontsize(t["title"], int(62 * s), max_w)
    fs_loc = mv.fit_fontsize(t["location"], int(36 * s), max_w)
    y = main_h - int(m * 0.8)
    if t["location"]:
        y -= fs_loc
        tl.add(t["location"], fs_loc, m, y, a, b, color=th["sub"], box=box, bold=False)
        y -= int(fs_loc * 0.75)
    if t["title"]:
        y -= fs_title
        tl.add(t["title"], fs_title, m, y, a, b, box=box)
    if t["tag"]:
        tl.add(t["tag"], int(36 * s), m, m + int(10 * s), a, b,
               color=th["caption_color"], box=th["caption_box"] or box or "black@0.5")

    # แถบข้อมูลด้านล่าง: ราคา / รายละเอียด / เบอร์ / รหัสทรัพย์ (จัดกึ่งกลางแนวตั้งในแถบ)
    text_c = "0x222222" if light else "white"
    sub_c = "0x666666" if light else "white@0.75"
    price_c = th["outro_price"] if light else th["price_color"]
    pbox = th["price_box"] if th["price_box"] and not light else None
    rows = []
    if t["price"]:
        fs = mv.fit_fontsize(t["price"], int(78 * s), max_w)
        rows.append((t["price"], fs, price_c, pbox, None))
    if t["details"]:
        rows.append((t["details"], mv.fit_fontsize(t["details"], int(36 * s), max_w), sub_c, None, False))
    if t["contact"]:
        rows.append((t["contact"], mv.fit_fontsize(t["contact"], int(42 * s), max_w), text_c, None, None))
    if t["ref"]:
        rows.append((t["ref"], int(26 * s), sub_c, None, False))
    avail = H - bottom_safe - panel_y
    pad = int(m * 0.6)

    def measure(rs):
        sp = [int(r[1] * (0.62 if r[3] else 0.42)) for r in rs]
        # กล่องราคามีขอบหนา ต้องเผื่อด้านบน/ล่าง
        extra = sum(int(r[1] * 0.38) * 2 for r in rs if r[3])
        return sp, sum(r[1] for r in rs) + sum(sp[:-1]) + extra

    spacing, block = measure(rows)
    if block > avail - 2 * pad:  # ข้อความไม่พอดีแถบ → ย่อทุกบรรทัดตามสัดส่วน
        k = (avail - 2 * pad) / block
        rows = [(tx, max(20, int(fs * k)), c, bx, bd) for tx, fs, c, bx, bd in rows]
        spacing, block = measure(rows)
    y = panel_y + max(pad, (avail - block) // 2) + (int(rows[0][1] * 0.38) if rows and rows[0][3] else 0)
    for (text, fs, col, bx, bold), sp in zip(rows, spacing):
        tl.add(text, fs, m, y, a, b, color=col, box=bx, bold=bold)
        y += fs + sp

    if tl.filters:
        parts.append(f"[{video}]" + ",".join(tl.filters) + "[out]")
        video = "out"
    script = os.path.join(tmpdir, "filter_poster.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(parts))
    args += mv.filter_script_args(script) + ["-map", f"[{video}]", "-frames:v", "1",
             "-update", "1", "-q:v", "2", out_path]
    subprocess.run(args, check=True)
    print(f"✓ โปสต์: {out_path}")


def render_poster(cfg, size, out_path, tmpdir):
    W, H = SIZES[size]
    th = cfg["_theme"]
    img = pick_image(cfg)

    args = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error", "-i", img["path"]]
    parts = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
             f"crop={W}:{H},setsar=1,format=yuv420p[bg]"]
    video, idx = "bg", 1

    # เงาไล่สีให้ข้อความอ่านง่าย (สไตล์หรูหราไม่มีกล่องข้อความ จึงเข้มกว่า)
    bottom_h = mv.even(H * (0.62 if th["gradient"] else 0.45))  # ต้องเป็นเลขคู่ (yuv420)
    alpha = "E0" if th["gradient"] else "90"
    grads = [(f"gradients=s={W}x{bottom_h}:c0=0x000000{alpha}:c1=0x00000000:"
              f"x0=0:y0={bottom_h}:x1=0:y1=0:n=2:speed=0", f"0:{H - bottom_h}")]
    if th["gradient"]:
        top_h = mv.even(H * 0.22)
        grads.append((f"gradients=s={W}x{top_h}:c0=0x00000080:c1=0x00000000:"
                      f"x0=0:y0=0:x1=0:y1={top_h}:n=2:speed=0", "0:0"))
    if not th["outro_text"] == "0x222222":  # มินิมอลใช้กล่องขาว ไม่ต้องมีเงา
        for src, pos in grads:
            args += ["-f", "lavfi", "-i", src]
            parts.append(f"[{video}][{idx}:v]overlay={pos}[g{idx}]")
            video, idx = f"g{idx}", idx + 1

    # โลโก้มุมขวาบน
    m = int(W * 0.045)
    if cfg["_logo"]:
        lw_, lh_ = cfg["_logo_size"]
        lw = mv.even(W * (0.19 if lw_ / lh_ < 1.6 else 0.26))
        args += ["-i", cfg["_logo"]]
        parts.append(f"[{idx}:v]scale={lw}:-1:flags=lanczos,format=rgba[logo]")
        parts.append(f"[{video}][logo]overlay=W-w-{m}:{m}[vl]")
        video, idx = "vl", idx + 1

    # ข้อความ (รูปนิ่ง: ให้แสดงตั้งแต่ก่อน t=0 เพื่อไม่ติดเอฟเฟกต์เฟด)
    tl = mv.TextLayer(tmpdir, th)
    a, b = -1.0, 10.0
    x0 = m
    max_w = W - 2 * m
    title = cfg.get("title", "")
    location = cfg.get("location", "")
    price = cfg.get("price", "")
    details = "  |  ".join(cfg.get("details", []))
    contact = cfg.get("contact", {}) or {}
    tag = cfg.get("poster_tag")
    if tag is None:
        tag = next((i["caption"] for i in cfg["_images"] if i.get("caption")), "")
    s = th["size_scale"]
    box, pbox, cbox = th["box"], th["price_box"], th["caption_box"]

    # จัดวางจากล่างขึ้นบน (story: เว้นขอบล่างให้พ้นปุ่มตอบกลับของ IG/Facebook)
    y = H - (int(H * 0.11) if size == "story" else m)
    ref_line = contact.get("name", "")
    phone = contact.get("phone", "")
    line_id = contact.get("line", "")
    contact_txt = "  ".join(t for t in [("โทร " + phone) if phone else "",
                                         ("LINE: " + line_id) if line_id else ""] if t)
    fs_ref = int(30 * s)
    fs_contact = mv.fit_fontsize(contact_txt, int(46 * s), max_w)
    fs_details = mv.fit_fontsize(details, int(40 * s), max_w)
    fs_price = mv.fit_fontsize(price, int(84 * s), max_w)
    fs_loc = mv.fit_fontsize(location, int(38 * s), max_w)
    fs_title = mv.fit_fontsize(title, int(66 * s), max_w)

    if ref_line:
        y -= fs_ref
        tl.add(ref_line, fs_ref, x0, y, a, b, color=th["sub"], box=box, bold=False)
        y -= int(fs_ref * 1.2)
    if contact_txt:
        y -= fs_contact
        tl.add(contact_txt, fs_contact, x0, y, a, b, box=box)
        y -= int(fs_contact * 0.9)
    if th["separator"] and not pbox:
        tl.line(x0, y - 6, 110, 3, a, b)
        y -= int(30 * s)
    if details:
        y -= fs_details
        tl.add(details, fs_details, x0, y, a, b, color=th["sub"], box=box, bold=False)
        y -= int(fs_details * 0.9)
    if price:
        y -= fs_price
        tl.add(price, fs_price, x0, y, a, b, color=th["price_color"], box=pbox)
        y -= int(fs_price * 0.75)
    if location:
        y -= fs_loc
        tl.add(location, fs_loc, x0, y, a, b, color=th["sub"], box=box, bold=False)
        y -= int(fs_loc * 0.8)
    if title:
        y -= fs_title
        tl.add(title, fs_title, x0, y, a, b, box=box)
    if tag:
        tl.add(tag, int(38 * s), x0, m + int(10 * s), a, b, color=th["caption_color"], box=cbox or box or "black@0.5")

    if tl.filters:
        parts.append(f"[{video}]" + ",".join(tl.filters) + "[out]")
        video = "out"

    script = os.path.join(tmpdir, "filter_poster.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(parts))
    args += mv.filter_script_args(script) + ["-map", f"[{video}]", "-frames:v", "1",
             "-update", "1", "-q:v", "2", out_path]
    subprocess.run(args, check=True)
    print(f"✓ โปสต์: {out_path}")


def make(project_dir, style=None, size="post", skip_existing=False):
    """สร้างรูปโปสต์ของโปรเจกต์ คืนค่า path ของไฟล์ (หรือ None ถ้าข้าม)"""
    if size not in SIZES:
        raise ValueError(f"ขนาดต้องเป็น: {', '.join(SIZES)}")
    project_dir = os.path.abspath(project_dir)
    cfg = mv.load_project(project_dir, style)
    out_dir = os.path.join(project_dir, "output")
    name = cfg.get("output_name") or os.path.basename(project_dir)
    out_path = os.path.join(out_dir, f"{name}_{cfg['_style']}_poster_{size}.jpg")
    if skip_existing and os.path.exists(out_path):
        return None
    tmpdir = os.path.join(out_dir, ".tmp_poster")
    os.makedirs(tmpdir, exist_ok=True)
    layout = cfg.get("poster_layout") or ("collage" if len(cfg["_images"]) > 1 else "single")
    try:
        if layout == "collage" and len(cfg["_images"]) > 1:
            render_collage(cfg, size, out_path, tmpdir)
        else:
            render_poster(cfg, size, out_path, tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out_path


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    argv = sys.argv[1:]
    opts = {"style": None, "size": "post"}
    for flag in ("--style", "--size"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                sys.exit(f"{flag} ต้องมีค่า")
            opts[flag[2:]] = argv[i + 1]
            del argv[i:i + 2]
    if not argv:
        print(__doc__)
        sys.exit(1)
    try:
        make(argv[0], opts["style"], opts["size"])
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
