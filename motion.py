#!/usr/bin/env python3
"""
ทำให้รูปเคลื่อนไหว — make_video.py เรียกใช้เอง (ต้องรันด้วย Python ใน .venv ที่ติดตั้งตาม README)

    .venv/bin/python motion.py analyze <โฟลเดอร์ผล>::<รูป> [...]
        ประมาณความลึก (Depth Anything V2 Small) + หาพื้นที่ฟ้า/น้ำ (UperNet ADE20K)
        เก็บใน <โฟลเดอร์ผล>/ : depth.png, sky.png, water.png, info.json
    .venv/bin/python motion.py render <jobs.json>
        สร้างคลิปของแต่ละฉาก (ข้ามคลิปที่มีอยู่แล้ว)

สิ่งที่ทำได้ต่อฉาก:
    กล้อง      push (ซูมเข้าหาจุดโฟกัส) / pull / pan_left / pan_right / rise (เงยขึ้น) — เคลื่อนแบบนุ่ม
    2.5D       ฉากหน้าขยับมากกว่าฉากหลังตามความลึก (parallax)
    น้ำ        ผิวน้ำในสระ/ทะเลกระเพื่อมเบา ๆ
    ฟ้า        เมฆเลื่อนช้า ๆ
    แสงวิ่ง     แถบแสงวิ่งผ่านรูปครั้งเดียว (light sweep)
    แบ่งจอ     2 รูปในฉากเดียว รูปที่สองเลื่อนเข้ามา

โมเดล (ใช้เชิงพาณิชย์ได้): depth-anything/Depth-Anything-V2-Small-hf (Apache-2.0),
openmmlab/upernet-convnext-tiny (MIT) — ดาวน์โหลดอัตโนมัติครั้งแรก เก็บใน ~/.cache/huggingface
"""
import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np

DEPTH_ID = "depth-anything/Depth-Anything-V2-Small-hf"
SEG_ID = "openmmlab/upernet-convnext-tiny"
SKY_LABELS = {"sky"}
WATER_LABELS = {"water", "sea", "river", "lake", "swimming pool", "waterfall"}
ANALYZE_MAX = 1024  # ขนาดรูปที่ส่งให้โมเดล (ด้านยาว)


# ---------------------------------------------------------------- analyze

def _clean_mask(mask, min_frac=0.01):
    """ตัดจุดเล็ก ๆ ทิ้ง เก็บเฉพาะบริเวณใหญ่"""
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] >= min_frac * m.size:
            keep[lab == k] = 1
    return keep


def analyze(pairs):
    """pairs = ["<โฟลเดอร์ผล>::<รูป>", ...] (make_video.py เป็นคนกำหนดโฟลเดอร์)"""
    pairs = [tuple(x.split("::", 1)) for x in pairs]
    todo = [(d, p) for d, p in pairs if not os.path.exists(os.path.join(d, "info.json"))]
    if not todo:
        return
    import torch
    from PIL import Image
    from transformers import (AutoImageProcessor, AutoModelForDepthEstimation,
                              AutoModelForSemanticSegmentation)
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"  ✦ วิเคราะห์ความลึก/ฟ้า/น้ำ {len(todo)} รูป ({dev}) ...")
    dproc = AutoImageProcessor.from_pretrained(DEPTH_ID)
    dmodel = AutoModelForDepthEstimation.from_pretrained(DEPTH_ID).to(dev).eval()
    sproc = AutoImageProcessor.from_pretrained(SEG_ID)
    # UperNet ใช้ adaptive pooling ที่ MPS (GPU ของ Mac) ยังไม่รองรับ → รันบน CPU (โมเดลเล็ก ไม่ช้า)
    smodel = AutoModelForSemanticSegmentation.from_pretrained(SEG_ID).eval()
    labels = {i: n.split(",")[0].strip() for i, n in smodel.config.id2label.items()}
    sky_ids = [i for i, n in labels.items() if n in SKY_LABELS]
    water_ids = [i for i, n in labels.items() if n in WATER_LABELS]

    for out, path in todo:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        k = min(1.0, ANALYZE_MAX / max(w, h))
        small = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
        sw, sh = small.size
        with torch.no_grad():
            d = dmodel(**dproc(images=small, return_tensors="pt").to(dev)).predicted_depth
            d = torch.nn.functional.interpolate(d[:, None], size=(sh, sw), mode="bicubic", align_corners=False)[0, 0]
            d = d.float().cpu().numpy()
            logits = smodel(**sproc(images=small, return_tensors="pt")).logits
            logits = torch.nn.functional.interpolate(logits, size=(sh, sw), mode="bilinear", align_corners=False)
            seg = logits.argmax(1)[0].cpu().numpy()
        # ความลึกแบบสัมพัทธ์: ค่ามาก = ใกล้กล้อง → ปรับเป็น 0..1
        lo, hi = np.percentile(d, 2), np.percentile(d, 98)
        depth = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
        sky = _clean_mask(np.isin(seg, sky_ids))
        water = _clean_mask(np.isin(seg, water_ids), 0.005)
        depth[sky > 0] = 0.0  # ฟ้าอยู่ไกลสุดเสมอ

        # จุดโฟกัสแนะนำ: บริเวณที่ไกลที่สุด (ไม่นับฟ้า) = ทิศที่กล้อง "เดินเข้าไป"
        ground = (sky == 0)
        focus = [0.5, 0.5]
        if ground.sum() > 0.05 * ground.size:
            thr = np.percentile(depth[ground], 15)
            far = ground & (depth <= thr)
            ys, xs = np.nonzero(far)
            if len(xs):
                focus = [float(np.clip(xs.mean() / sw, 0.3, 0.7)), float(np.clip(ys.mean() / sh, 0.3, 0.7))]
        if sky.mean() > 0.12:  # รูปภายนอกที่เห็นฟ้า: โฟกัสที่ตัวอาคาร
            ys, xs = np.nonzero(ground)
            if len(xs):
                focus = [float(np.clip(xs.mean() / sw, 0.3, 0.7)), 0.45]

        os.makedirs(out, exist_ok=True)
        cv2.imwrite(os.path.join(out, "depth.png"), (depth * 65535).astype(np.uint16))
        cv2.imwrite(os.path.join(out, "sky.png"), sky * 255)
        cv2.imwrite(os.path.join(out, "water.png"), water * 255)
        info = {"sky_frac": round(float(sky.mean()), 4), "water_frac": round(float(water.mean()), 4),
                "focus": [round(focus[0], 3), round(focus[1], 3)], "depth": True,
                "size": [w, h]}
        with open(os.path.join(out, "info.json"), "w") as f:
            json.dump(info, f)
        print(f"    {os.path.basename(out).rsplit('-', 1)[0]}: ฟ้า {info['sky_frac']:.0%} น้ำ {info['water_frac']:.0%} โฟกัส {info['focus']}")


# ---------------------------------------------------------------- render

def ease(p):
    return p * p * (3 - 2 * p)


def hex_bgr(c):
    c = c.replace("0x", "").replace("#", "")[:6]
    return (int(c[4:6], 16), int(c[2:4], 16), int(c[0:2], 16))


class Pane:
    """รูปหนึ่งรูปที่มีกล้อง/เอฟเฟกต์ของตัวเอง วาดลงกรอบขนาด pw x ph"""

    def __init__(self, spec, pw, ph, frames, fps):
        self.pw, self.ph, self.frames, self.fps = pw, ph, frames, fps
        self.motion = spec.get("motion", "push")
        self.zoom = float(spec.get("zoom", 0.15))
        fx, fy = spec.get("focus") or [0.5, 0.5]
        orig = cv2.imread(spec["image"], cv2.IMREAD_COLOR)
        if orig is None:
            raise SystemExit(f"อ่านรูปไม่ได้: {spec['image']}")
        oh, ow = orig.shape[:2]
        zmax = 1 + max(self.zoom, 0.22)
        cover = max(pw / ow, ph / oh)
        f = min(1.0, cover * zmax * 1.05)  # ย่อรูปใหญ่ลงเท่าที่ต้องใช้ (เร็วขึ้น ไม่เสียความคม)
        self.src = cv2.resize(orig, (max(2, int(ow * f)), max(2, int(oh * f))), interpolation=cv2.INTER_AREA) if f < 1 else orig
        self.ih, self.iw = self.src.shape[:2]
        self.k = max(pw / self.iw, ph / self.ih)  # สเกลที่รูปพอดีเต็มกรอบ (zoom 1)
        self.fx, self.fy = fx * self.iw, fy * self.ih

        an = spec.get("analysis")
        def load(name, flag=cv2.IMREAD_UNCHANGED):
            p = os.path.join(an, name) if an else None
            if not p or not os.path.exists(p):
                return None
            m = cv2.imread(p, flag)
            return cv2.resize(m, (self.iw, self.ih), interpolation=cv2.INTER_LINEAR) if m is not None else None
        depth = load("depth.png")
        self.depth = None
        self.parallax = float(spec.get("parallax", 1.0))
        if depth is not None and self.parallax > 0:
            d = depth.astype(np.float32) / 65535.0
            ks = max(3, int(min(self.iw, self.ih) * 0.012) | 1)
            self.depth = cv2.GaussianBlur(d, (ks, ks), 0)  # ลดรอยฉีกที่ขอบวัตถุ
        self.water = None
        if spec.get("water"):
            w = load("water.png", cv2.IMREAD_GRAYSCALE)
            if w is not None and w.any():
                self.water = cv2.GaussianBlur(w.astype(np.float32) / 255.0, (0, 0), 3)
        self.sky = None
        if spec.get("sky"):
            s = load("sky.png", cv2.IMREAD_GRAYSCALE)
            if s is not None and s.any():
                self.sky = cv2.GaussianBlur(s.astype(np.float32) / 255.0, (0, 0), 2)[..., None]
                self._sky_plate(s)
        self.sweep = bool(spec.get("sweep"))
        self.phase = float(spec.get("phase", 0.0))
        # ตารางพิกัดของกรอบ (ครึ่งความละเอียด แล้วขยาย — แผนที่พิกัดเรียบ จึงไม่เสียคุณภาพ)
        self.hw, self.hh = max(2, pw // 2), max(2, ph // 2)
        u = (np.arange(self.hw, dtype=np.float32) + 0.5) * (pw / self.hw) - pw / 2
        v = (np.arange(self.hh, dtype=np.float32) + 0.5) * (ph / self.hh) - ph / 2
        self.U, self.V = np.meshgrid(u, v)
        if self.sweep:
            uu, vv = np.meshgrid(np.arange(pw, dtype=np.float32), np.arange(ph, dtype=np.float32))
            self.diag = (uu + 0.55 * vv) / (pw + 0.55 * ph)

    def _sky_plate(self, sky_u8):
        """ภาพฟ้าเต็มแผ่น (เติมส่วนที่เป็นตึกด้วย inpaint) ต่อกับภาพกลับด้าน → เลื่อนได้ไม่มีรอยต่อ"""
        small = cv2.resize(self.src, (max(2, self.iw // 4), max(2, self.ih // 4)), interpolation=cv2.INTER_AREA)
        hole = cv2.resize(255 - sky_u8, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
        hole = cv2.dilate(hole, np.ones((5, 5), np.uint8))
        filled = cv2.inpaint(small, hole, 5, cv2.INPAINT_TELEA)
        filled = cv2.resize(filled, (self.iw, self.ih), interpolation=cv2.INTER_CUBIC)
        plate = np.where(self.sky > 0.5, self.src, filled)
        self.plate = np.hstack([plate, plate[:, ::-1]]).astype(np.float32)
        rows = np.nonzero(self.sky[..., 0].max(axis=1) > 0.01)[0]
        self.sky_rows = (rows.min(), rows.max() + 1)

    def camera(self, p):
        """(cx, cy, zoom) ในพิกัดรูป ที่ความคืบหน้า p (0..1)"""
        e, z, iw, ih = ease(p), self.zoom, self.iw, self.ih
        m = self.motion
        if m == "push":
            Z = 1 + z * e
            cx, cy = iw / 2 + (self.fx - iw / 2) * e, ih / 2 + (self.fy - ih / 2) * e
        elif m == "pull":
            Z = 1 + z * (1 - e)
            cx, cy = self.fx + (iw / 2 - self.fx) * e, self.fy + (ih / 2 - self.fy) * e
        elif m == "rise":
            Z = 1 + max(z, 0.2)
            wh = self.ph / (self.k * Z)
            cx, cy = self.fx, (ih - wh / 2) + (wh / 2 - (ih - wh / 2)) * e
        else:  # pan_left / pan_right: กล้องเลื่อนตามแนวนอน
            ww = self.pw / (self.k * (1 + z * 0.35))
            room = iw - ww
            Z = 1 + z * 0.35 + (0 if room > 0.08 * iw else z * 0.6)  # รูปแคบ: ซูมเพิ่มให้มีที่เลื่อน
            ww = self.pw / (self.k * Z)
            a, b = ww / 2, iw - ww / 2
            cx = a + (b - a) * (e if m == "pan_right" else 1 - e)
            cy = self.fy
        # ไม่ให้กรอบเลยขอบรูป
        ww, wh = self.pw / (self.k * Z), self.ph / (self.k * Z)
        cx = min(max(cx, ww / 2), iw - ww / 2) if iw > ww else iw / 2
        cy = min(max(cy, wh / 2), ih - wh / 2) if ih > wh else ih / 2
        return cx, cy, Z

    def frame(self, n):
        p = n / max(1, self.frames - 1)
        t = n / self.fps + self.phase
        cx, cy, Z = self.camera(p)
        s = 1.0 / (self.k * Z)
        X = cx + self.U * s
        Y = cy + self.V * s
        if self.depth is not None:
            D = cv2.remap(self.depth, X, Y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT) - 0.5
            amp = self.parallax * self.pw * s
            if self.motion in ("push", "pull"):
                # แรงเกินไปขอบตึกจะโค้ง (ทดสอบแล้ว 0.07 โค้งชัด, 0.03 ตรง)
                g = (ease(p) if self.motion == "push" else 1 - ease(p)) * 0.03 * self.parallax
                X = X - (X - cx) * D * g
                Y = Y - (Y - cy) * D * g
            elif self.motion == "rise":
                Y = Y - D * amp * 0.035 * (ease(p) - 0.5)
            else:
                X = X + D * amp * 0.035 * (ease(p) - 0.5) * (1 if self.motion == "pan_right" else -1)
        if self.water is not None:
            Wm = cv2.remap(self.water, X, Y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            if Wm.any():
                a = 1.6 * s  # ประมาณ 1.6 พิกเซลบนจอ
                lam = 0.035 * self.iw
                X = X + Wm * a * 0.6 * np.sin(2 * math.pi * Y / (lam * 1.7) + 2.1 * t)
                Y = Y + Wm * a * np.sin(2 * math.pi * (X / (lam * 2.3) + Y / lam) + 3.3 * t)
        mapx = cv2.resize(X, (self.pw, self.ph), interpolation=cv2.INTER_LINEAR)
        mapy = cv2.resize(Y, (self.pw, self.ph), interpolation=cv2.INTER_LINEAR)
        src = self.src
        if self.sky is not None:
            r0, r1 = self.sky_rows
            shift = int(round(0.008 * self.iw * t)) % (2 * self.iw)
            rolled = np.roll(self.plate[r0:r1], -shift, axis=1)[:, :self.iw]
            src = self.src.copy()
            m = self.sky[r0:r1]
            src[r0:r1] = (src[r0:r1] * (1 - m) + rolled * m).astype(np.uint8)
        out = cv2.remap(src, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if self.sweep:
            q = (t - 0.35) / 1.3  # แถบแสงวิ่งจากมุมซ้ายบน → ขวาล่าง ใน 1.3 วินาที
            if -0.2 < q < 1.2:
                band = np.exp(-((self.diag - (q * 1.4 - 0.2)) ** 2) / (2 * 0.045 ** 2)) * 70
                out = np.clip(out.astype(np.float32) + band[..., None], 0, 255).astype(np.uint8)
        return out


def render_job(job):
    out = job["out"]
    if os.path.exists(out):
        return out
    cv2.setNumThreads(2)
    W, H, fps, frames = job["W"], job["H"], job["fps"], job["frames"]
    split, gap = job.get("split"), 8
    if split == "v":
        rects = [(0, 0, W, (H - gap) // 2), (0, (H - gap) // 2 + gap, W, H - (H - gap) // 2 - gap)]
    elif split == "h":
        rects = [(0, 0, (W - gap) // 2, H), ((W - gap) // 2 + gap, 0, W - (W - gap) // 2 - gap, H)]
    else:
        rects = [(0, 0, W, H)]
    panes = [Pane(sp, r[2], r[3], frames, fps) for sp, r in zip(job["panes"], rects)]
    bg = np.zeros((H, W, 3), np.uint8)
    bg[:] = hex_bgr(job.get("bg", "0x141414"))  # พื้นก่อนรูปที่สองเลื่อนเข้ามา
    if len(rects) > 1:  # เส้นคั่นสีของสไตล์
        if split == "v":
            bg[rects[0][3]:rects[1][1]] = hex_bgr(job.get("accent", "0x111111"))
        else:
            bg[:, rects[0][2]:rects[1][0]] = hex_bgr(job.get("accent", "0x111111"))
    tmp = out + ".part.mp4"
    proc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                             "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p", tmp],
                            stdin=subprocess.PIPE)
    slide = int(0.6 * fps)
    s0 = int((float(job.get("delay", 0)) + 0.1) * fps)  # เริ่มเลื่อนหลังเปลี่ยนภาพเสร็จ ให้เห็นการเลื่อน
    for n in range(frames):
        canvas = bg.copy() if len(panes) > 1 else None
        for k, (pane, (x, y, w, h)) in enumerate(zip(panes, rects)):
            img = pane.frame(n)
            if canvas is None:
                canvas = img
                continue
            if k == 1 and n < s0:
                continue  # ยังไม่ถึงเวลา: เห็นพื้นสีของสไตล์
            if k == 1 and n < s0 + slide:  # รูปที่สองเลื่อนเข้ามา
                off = int((1 - ease((n - s0) / slide)) * (W if split == "v" else W - x))
                if off >= w:
                    continue
                x2, w2 = x + off, w - off
                canvas[y:y + h, x2:x + w] = img[:, :w2]
            else:
                canvas[y:y + h, x:x + w] = img
        proc.stdin.write(canvas.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit(f"สร้างคลิปไม่สำเร็จ: {out}")
    os.replace(tmp, out)
    return out


def render(jobs_path):
    with open(jobs_path, encoding="utf-8") as f:
        jobs = json.load(f)
    todo = [j for j in jobs if not os.path.exists(j["out"])]
    if not todo:
        return
    print(f"  ✦ สร้างภาพเคลื่อนไหว {len(todo)} ฉาก ...")
    workers = max(1, min(len(todo), (os.cpu_count() or 4) // 2))
    if workers == 1:
        for j in todo:
            render_job(j)
        return
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(workers) as ex:
        for _ in ex.map(render_job, todo):
            pass


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if len(sys.argv) >= 3 and sys.argv[1] == "analyze":
        analyze(sys.argv[2:])
    elif len(sys.argv) == 3 and sys.argv[1] == "render":
        render(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
