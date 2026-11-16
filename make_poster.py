#!/usr/bin/env python3
"""
สร้างรูปโปสต์โฆษณาทรัพย์ (รูปนิ่ง) จาก config.json เดียวกับวิดีโอ

วิธีใช้:
    python3 make_poster.py projects/<ชื่อโปรเจกต์> [--style <สไตล์>] [--size post|square|story] [--layout <แบบ>]

ขนาด:
    post    1080x1350 (4:5)  ฟีด Facebook / Instagram  ← ค่าเริ่มต้น
    square  1080x1080 (1:1)
    story   1080x1920 (9:16) Story / Reels cover

แบบจัดวาง (ไม่ระบุ = เลือกจากรหัสโปรเจกต์และจำนวนรูป → โปรเจกต์เดิมได้แบบเดิมเสมอ):
    collage   รูปหลักใหญ่ + รูปเล็กเรียงแถว + แถบข้อมูลด้านล่าง
    grid      ตาราง 2×2 (3 รูป = รูปบนเต็มแถว) + แถบข้อมูลด้านล่าง
    split     รูปหลักใหญ่ซ้าย + รูปเล็ก 2 รูปเรียงขวา + แถบข้อมูลด้านล่าง
    magazine  รูปเต็มหน้า ชื่อตัวใหญ่ด้านบน + แถบราคาเต็มความกว้าง + รูปเล็กแบบมีกรอบ
    frame     รูปอยู่ในกรอบสี บนพื้นสีของสไตล์ + ข้อความจัดกึ่งกลาง (เหมาะกับรูปเล็ก/ไม่คม)
    single    รูปเดียวเต็มกรอบ ข้อความทับบนรูป

ค่าใน config.json ที่ใช้เพิ่ม (ไม่บังคับ):
    "poster_layout": "collage"            collage / grid / split / magazine / frame / single / auto
    "poster_images": ["03.jpeg", "04.jpeg", "05.jpeg", "02.jpeg"]
                                          รูปที่ใช้ (รูปแรก = รูปหลัก, ที่เหลือ = รูปเล็กสูงสุด 3 รูป)
    "poster_image": "03.jpeg"             รูปหลัก (ถ้าไม่ได้กำหนด poster_images)
    "poster_tag": "ห้องใหม่"               ป้ายเล็กมุมซ้ายบน (ค่าเริ่มต้น = คำบรรยายแรกที่มี)
"""
import os
import shutil
import subprocess
import sys
import zlib

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


def above(y_top, fs_lower, fs_upper, boxed, gap=8):
    """ตำแหน่ง y ของบรรทัดที่วางเหนือบรรทัดที่อยู่ที่ y_top โดยไม่ให้กล่องข้อความซ้อนกัน
    (ข้อความไทยของ Kanit สูงราว 1.3 เท่าของขนาดฟอนต์ + ขอบกล่อง 0.38 เท่า)"""
    pad = (int(fs_lower * 0.38) + int(fs_upper * 0.38)) if boxed else 0
    return y_top - pad - gap - int(fs_upper * 1.3)


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


LAYOUTS = ("collage", "grid", "split", "magazine", "frame", "single")


def choose_layout(cfg, n, forced=None):
    """แบบจัดวาง: --layout > poster_layout ใน config > เลือกจากชื่อโปรเจกต์ตามจำนวนรูปที่มี"""
    want = forced or cfg.get("poster_layout")
    if want not in (None, "auto"):
        if want not in LAYOUTS:
            raise ValueError(f"poster_layout ต้องเป็น: {', '.join(LAYOUTS)} หรือ auto")
        return want if n > 1 or want in ("single", "magazine", "frame") else "single"
    if n >= 3:
        opts = ["collage", "grid", "split", "magazine", "frame"]
    elif n == 2:
        opts = ["collage", "magazine", "frame"]
    else:
        opts = ["single", "magazine", "frame"]
    return opts[zlib.crc32(f"poster_layout:{cfg.get('_name', '')}".encode("utf-8")) % len(opts)]


def accent(th, c):
    """แปลง accent / accent@0.9 เป็นสีจริง"""
    if c and c.startswith("accent"):
        return th["accent_color"] + c[len("accent"):]
    return c


class Canvas:
    """ประกอบรูปโปสต์ทีละชั้นด้วย ffmpeg: พื้นสี → รูป → กล่อง/เงา → โลโก้ → ข้อความ"""

    def __init__(self, W, H, bg):
        self.W, self.H = W, H
        self.args = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
                     "-f", "lavfi", "-i", f"color=c={bg}:s={W}x{H},format=yuv420p"]
        self.parts = []
        self.video, self.idx, self.n = "0:v", 1, 0

    def _label(self):
        self.n += 1
        return f"k{self.n}"

    def _overlay(self, src, x, y):
        out = self._label()
        self.parts.append(f"[{self.video}][{src}]overlay={int(x)}:{int(y)}[{out}]")
        self.video = out

    def image(self, path, w, h, x, y):
        w, h = mv.even(w), mv.even(h)
        self.args += ["-i", path]
        src = self._label()
        self.parts.append(f"[{self.idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
                          f"crop={w}:{h},setsar=1[{src}]")
        self.idx += 1
        self._overlay(src, x, y)

    def box(self, x, y, w, h, color):
        out = self._label()
        self.parts.append(f"[{self.video}]drawbox=x={int(x)}:y={int(y)}:w={int(w)}:h={int(h)}:"
                          f"color={color}:t=fill[{out}]")
        self.video = out

    def shade(self, w, h, x, y, alpha, dark_at="bottom"):
        """เงาไล่สีดำ (dark_at = ด้านที่เข้ม)"""
        h = mv.even(h)
        y0, y1 = (h, 0) if dark_at == "bottom" else (0, h)
        self.args += ["-f", "lavfi", "-i", f"gradients=s={int(w)}x{h}:c0=0x000000{alpha}:c1=0x00000000:"
                                           f"x0=0:y0={y0}:x1=0:y1={y1}:n=2:speed=0"]
        src = f"{self.idx}:v"
        self.idx += 1
        self._overlay(src, x, y)

    def logo(self, cfg, frac, x_right, y):
        """โลโก้ชิดขวาที่ x_right คืนค่าความกว้างที่ใช้ (0 ถ้าไม่มีโลโก้)"""
        if not cfg["_logo"]:
            return 0
        lw_, lh_ = cfg["_logo_size"]
        lw = mv.even(self.W * (frac if lw_ / lh_ < 1.6 else frac * 1.4))
        self.args += ["-i", cfg["_logo"]]
        src = self._label()
        self.parts.append(f"[{self.idx}:v]scale={lw}:-1:flags=lanczos,format=rgba[{src}]")
        self.idx += 1
        self._overlay(src, x_right - lw, y)
        return lw

    def render(self, tl, tmpdir, out_path):
        if tl.filters:
            self.parts.append(f"[{self.video}]" + ",".join(tl.filters) + "[out]")
            self.video = "out"
        script = os.path.join(tmpdir, "filter_poster.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(";\n".join(self.parts))
        subprocess.run(self.args + mv.filter_script_args(script) + [
            "-map", f"[{self.video}]", "-frames:v", "1", "-update", "1", "-q:v", "2", out_path], check=True)
        print(f"✓ โปสต์: {out_path}")


def panel_colors(th):
    """สีข้อความบนแถบข้อมูล: (ตัวหลัก, ตัวรอง, ราคา, กล่องราคา)"""
    if th.get("light"):  # แถบสีอ่อน: ใช้สี/กล่องราคาของฉากปิด (เช่น ธรรมชาติ = ตัวขาวบนกล่องเขียว)
        return th["outro_text"], th.get("sub") or "0x666666", th["outro_price"], th.get("outro_price_box")
    return "white", "white@0.75", th["price_color"], th["price_box"]


def info_rows(t, th, s, max_w, title=False, price=True):
    """บรรทัดข้อมูลบนแถบ: (ข้อความ, ขนาด, สี, กล่อง, ตัวหนา)"""
    text_c, sub_c, price_c, pbox = panel_colors(th)
    rows = []
    if title and t["title"]:
        rows.append((t["title"], mv.fit_fontsize(t["title"], int(60 * s), max_w), text_c, None, None))
    if title and t["location"]:
        rows.append((t["location"], mv.fit_fontsize(t["location"], int(34 * s), max_w), sub_c, None, False))
    if price and t["price"]:
        rows.append((t["price"], mv.fit_fontsize(t["price"], int(78 * s), max_w), price_c, pbox, None))
    if t["details"]:
        rows.append((t["details"], mv.fit_fontsize(t["details"], int(36 * s), max_w), sub_c, None, False))
    if t["contact"]:
        rows.append((t["contact"], mv.fit_fontsize(t["contact"], int(42 * s), max_w), text_c, None, None))
    if t["ref"]:
        rows.append((t["ref"], int(26 * s), sub_c, None, False))
    return rows


def _measure(rows):
    sp = [int(r[1] * 0.42) for r in rows]
    # กล่องราคามีขอบหนา ต้องเผื่อด้านบน/ล่างของกล่อง
    extra = sum(int(r[1] * 0.38) * 2 for r in rows if r[3])
    return sp, sum(r[1] for r in rows) + sum(sp[:-1]) + extra


def rows_height(rows):
    return _measure(rows)[1] if rows else 0


def stack_rows(tl, rows, x, top, avail, pad, a, b):
    """วางบรรทัดเรียงลงมาในพื้นที่สูง avail จัดกึ่งกลางแนวตั้ง (ย่อทุกบรรทัดถ้าไม่พอ)"""
    if not rows:
        return
    spacing, block = _measure(rows)
    if block > avail - 2 * pad:
        k = (avail - 2 * pad) / block
        rows = [(tx, max(20, int(fs * k)), c, bx, bd) for tx, fs, c, bx, bd in rows]
        spacing, block = _measure(rows)
    y = top + max(pad, (avail - block) // 2)
    for (text, fs, col, bx, bold), sp in zip(rows, spacing):
        bp = int(fs * 0.38) if bx else 0
        tl.add(text, fs, x, y + bp, a, b, color=col, box=bx, bold=bold)
        y += fs + 2 * bp + sp


def add_tag(tl, t, th, s, x, y, max_w=None):
    if t["tag"]:
        fs = int(36 * s) if max_w is None else mv.fit_fontsize(t["tag"], int(36 * s), max_w)
        tl.add(t["tag"], fs, x, y, -1.0, 10.0,
               color=th["caption_color"], box=th["caption_box"] or th["box"] or "black@0.5")


def title_block(tl, t, th, s, x, bottom, max_w, fs_title=62, fs_loc=36):
    """ชื่อโครงการ + ทำเล วางให้บรรทัดล่างสุดจบที่ bottom"""
    box = th["box"]
    ft = mv.fit_fontsize(t["title"], int(fs_title * s), max_w)
    fl = mv.fit_fontsize(t["location"], int(fs_loc * s), max_w)
    y = bottom
    if t["location"]:
        y -= int(fl * 1.3)
        tl.add(t["location"], fl, x, y, -1.0, 10.0, color=th["sub"], box=box, bold=False)
    if t["title"]:
        y = above(y, fl, ft, bool(box)) if t["location"] else y - int(ft * 1.3)
        tl.add(t["title"], ft, x, y, -1.0, 10.0, box=box)


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
    light = th.get("light", False)  # มินิมอล/ธรรมชาติ = แถบข้อมูลสีอ่อน
    panel = mv.panel_color(th)
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
        y -= int(fs_loc * 1.3)
        tl.add(t["location"], fs_loc, m, y, a, b, color=th["sub"], box=box, bold=False)
    if t["title"]:
        y = above(y, fs_loc, fs_title, bool(box)) if t["location"] else y - int(fs_title * 1.3)
        tl.add(t["title"], fs_title, m, y, a, b, box=box)
    if t["tag"]:
        tl.add(t["tag"], int(36 * s), m, m + int(10 * s), a, b,
               color=th["caption_color"], box=th["caption_box"] or box or "black@0.5")

    # แถบข้อมูลด้านล่าง: ราคา / รายละเอียด / เบอร์ / รหัสทรัพย์ (จัดกึ่งกลางแนวตั้งในแถบ)
    rows = info_rows(t, th, s, max_w)
    stack_rows(tl, rows, m, panel_y, H - bottom_safe - panel_y, int(m * 0.6), a, b)

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
    if not th.get("light"):  # สไตล์สีอ่อนใช้กล่องสีอ่อน ไม่ต้องมีเงาไล่สี
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
    if title:
        y = above(y, fs_loc, fs_title, bool(box)) if location else y - int(fs_loc * 0.8) - fs_title
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


def _setup(cfg, size):
    W, H = SIZES[size]
    th = cfg["_theme"]
    s = th["size_scale"] * {"square": 0.92, "story": 1.1}.get(size, 1.0)
    bottom_safe = int(H * 0.11) if size == "story" else 0
    return W, H, th, s, bottom_safe


def render_grid(cfg, size, out_path, tmpdir):
    """ตาราง 2×2 (3 รูป = รูปแรกเต็มแถวบน) + แถบสี + แถบข้อมูลรวมชื่อโครงการ"""
    W, H, th, s, bottom_safe = _setup(cfg, size)
    imgs = pick_images(cfg)
    c = Canvas(W, H, mv.panel_color(th))
    gap, m = 8, int(W * 0.045)
    grid_h = mv.even(H * {"post": 0.6, "square": 0.56, "story": 0.56}[size])
    if len(imgs) >= 4:
        rows = [imgs[0:2], imgs[2:4]]
    elif len(imgs) == 3:
        rows = [imgs[0:1], imgs[1:3]]
    else:
        rows = [[im] for im in imgs]
    rh = (grid_h - gap * (len(rows) - 1)) / len(rows)
    for r, row in enumerate(rows):
        cw = (W - gap * (len(row) - 1)) / len(row)
        for k, im in enumerate(row):
            x = int(k * (cw + gap)) if k < len(row) - 1 else W - mv.even(cw)
            c.image(im["path"], cw, rh, x, int(r * (rh + gap)))
    stripe = max(8, int(H * 0.008))
    c.box(0, grid_h, W, stripe, accent(th, "accent"))
    c.logo(cfg, 0.16, W - m, m)

    t = poster_texts(cfg)
    tl = mv.TextLayer(tmpdir, th)
    add_tag(tl, t, th, s, m, m + int(10 * s))
    top = grid_h + stripe
    stack_rows(tl, info_rows(t, th, s, W - 2 * m, title=True), m, top, H - bottom_safe - top, int(m * 0.5), -1.0, 10.0)
    c.render(tl, tmpdir, out_path)


def render_split(cfg, size, out_path, tmpdir):
    """รูปหลักใหญ่ซ้าย (ชื่อโครงการท้ายรูป) + รูปเล็กเรียงขวา + แถบข้อมูลด้านล่าง"""
    W, H, th, s, bottom_safe = _setup(cfg, size)
    imgs = pick_images(cfg, 3)
    c = Canvas(W, H, mv.panel_color(th))
    gap, m = 8, int(W * 0.045)
    top_h = mv.even(H * {"post": 0.64, "square": 0.6, "story": 0.6}[size])
    left_w = mv.even(W * 0.64)
    c.image(imgs[0]["path"], left_w, top_h, 0, 0)
    side = imgs[1:] or imgs[:1]
    sh = (top_h - gap * (len(side) - 1)) / len(side)
    for k, im in enumerate(side):
        y = int(k * (sh + gap)) if k < len(side) - 1 else top_h - mv.even(sh)
        c.image(im["path"], W - left_w - gap, sh, left_w + gap, y)
    if not th.get("light"):
        c.shade(left_w, top_h * 0.5, 0, top_h - mv.even(top_h * 0.5), "D0")
    c.logo(cfg, 0.15, W - m, m)

    t = poster_texts(cfg)
    tl = mv.TextLayer(tmpdir, th)
    add_tag(tl, t, th, s, m, m + int(10 * s), left_w - 2 * m)
    title_block(tl, t, th, s, m, top_h - int(m * 0.8), left_w - 2 * m, 56, 32)
    stack_rows(tl, info_rows(t, th, s, W - 2 * m), m, top_h + gap, H - bottom_safe - top_h - gap,
               int(m * 0.6), -1.0, 10.0)
    c.render(tl, tmpdir, out_path)


def render_magazine(cfg, size, out_path, tmpdir):
    """รูปเต็มหน้า ชื่อตัวใหญ่ด้านบน + รูปเล็กมีกรอบ + แถบราคาเต็มความกว้าง + แถบข้อมูลล่างสุด"""
    W, H, th, s, bottom_safe = _setup(cfg, size)
    imgs = pick_images(cfg)
    light = th.get("light", False)
    panel = mv.panel_color(th)
    text_c, sub_c, price_c, pbox = panel_colors(th)
    c = Canvas(W, H, panel)
    m = int(W * 0.05)
    t = poster_texts(cfg)
    tl = mv.TextLayer(tmpdir, th)

    # แถบล่างสุด (รายละเอียด / เบอร์ / รหัส) และแถบราคาเหนือขึ้นไป
    rows = info_rows(t, th, s, W - 2 * m, price=False)
    pad = int(m * 0.5)
    strip_h = rows_height(rows) + 2 * pad + bottom_safe
    fs_price = mv.fit_fontsize(t["price"], int(96 * s), W - 2 * m) if t["price"] else 0
    band_h = int(fs_price * 1.9) if t["price"] else 0
    band_y = H - strip_h - band_h
    c.image(imgs[0]["path"], W, band_y, 0, 0)
    if not light:
        # สไตล์ไม่มีกล่องข้อความ (หรูหรา/กลางคืน) ต้องใช้เงาเข้มกว่า ให้ชื่อตัวใหญ่อ่านออกบนท้องฟ้าสว่าง
        boxless = not th["box"]
        c.shade(W, band_y * (0.48 if boxless else 0.38), 0, 0, "F0" if boxless else "C8", dark_at="top")
        c.shade(W, band_y * 0.3, 0, band_y - mv.even(band_y * 0.3), "A0")
    if band_h:
        band = accent(th, pbox) if pbox else "black@0.7"
        c.box(0, band_y, W, band_h, band)
        tl.add(t["price"], fs_price, m, band_y + (band_h - int(fs_price * 1.25)) // 2, -1.0, 10.0,
               color=price_c if pbox else accent(th, "accent"))
    stack_rows(tl, rows, m, band_y + band_h, strip_h - bottom_safe, pad, -1.0, 10.0)

    # รูปเล็กแบบมีกรอบ ชิดขวาเหนือแถบราคา
    thumbs = imgs[1:4]
    ts = mv.even(W * 0.19)
    bw = max(5, int(W * 0.006))
    tgap = int(W * 0.02)
    ty = band_y - ts - int(m * 0.7)
    for k, im in enumerate(reversed(thumbs)):
        x = W - m - ts - k * (ts + tgap)
        c.box(x - bw, ty - bw, ts + 2 * bw, ts + 2 * bw, "white" if not light else panel)
        c.image(im["path"], ts, ts, x, ty)
    thumbs_w = len(thumbs) * (ts + tgap)

    lw = c.logo(cfg, 0.15, W - m, m)
    # ชื่อตัวใหญ่ + ทำเล มุมซ้ายบน
    max_w = W - 2 * m - (lw + int(W * 0.03) if lw else 0)
    ft = mv.fit_fontsize(t["title"], int(84 * s), max_w)
    fl = mv.fit_fontsize(t["location"], int(38 * s), max_w)
    box = th["box"]
    y = m + (int(ft * 0.38) if box else 0)
    if t["title"]:
        tl.add(t["title"], ft, m, y, -1.0, 10.0, box=box)
        y += int(ft * 1.3) + (int(ft * 0.38) + int(fl * 0.38) if box else 0) + 10
    if t["location"]:
        tl.add(t["location"], fl, m, y, -1.0, 10.0, color=th["sub"], box=box, bold=False)
    if t["tag"]:
        fs_tag = mv.fit_fontsize(t["tag"], int(36 * s), W - 2 * m - thumbs_w)
        add_tag(tl, t, th, s, m, band_y - int(m * 0.7) - int(fs_tag * 1.3) - int(fs_tag * 0.38),
                W - 2 * m - thumbs_w)
    c.render(tl, tmpdir, out_path)


def render_frame(cfg, size, out_path, tmpdir):
    """รูปในกรอบสีบนพื้นสีของสไตล์ + รูปเล็กเรียงแถว + ข้อความจัดกึ่งกลาง"""
    W, H, th, s, bottom_safe = _setup(cfg, size)
    imgs = pick_images(cfg)
    c = Canvas(W, H, mv.panel_color(th))
    m = int(W * 0.06)
    gap = int(W * 0.025)
    bw = max(6, int(W * 0.007))
    main_h = mv.even(H * {"post": 0.5, "square": 0.44, "story": 0.45}[size])
    fw = W - 2 * m
    c.box(m - bw, m - bw, fw + 2 * bw, main_h + 2 * bw, accent(th, "accent"))
    c.image(imgs[0]["path"], fw, main_h, m, m)
    y = m + main_h + bw
    thumbs = imgs[1:4]
    if thumbs:
        y += gap
        th_h = mv.even(H * {"post": 0.13, "square": 0.14, "story": 0.11}[size])
        tw = (fw - gap * (len(thumbs) - 1)) / len(thumbs)
        for k, im in enumerate(thumbs):
            x = m + int(k * (tw + gap)) if k < len(thumbs) - 1 else m + fw - mv.even(tw)
            c.image(im["path"], tw, th_h, x, y)
        y += th_h
    pad = int(m * 0.3)
    c.logo(cfg, 0.14, W - m - int(W * 0.02), m + int(W * 0.02))

    t = poster_texts(cfg)
    tl = mv.TextLayer(tmpdir, th)
    add_tag(tl, t, th, s, m + int(W * 0.025), m + int(W * 0.025))
    stack_rows(tl, info_rows(t, th, s, W - 2 * m, title=True), "(w-text_w)/2", y, H - bottom_safe - y,
               pad, -1.0, 10.0)
    c.render(tl, tmpdir, out_path)


RENDERERS = {
    "collage": lambda cfg, size, out, tmp: render_collage(cfg, size, out, tmp),
    "grid": render_grid,
    "split": render_split,
    "magazine": render_magazine,
    "frame": render_frame,
    "single": lambda cfg, size, out, tmp: render_poster(cfg, size, out, tmp),
}


def make(project_dir, style=None, size="post", skip_existing=False, layout=None):
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
    chosen = choose_layout(cfg, len(pick_images(cfg)), layout)
    print(f"  แบบจัดวางโปสต์: {chosen}")
    try:
        RENDERERS[chosen](cfg, size, out_path, tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out_path


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    argv = sys.argv[1:]
    opts = {"style": None, "size": "post", "layout": None}
    for flag in ("--style", "--size", "--layout"):
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
        make(argv[0], opts["style"], opts["size"], layout=opts["layout"])
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
