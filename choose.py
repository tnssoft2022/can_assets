#!/usr/bin/env python3
"""
หน้าเลือกก่อนสร้างวิดีโอ/โปสต์: เลือกสไตล์ (การ์ด), รูปที่จะใช้, รูปหลัก — มีตัวเลือกแนะนำ

    python3 choose.py projects/<โครงการ> [--timeout 20] [--port 8765] [--no-browser]   หน้าเว็บในเครื่อง
    python3 choose.py projects/<โครงการ> --widget [--timeout 20]                       การ์ดในแชตของ Claude
    python3 choose.py projects/<โครงการ> --apply --style S --images a.jpg,b.jpg --main a.jpg

- เปิดหน้าเว็บในเครื่อง (http://localhost:<port>) แสดงการ์ดสไตล์ + รูปย่อจริง
- นับถอยหลัง --timeout วินาที (ค่าเริ่มต้น 20) — ถ้าไม่มีการเลือก ใช้ตัวเลือกแนะนำ
- กดเลือกอะไรก็ตาม → หยุดนับ รอจนกด "ยืนยัน"
- ผลที่เลือกบันทึกลง config.json (style, images, poster_images) แล้วพิมพ์สรุปออกมา จบโปรแกรม

ค่าแนะนำ:
- สไตล์: "recommended_style" ใน config.json (Claude ตั้งให้หลังดูทรัพย์) ไม่มี → เดาจากประเภททรัพย์
- รูปที่ใช้: รูปใน "images" ของ config (รูปใน _excluded_images ไม่ติ๊ก พร้อมเหตุผล)
- รูปหลัก: รูปแรกของ "poster_images" หรือของ "images"
"""
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import make_video as mv

STYLE_INFO = {
    "modern": ("ทันสมัย", "แถบแดงเลือดหมู ตัวหนา จังหวะเร็ว", "คอนโดทั่วไป ห้องเช่า"),
    "luxury": ("หรูหรา", "ขาว-ทอง เงาไล่สี ช้า", "คอนโดหรู บ้านหรู"),
    "minimal": ("มินิมอล", "กล่องขาว ตัวเข้ม สะอาดตา", "ทุกประเภท แบบเรียบ"),
    "bold": ("ป้ายเซล", "เหลือง-ดำ ตัวใหญ่ ราคาเด่น", "ราคาถูก ขายด่วน โปรโมชัน"),
    "nature": ("ธรรมชาติ", "เขียว-ครีม นุ่ม เฟดช้า", "บ้านเดี่ยว บ้านสวน ที่ดิน"),
    "corporate": ("ทางการ", "น้ำเงินกรมท่า-ขาว เรียบ", "อาคารพาณิชย์ ออฟฟิศ โกดัง"),
    "night": ("หรูกลางคืน", "โทนมืด ฟ้าเรืองแสง", "คอนโดหรู เพนท์เฮาส์"),
}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


# ---------------------------------------------------------------- recommendation

def _money(text):
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(ล้าน)?", text.replace("฿", ""))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * 1_000_000 if m.group(2) else v


def recommend_style(cfg):
    """สไตล์แนะนำตามประเภททรัพย์ (ถ้า Claude ตั้ง recommended_style ไว้ ใช้ค่านั้น)"""
    if cfg.get("recommended_style") in mv.THEMES:
        return cfg["recommended_style"], "Claude แนะนำจากการดูทรัพย์"
    text = " ".join([cfg.get("title", ""), cfg.get("location", ""), " ".join(cfg.get("details", []))]).lower()
    price = cfg.get("price", "")
    if re.search(r"ที่ดิน|ที่นา|ไร่|บ้านเดี่ยว|บ้านสวน|วิลล่า|villa", text):
        return "nature", "บ้านเดี่ยว / ที่ดิน"
    if re.search(r"อาคาร|พาณิชย์|ออฟฟิศ|สำนักงาน|โกดัง|โรงงาน|office|building|warehouse", text):
        return "corporate", "อาคารพาณิชย์ / ออฟฟิศ"
    if re.search(r"penthouse|เพนท์เฮาส์", text):
        return "night", "เพนท์เฮาส์"
    v = _money(price) if "ขาย" in price else None
    r = _money(price) if "เช่า" in price else None
    if (v and v >= 10_000_000) or (r and r >= 60_000):
        return "night", "ราคาสูง (คอนโดหรู)"
    if (v and v <= 1_500_000) or (r and r <= 6_000):
        return "bold", "ราคาถูก"
    return "modern", "คอนโด / ห้องเช่าทั่วไป"


def gather(project_dir):
    with open(os.path.join(project_dir, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    img_dir = cfg.get("image_dir") or os.path.join(project_dir, "images")
    if not os.path.isabs(img_dir):
        img_dir = os.path.join(project_dir, img_dir)
    used = [it["file"] for it in cfg.get("images", [])]
    excluded = cfg.get("_excluded_images", {})
    all_files = sorted(f for f in os.listdir(img_dir) if f.lower().endswith(IMAGE_EXT))
    files = used + [f for f in all_files if f not in used]  # รูปที่ใช้ก่อน (ตามลำดับ config) แล้วรูปที่เหลือ
    main = (cfg.get("poster_images") or used or files)[0]
    style, reason = recommend_style(cfg)
    captions = {it["file"]: it.get("caption", "") for it in cfg.get("images", [])}
    images = [{"file": f, "recommended": f in used, "caption": captions.get(f, ""),
               "reason": excluded.get(f, "" if f in used else "ไม่ได้อยู่ในรายการแนะนำ")} for f in files]
    return cfg, img_dir, {"style": style, "style_reason": reason, "main": main, "images": images}


# ---------------------------------------------------------------- apply

def apply_choice(project_dir, cfg, style, chosen, main):
    """บันทึกผลเลือกลง config.json: สไตล์, รูปที่ใช้ (รูปหลักเป็นฉากแรก), รูปของโปสต์"""
    by_file = {it["file"]: dict(it) for it in cfg.get("images", [])}
    old_first = cfg["images"][0]["file"] if cfg.get("images") else None
    # ฉากแรกต้องเป็นบทเปิด (ชื่อ + ราคา) เสมอ → ถ้าเปลี่ยนรูปหลัก ให้สลับคำบรรยาย/บทพากย์กับรูปแรกเดิม
    if old_first and main != old_first and main in by_file:
        a, b = by_file[old_first], by_file[main]
        for key in ("caption", "narration"):
            a[key], b[key] = b.get(key, ""), a.get(key, "")
    order = [main] + [f for f in chosen if f != main]
    cfg["images"] = [by_file.get(f, {"file": f, "caption": ""}) for f in order]
    cfg["style"] = style
    cfg["poster_images"] = order[:4]
    cfg.pop("poster_image", None)
    with open(os.path.join(project_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- chat card (show_widget)

def _b64_thumb(path, width, q):
    import base64
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-vf", f"scale={width}:-2",
                          "-q:v", str(q), "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-"],
                         capture_output=True, check=True).stdout
    return "data:image/jpeg;base64," + base64.b64encode(out).decode()


def widget_html(project_dir, cfg, img_dir, rec, timeout):
    """การ์ดเลือกสำหรับแสดงในแชต (show_widget) — ส่งคำตอบกลับด้วย sendPrompt"""
    name = os.path.basename(project_dir)
    brand = mv.load_brand()
    main_bg = _b64_thumb(os.path.join(img_dir, rec["main"]), 160, 9)
    cards = []
    for key, th in mv.THEMES.items():
        acc = th["accent_color"]
        b_acc = brand.get("accent_color", {})
        if isinstance(b_acc, dict) and b_acc.get(key):
            acc = b_acc[key]
        light = th.get("light")
        panel = css_color(th.get("panel") or ("0xF7F5F2" if light else "0x141414"), acc)
        tbg, tc = css_color(th["box"], acc), css_color(th["text"], acc)
        pbg = css_color(th.get("outro_price_box") if light else th["price_box"], acc)
        pc = css_color(th["outro_price"] if light else th["price_color"], acc)
        sname, desc, fit = STYLE_INFO.get(key, (key, "", ""))
        is_rec = key == rec["style"]
        badge = '<span class="bd">แนะนำ</span>' if is_rec else ""
        cards.append(
            f'<button type="button" class="st{" on" if is_rec else ""}" data-s="{key}">{badge}'
            f'<div class="mk" style="background:{panel}"><div class="mi">'
            f'<span style="background:{tbg};color:{tc}">ชื่อโครงการ</span></div>'
            f'<span class="mp" style="background:{pbg};color:{pc}">ราคา</span></div>'
            f'<div class="sn">{sname}</div><div class="sd">{fit}</div></button>')
    tiles = []
    for i, im in enumerate(rec["images"], 1):
        src = _b64_thumb(os.path.join(img_dir, im["file"]), 120, 12)
        note = im["caption"] if im["recommended"] else im["reason"]
        star = " ★" if im["file"] == rec["main"] else ""
        tiles.append(
            f'<div class="tl{"" if im["recommended"] else " off"}" data-f="{im["file"]}">'
            f'<img src="{src}" alt="{im["file"]}">'
            f'<label><input type="checkbox" class="u"{" checked" if im["recommended"] else ""}> ใช้</label>'
            f'<label><input type="radio" name="mn" value="{im["file"]}"{" checked" if im["file"] == rec["main"] else ""}> หลัก{star}</label>'
            f'<div class="nt">{i}. {note or im["file"]}</div></div>')
    rec_imgs = [i["file"] for i in rec["images"] if i["recommended"]]
    js_rec = json.dumps({"style": rec["style"], "images": rec_imgs, "main": rec["main"]}, ensure_ascii=False)
    sname = STYLE_INFO.get(rec["style"], (rec["style"],))[0]
    return f"""<h2 class="sr-only">เลือกสไตล์ รูปที่ใช้ และรูปหลัก ของ {cfg.get('title', '')}</h2>
<style>
.st{{position:relative;text-align:left;padding:8px;border-radius:12px;border:0.5px solid var(--border);background:var(--surface-2);cursor:pointer}}
.st.on{{border:2px solid var(--border-accent)}} .bd{{position:absolute;top:-9px;right:8px;background:var(--bg-accent);color:var(--text-accent);font-size:11px;padding:2px 8px;border-radius:var(--radius)}}
.mk{{border-radius:6px;overflow:hidden;height:92px;display:flex;flex-direction:column}} .mi{{flex:1;background:url({main_bg}) center/cover;display:flex;align-items:flex-end;padding:4px}}
.mi span,.mp{{font-size:11px;font-weight:500;padding:1px 5px;border-radius:3px}} .mp{{margin:4px;align-self:flex-start}}
.sn{{font-size:13px;font-weight:500;margin-top:6px;color:var(--text-primary)}} .sd{{font-size:11px;color:var(--text-secondary)}}
.tl{{border:0.5px solid var(--border);border-radius:12px;padding:6px;background:var(--surface-2)}} .tl.off{{opacity:.6}}
.tl img{{width:100%;height:76px;object-fit:cover;border-radius:6px;display:block}} .tl label{{font-size:12px;margin-right:8px;color:var(--text-primary)}}
.nt{{font-size:11px;color:var(--text-secondary)}} .gr{{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(120px,1fr))}}
</style>
<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:4px 0 12px">
<span id="cd" style="flex:1;font-size:14px;color:var(--text-secondary)"></span><span id="er" style="font-size:13px;color:var(--text-danger)"></span>
<button type="button" id="ur">ใช้ค่าแนะนำ ↗</button><button type="button" id="ok">ยืนยัน ↗</button></div>
<p style="font-size:13px;color:var(--text-secondary);margin:0 0 8px">สไตล์ — แนะนำ: {sname} ({rec['style_reason']})</p>
<div class="gr" id="sts">{''.join(cards)}</div>
<p style="font-size:13px;color:var(--text-secondary);margin:16px 0 8px">รูปที่ใช้ และรูปหลัก (ฉากแรก + รูปใหญ่ในโปสต์)</p>
<div class="gr">{''.join(tiles)}</div>
<script>
const R={js_rec},P={json.dumps(name, ensure_ascii=False)};let left={timeout},paused=false,sent=false;
const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
function tick(){{if(sent)return;if(paused){{q('#cd').textContent='หยุดนับแล้ว — กด ยืนยัน เมื่อพร้อม';return}}
q('#cd').textContent='ใช้ค่าแนะนำใน '+left+' วินาที';if(left<=0){{send(R,true);return}}left--;setTimeout(tick,1000)}}
function pause(){{if(!paused){{paused=true;tick()}}}}
function cur(){{const st=(q('.st.on')||{{dataset:{{s:R.style}}}}).dataset.s;const im=qa('.tl').filter(t=>t.querySelector('.u').checked).map(t=>t.dataset.f);
const m=q('input[name=mn]:checked');return{{style:st,images:im,main:m?m.value:im[0]}}}}
function send(c,auto){{if(!c.images.length){{q('#er').textContent='เลือกรูปอย่างน้อย 1 รูป';return}}
if(!c.images.includes(c.main)){{q('#er').textContent='รูปหลักต้องเป็นรูปที่ติ๊ก ใช้';return}}
sent=true;q('#cd').textContent=auto?'ใช้ค่าแนะนำแล้ว':'ส่งตัวเลือกแล้ว';
sendPrompt('เลือกแล้ว ['+P+'] สไตล์: '+c.style+' | รูป: '+c.images.join(', ')+' | รูปหลัก: '+c.main+(auto?' (ค่าแนะนำ — หมดเวลา)':''))}}
qa('.st').forEach(b=>b.onclick=()=>{{pause();qa('.st').forEach(x=>x.classList.remove('on'));b.classList.add('on')}});
qa('.u').forEach(c=>c.onchange=()=>{{pause();q('#er').textContent='';c.closest('.tl').classList.toggle('off',!c.checked);
const m=q('input[name=mn]:checked');if(m&&!m.closest('.tl').querySelector('.u').checked){{const f=qa('.tl').find(t=>t.querySelector('.u').checked);if(f)f.querySelector('input[name=mn]').checked=true}}}});
qa('input[name=mn]').forEach(r=>r.onchange=()=>{{pause();q('#er').textContent='';const b=r.closest('.tl').querySelector('.u');if(!b.checked){{b.checked=true;b.onchange()}}}});
q('#ok').onclick=()=>send(cur(),false);q('#ur').onclick=()=>send(R,false);tick();
</script>"""


# ---------------------------------------------------------------- page

def css_color(c, accent):
    """'0xRRGGBB@0.9' / 'white@0.8' / 'accent@1.0' → CSS rgba()"""
    if not c:
        return "transparent"
    c = c.replace("accent", accent)
    col, _, a = c.partition("@")
    a = float(a) if a else 1.0
    if col == "white":
        r = g = b = 255
    elif col == "black":
        r = g = b = 0
    else:
        h = col.replace("0x", "")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def style_cards(cfg, rec):
    brand = mv.load_brand()
    cards = []
    for key, th in mv.THEMES.items():
        acc = th["accent_color"]
        b_acc = brand.get("accent_color", {})
        if isinstance(b_acc, dict) and b_acc.get(key):
            acc = b_acc[key]
        name, desc, fit = STYLE_INFO.get(key, (key, "", ""))
        panel = css_color(th.get("panel") or ("0xF7F5F2" if th.get("light") else "0x141414"), acc)
        title_bg = css_color(th["box"], acc)
        title_c = css_color(th["text"], acc)
        price_bg = css_color(th["price_box"] if not th.get("light") else th.get("outro_price_box"), acc)
        price_c = css_color(th["price_color"] if not th.get("light") else th["outro_price"], acc)
        shade = "linear-gradient(transparent 40%, rgba(0,0,0,.65))" if th.get("gradient") else "none"
        badge = '<span class="badge">แนะนำ</span>' if key == rec["style"] else ""
        cards.append(f"""
<button class="style{' sel' if key == rec['style'] else ''}" data-style="{key}">
  {badge}
  <div class="mock" style="background:{panel}">
    <div class="mimg" style="background-image:{shade}, url('/img/{rec['main']}')">
      <span class="mtitle" style="background:{title_bg};color:{title_c}">{cfg.get('title', '')[:22]}</span>
    </div>
    <span class="mprice" style="background:{price_bg};color:{price_c}">{cfg.get('price', '')[:18]}</span>
  </div>
  <div class="sname">{name} <code>{key}</code></div>
  <div class="sdesc">{desc}</div>
  <div class="sfit">เหมาะกับ: {fit}</div>
</button>""")
    return "".join(cards)


def image_cards(rec):
    out = []
    for i, im in enumerate(rec["images"], 1):
        chk = "checked" if im["recommended"] else ""
        note = im["caption"] if im["recommended"] else im["reason"]
        out.append(f"""
<div class="img{' off' if not im['recommended'] else ''}" data-file="{im['file']}">
  <img src="/img/{im['file']}" loading="lazy">
  <label class="use"><input type="checkbox" class="usebox" {chk}> ใช้รูปนี้</label>
  <label class="main"><input type="radio" name="main" value="{im['file']}" {'checked' if im['file'] == rec['main'] else ''}> รูปหลัก{' ★' if im['file'] == rec['main'] else ''}</label>
  <div class="note">{i}. {im['file']}{' — ' + note if note else ''}</div>
</div>""")
    return "".join(out)


PAGE = """<!doctype html><html lang="th"><head><meta charset="utf-8">
<title>เลือกสไตล์และรูป — {title}</title>
<style>
body{{font-family:-apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f5f2;color:#222}}
header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:12px 20px;display:flex;gap:16px;align-items:center;z-index:5}}
header h1{{font-size:18px;margin:0;flex:1}} #count{{font-size:15px;color:#a3172f;font-weight:600}}
button.act{{font-size:15px;padding:8px 16px;border-radius:8px;border:1px solid #bbb;background:#fff;cursor:pointer}}
button.primary{{background:#a3172f;color:#fff;border-color:#a3172f}}
main{{padding:16px 20px 40px}} h2{{font-size:16px;margin:22px 0 4px}} .hint{{color:#666;font-size:13px;margin:0 0 10px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}}
.style{{position:relative;text-align:left;background:#fff;border:2px solid #e2e0da;border-radius:12px;padding:10px;cursor:pointer;font:inherit}}
.style.sel{{border-color:#a3172f;box-shadow:0 0 0 3px rgba(163,23,47,.15)}}
.badge{{position:absolute;top:-9px;right:10px;background:#a3172f;color:#fff;font-size:11px;padding:2px 8px;border-radius:10px}}
.mock{{border-radius:8px;overflow:hidden;height:150px;display:flex;flex-direction:column}}
.mimg{{flex:1;background-size:cover;background-position:center;display:flex;align-items:flex-end;padding:6px}}
.mtitle{{font-size:11px;padding:2px 5px;border-radius:3px;font-weight:600}}
.mprice{{margin:6px;align-self:flex-start;font-size:12px;font-weight:700;padding:3px 7px;border-radius:3px}}
.sname{{font-weight:600;margin-top:8px;font-size:14px}} .sname code{{font-size:11px;color:#888}}
.sdesc,.sfit{{font-size:12px;color:#666}}
.imgs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}}
.img{{background:#fff;border:2px solid #e2e0da;border-radius:12px;padding:8px}} .img.off{{opacity:.55}}
.img img{{width:100%;height:140px;object-fit:cover;border-radius:6px;display:block}}
.img label{{display:inline-flex;gap:4px;align-items:center;font-size:13px;margin:6px 10px 0 0;cursor:pointer}}
.note{{font-size:12px;color:#666;margin-top:4px}} #err{{color:#c00;font-size:13px}}
#done{{display:none;padding:40px;text-align:center;font-size:18px}}
</style></head><body>
<header><h1>เลือกสไตล์และรูป — {title}</h1>
<span id="count"></span><span id="err"></span>
<button class="act" id="useRec">ใช้ค่าแนะนำ</button>
<button class="act primary" id="ok">ยืนยัน</button></header>
<main id="form">
<h2>1. สไตล์</h2><p class="hint">แนะนำ: <b>{rec_style_name}</b> ({style_reason})</p>
<div class="grid">{styles}</div>
<h2>2. รูปที่จะใช้ และ 3. รูปหลัก</h2>
<p class="hint">ติ๊ก "ใช้รูปนี้" ให้รูปที่ต้องการ (เรียงตามลำดับ) • รูปหลัก = ฉากแรกของวิดีโอ + รูปใหญ่ในโปสต์ (★ = แนะนำ)</p>
<div class="imgs">{images}</div>
</main>
<div id="done"></div>
<script>
const REC = {rec_json};
let left = {timeout}, paused = false, sent = false;
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
function tick() {{
  if (sent) return;
  if (paused) {{ $('#count').textContent = 'หยุดนับแล้ว — กด "ยืนยัน" เมื่อพร้อม'; return; }}
  $('#count').textContent = 'ใช้ค่าแนะนำใน ' + left + ' วินาที';
  if (left <= 0) {{ send(current(true), true); return; }}
  left--; setTimeout(tick, 1000);
}}
function pause() {{ if (!paused) {{ paused = true; tick(); }} }}
function current(rec) {{
  if (rec) return {{style: REC.style, images: REC.images.filter(i => i.recommended).map(i => i.file), main: REC.main}};
  const style = ($('.style.sel') || {{}}).dataset?.style || REC.style;
  const images = $$('.img').filter(d => d.querySelector('.usebox').checked).map(d => d.dataset.file);
  const m = $('input[name=main]:checked');
  return {{style, images, main: m ? m.value : images[0]}};
}}
function send(c, auto) {{
  if (!c.images.length) {{ $('#err').textContent = 'เลือกรูปอย่างน้อย 1 รูป'; return; }}
  if (!c.images.includes(c.main)) {{ $('#err').textContent = 'รูปหลักต้องเป็นรูปที่ติ๊ก "ใช้รูปนี้"'; return; }}
  sent = true; c.auto = !!auto;
  fetch('/select', {{method: 'POST', body: JSON.stringify(c)}}).then(() => {{
    $('#form').style.display = 'none'; $('header').style.display = 'none';
    $('#done').style.display = 'block';
    $('#done').textContent = (auto ? 'ใช้ค่าแนะนำแล้ว' : 'บันทึกแล้ว') + ' — สไตล์ ' + c.style + ', ' + c.images.length + ' รูป, รูปหลัก ' + c.main + ' (ปิดหน้านี้ได้)';
  }});
}}
$$('.style').forEach(b => b.onclick = () => {{ pause(); $$('.style').forEach(x => x.classList.remove('sel')); b.classList.add('sel'); }});
$$('.usebox').forEach(c => c.onchange = () => {{ pause(); $('#err').textContent = '';
  c.closest('.img').classList.toggle('off', !c.checked);
  const m = $('input[name=main]:checked');
  if (m && !m.closest('.img').querySelector('.usebox').checked) {{
    const first = $$('.img').find(d => d.querySelector('.usebox').checked);
    if (first) first.querySelector('input[name=main]').checked = true;
  }}
}});
$$('input[name=main]').forEach(r => r.onchange = () => {{ pause(); $('#err').textContent = '';
  const box = r.closest('.img').querySelector('.usebox'); if (!box.checked) {{ box.checked = true; box.onchange(); }} }});
$('#ok').onclick = () => send(current(false), false);
$('#useRec').onclick = () => send(current(true), false);
tick();
</script></body></html>"""


def main():
    argv = sys.argv[1:]
    opts = {"timeout": 20, "port": 8765, "browser": True}
    if "--no-browser" in argv:
        argv.remove("--no-browser")
        opts["browser"] = False
    for flag in ("--timeout", "--port"):
        if flag in argv:
            i = argv.index(flag)
            opts[flag[2:]] = int(argv[i + 1])
            del argv[i:i + 2]
    mode = "page"
    for flag in ("--widget", "--apply"):
        if flag in argv:
            argv.remove(flag)
            mode = flag[2:]
    picked = {}
    for flag in ("--style", "--images", "--main"):
        if flag in argv:
            i = argv.index(flag)
            picked[flag[2:]] = argv[i + 1]
            del argv[i:i + 2]
    if not argv:
        print(__doc__)
        sys.exit(1)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    project_dir = os.path.abspath(argv[0])
    cfg, img_dir, rec = gather(project_dir)

    if mode == "widget":  # พิมพ์ HTML ของการ์ดในแชต
        print(widget_html(project_dir, cfg, img_dir, rec, opts["timeout"]))
        return
    if mode == "apply":  # บันทึกผลที่เลือกจากการ์ดในแชต
        files = [i["file"] for i in rec["images"]]
        style = picked.get("style") if picked.get("style") in mv.THEMES else rec["style"]
        chosen = [f.strip() for f in picked.get("images", "").split(",") if f.strip() in files] \
            or [i["file"] for i in rec["images"] if i["recommended"]]
        main_img = picked.get("main") if picked.get("main") in chosen else chosen[0]
        apply_choice(project_dir, cfg, style, chosen, main_img)
        print(f"✓ บันทึกแล้ว: สไตล์ {style} | รูป {', '.join([main_img] + [f for f in chosen if f != main_img])} "
              f"| รูปหลัก {main_img}")
        return
    thumb_dir = os.path.join(project_dir, "cache", "thumbs")
    os.makedirs(thumb_dir, exist_ok=True)

    page = PAGE.format(
        title=cfg.get("title", ""), styles=style_cards(cfg, rec), images=image_cards(rec),
        rec_style_name=STYLE_INFO.get(rec["style"], (rec["style"],))[0], style_reason=rec["style_reason"],
        rec_json=json.dumps(rec, ensure_ascii=False), timeout=opts["timeout"])
    result = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if self.path.startswith("/img/"):
                name = os.path.basename(unquote(self.path[5:]))
                src = os.path.join(img_dir, name)
                if not os.path.exists(src):
                    return self._send(404, b"not found", "text/plain")
                thumb = os.path.join(thumb_dir, os.path.splitext(name)[0] + ".jpg")
                if not os.path.exists(thumb):
                    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                                    "-vf", "scale=480:-2", "-q:v", "4", thumb], check=False)
                with open(thumb, "rb") as f:
                    return self._send(200, f.read(), "image/jpeg")
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/select":
                return self._send(404, b"", "text/plain")
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            result.update(data)
            self._send(200, b"ok", "text/plain")
            done.set()

    server = None
    for port in range(opts["port"], opts["port"] + 20):  # พอร์ตไม่ว่าง → ลองพอร์ตถัดไป
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if not server:
        sys.exit(f"ไม่มีพอร์ตว่างระหว่าง {opts['port']}–{opts['port'] + 19}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://localhost:{port}/"
    print(f"หน้าเลือก: {url}", flush=True)
    print(f"แนะนำ: สไตล์ {rec['style']} ({rec['style_reason']}), "
          f"{sum(i['recommended'] for i in rec['images'])} รูป, รูปหลัก {rec['main']}", flush=True)
    if opts["browser"]:
        webbrowser.open(url)
    # รอผลเลือก (หน้าเว็บนับถอยหลังเอง) — กันค้างตลอดไป: ไม่มีใครเปิดหน้าเลย 10 นาที → ใช้ค่าแนะนำ
    if not done.wait(timeout=600):
        result.update({"style": rec["style"], "main": rec["main"], "auto": True,
                       "images": [i["file"] for i in rec["images"] if i["recommended"]]})
        print("ไม่มีการเปิดหน้าเลือกภายใน 10 นาที — ใช้ค่าแนะนำ")
    server.shutdown()

    style = result.get("style") if result.get("style") in mv.THEMES else rec["style"]
    chosen = [f for f in result.get("images", []) if any(f == i["file"] for i in rec["images"])]
    main_img = result.get("main") if result.get("main") in chosen else (chosen or [rec["main"]])[0]
    apply_choice(project_dir, cfg, style, chosen or [main_img], main_img)
    how = "ค่าแนะนำ (หมดเวลา)" if result.get("auto") else "ผู้ใช้เลือก"
    print(f"✓ {how}: สไตล์ {style} | รูป {', '.join([main_img] + [f for f in chosen if f != main_img])} "
          f"| รูปหลัก {main_img}")
    print(json.dumps({"style": style, "images": chosen, "main": main_img, "auto": bool(result.get("auto"))},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
