#!/usr/bin/env python3
"""
สร้างเพลงประกอบ (แต่งขึ้นใหม่ด้วยการสังเคราะห์เสียง — ไม่มีปัญหาลิขสิทธิ์) แยกตามสไตล์

    python3 make_music.py            สร้างครบทุกสไตล์ → brand/music/<สไตล์>.mp3
    python3 make_music.py modern     สร้างเฉพาะสไตล์ที่ระบุ

- luxury  : เปียโนนุ่ม ๆ คอร์ดแจ๊ส ช้า ไม่มีกลอง
- modern  : จังหวะสนุก เบส + อาร์เปจจิโอ + กลองเบา ๆ
- minimal : กีตาร์ดีดเบา ๆ (สังเคราะห์) + เชคเกอร์

ความยาวประมาณ 64 วินาที (ระบบวนเพลงเองถ้าวิดีโอยาวกว่า) — ทำเสียงเบาลงอัตโนมัติตอนมีเสียงพากย์
"""
import array
import math
import os
import random
import subprocess
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "brand", "music")
SR = 32000

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def freq(name, octave):
    return 440.0 * 2 ** ((NOTE[name] + 12 * (octave + 1) - 69) / 12)


def chord(root, kind, octave=3):
    steps = {"maj": [0, 4, 7], "min": [0, 3, 7], "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10],
             "6": [0, 4, 7, 9], "add9": [0, 4, 7, 14]}[kind]
    base = NOTE[root] + 12 * (octave + 1)
    return [440.0 * 2 ** ((base + s - 69) / 12) for s in steps]


STYLES = {
    "luxury": {
        "bpm": 68, "bars": 18,
        "prog": [("C", "maj7"), ("A", "min7"), ("F", "maj7"), ("G", "6")],
        "pad": 0.10, "arp": 0.16, "arp_div": 2, "bass": 0.10, "drums": None, "tone": "piano",
    },
    "modern": {
        "bpm": 110, "bars": 30,
        "prog": [("C", "add9"), ("G", "maj"), ("A", "min"), ("F", "maj7")],
        "pad": 0.07, "arp": 0.11, "arp_div": 4, "bass": 0.18, "drums": "pop", "tone": "pluck",
    },
    "minimal": {
        "bpm": 88, "bars": 24,
        "prog": [("G", "maj"), ("D", "maj"), ("E", "min7"), ("C", "add9")],
        "pad": 0.05, "arp": 0.15, "arp_div": 4, "bass": 0.09, "drums": "shaker", "tone": "guitar",
    },
}


def add_tone(buf, start, dur, f, amp, tone):
    """เขียนโน้ตหนึ่งตัวลงใน buf (เสียงแบบเปียโน / pluck / กีตาร์)"""
    n0 = int(start * SR)
    n = int(dur * SR)
    if n0 >= len(buf):
        return
    n = min(n, len(buf) - n0)
    two_pi_f = 2 * math.pi * f / SR
    if tone == "piano":
        decay, harm = 2.2, (1.0, 0.45, 0.18, 0.08)
    elif tone == "guitar":
        decay, harm = 3.5, (1.0, 0.6, 0.35, 0.2, 0.1)
    else:  # pluck
        decay, harm = 6.0, (1.0, 0.5, 0.3, 0.15)
    attack = int(0.006 * SR)
    for i in range(n):
        env = math.exp(-decay * i / SR)
        if i < attack:
            env *= i / attack
        if i > n - 400:  # กันเสียงคลิกตอนจบโน้ต
            env *= (n - i) / 400
        ph = two_pi_f * i
        s = 0.0
        for k, h in enumerate(harm, 1):
            s += h * math.sin(ph * k)
        buf[n0 + i] += amp * env * s


def add_pad(buf, start, dur, freqs, amp):
    """คอร์ดยาว ๆ นุ่ม ๆ (ค่อย ๆ ดังขึ้น/เบาลง)"""
    n0, n = int(start * SR), int(dur * SR)
    n = min(n, len(buf) - n0)
    fade = int(0.35 * SR)
    steps = [2 * math.pi * f / SR for f in freqs]
    detune = [2 * math.pi * f * 1.003 / SR for f in freqs]
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        s = 0.0
        for a, b in zip(steps, detune):
            s += math.sin(a * i) + 0.6 * math.sin(b * i)
        buf[n0 + i] += amp * env * s / len(freqs)


def add_kick(buf, start, amp):
    n0, n = int(start * SR), int(0.28 * SR)
    n = min(n, len(buf) - n0)
    ph = 0.0
    for i in range(n):
        t = i / SR
        f = 45 + 90 * math.exp(-t * 28)
        ph += 2 * math.pi * f / SR
        buf[n0 + i] += amp * math.exp(-t * 11) * math.sin(ph)


def add_noise_hit(buf, start, dur, amp, rng):
    n0, n = int(start * SR), int(dur * SR)
    n = min(n, len(buf) - n0)
    prev = 0.0
    for i in range(n):
        w = rng.uniform(-1, 1)
        hp = w - prev  # high-pass แบบง่าย ให้เสียงแหลมเหมือนไฮแฮต/เชคเกอร์
        prev = w
        buf[n0 + i] += amp * math.exp(-i / SR * (60 if dur < 0.08 else 25)) * hp


def lowpass(buf, cutoff):
    a = 1 - math.exp(-2 * math.pi * cutoff / SR)
    y = 0.0
    for i in range(len(buf)):
        y += a * (buf[i] - y)
        buf[i] = y


def render_style(name):
    st = STYLES[name]
    beat = 60.0 / st["bpm"]
    bar = beat * 4
    total = st["bars"] * bar
    buf = array.array("d", bytes(8 * int(total * SR + SR)))
    rng = random.Random(7)
    prog = st["prog"]

    for b in range(st["bars"]):
        root, kind = prog[b % len(prog)]
        t0 = b * bar
        chord_f = chord(root, kind, 3)
        add_pad(buf, t0, bar + 0.05, chord_f, st["pad"])
        # เบส: โน้ตตัวแรกของคอร์ด
        bass_f = freq(root, 2)
        if st["drums"] == "pop":
            for k in (0, 1.5, 2, 3.5):
                add_tone(buf, t0 + k * beat, beat * 0.9, bass_f, st["bass"], "pluck")
        else:
            add_tone(buf, t0, bar, bass_f, st["bass"], st["tone"])
            add_tone(buf, t0 + 2 * beat, bar / 2, bass_f, st["bass"] * 0.7, st["tone"])
        # อาร์เปจจิโอ
        arp = chord(root, kind, 4)
        pattern = [0, 1, 2, 1, 3 % len(arp), 2, 1, 2] if len(arp) > 3 else [0, 1, 2, 1, 0, 2, 1, 2]
        div = st["arp_div"]
        steps = 4 * div // 2 if div == 2 else 8
        step_len = bar / steps
        for k in range(steps):
            # เว้นช่วงแรก 2 ห้องให้เพลงค่อย ๆ เริ่ม
            if b < 2 and k % 2:
                continue
            add_tone(buf, t0 + k * step_len, step_len * 2.2, arp[pattern[k % len(pattern)] % len(arp)],
                     st["arp"] * (1.0 if k % 2 == 0 else 0.7), st["tone"])
        # กลอง
        if st["drums"] == "pop" and 1 < b < st["bars"] - 1:
            for k in range(4):
                add_kick(buf, t0 + k * beat, 0.32 if k in (0, 2) else 0.18)
                add_noise_hit(buf, t0 + (k + 0.5) * beat, 0.05, 0.05, rng)
            add_noise_hit(buf, t0 + beat, 0.12, 0.06, rng)
            add_noise_hit(buf, t0 + 3 * beat, 0.12, 0.06, rng)
        elif st["drums"] == "shaker" and 0 < b < st["bars"] - 1:
            for k in range(8):
                add_noise_hit(buf, t0 + k * beat / 2, 0.07, 0.035 if k % 2 else 0.05, rng)

    lowpass(buf, 6500 if name == "modern" else 4500)
    peak = max(abs(x) for x in buf) or 1.0
    gain = 0.7 / peak
    # ค่อย ๆ จางตอนจบ 3 วินาที
    n_end = int(total * SR)
    fade = 3 * SR
    pcm = array.array("h", bytes(2 * n_end))
    for i in range(n_end):
        g = gain * min(1.0, (n_end - i) / fade)
        pcm[i] = int(max(-1.0, min(1.0, buf[i] * g)) * 32767)
    return pcm, total


def make(name):
    os.makedirs(OUT_DIR, exist_ok=True)
    pcm, total = render_style(name)
    wav = os.path.join(OUT_DIR, f"{name}.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    mp3 = os.path.join(OUT_DIR, f"{name}.mp3")
    # สเตอริโอแบบกว้างนิดหน่อย + ปรับความดังให้เท่ากันทุกเพลง
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav,
                    "-af", "aecho=0.8:0.6:40:0.25,loudnorm=I=-20:TP=-2:LRA=11,aresample=44100",
                    "-ac", "2", "-c:a", "libmp3lame", "-b:a", "160k", mp3], check=True)
    os.remove(wav)
    print(f"✓ เพลง {name}: {mp3} ({total:.0f} วินาที)")
    return mp3


def main():
    names = sys.argv[1:] or list(STYLES)
    for n in names:
        if n not in STYLES:
            sys.exit(f"สไตล์ต้องเป็น: {', '.join(STYLES)}")
        make(n)


if __name__ == "__main__":
    main()
