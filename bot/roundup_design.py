"""
7 Seas News — roundup design (APPROVED, Nov 2026). Do not change numbers here without the owner.

This file is the single source of truth for how the daily roundup looks:
  - make_cover()        TikTok cover, 1080×1350
  - cover_9x16()        YouTube/Facebook cover + first video frame, 1080×1920
  - story_canvas()      1080×1920 story frame built from the bot's 1080×1350 post (no headline)
  - draw_counter()      thin red progress line + "01 / 13" pill
  - typing_frame()      headline typed so far + red cursor
  - wipe()              red swipe transition
  - end_frame()         last frame "FOLLOW FOR MORE", 1080×1920
  - build_audio()       boom / typing clicks / whoosh (synthesized, no music files)
  - TIMING              all durations

Everything is drawn with Pillow at the final size. Fonts: Poppins Bold / SemiBold / Medium (.ttf).
"""
import math
import os
import random
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- sizes & colours
W = 1080
POST_H = 1350          # TikTok cover / post / slide
VID_H = 1920           # YouTube + Facebook video, cover, frames
OY = 285               # where the 1080×1350 post sits inside the 1080×1920 frame
M = 64                 # left/right margin

RED = (206, 0, 0)      # #CE0000
BLACK = (8, 8, 9)
CHARCOAL = (26, 26, 29)
WHITE = (255, 255, 255)
SOFT = (205, 205, 210)
FILL_TOP_9x16 = None   # computed from the cover itself (≈ 25,25,27)
FILL_BOTTOM_9x16 = (8, 8, 8)

FPS = 30
TIMING = {
    "cover_hold_s": 1.3,        # opening cover, then red swipe out
    "wipe_frames": 8,           # each way (in / out), smoothstep easing
    "type_s_per_char": 0.028,   # typing speed
    "type_min_s": 1.4,
    "type_max_s": 2.4,
    "hold_s": 2.2,              # full headline stays on screen
    "cursor_blink_frames": 9,   # cursor on/off every 9 frames …
    "cursor_blink_until": 36,   # … only for the first 36 frames of the hold
    "end_hold_s": 2.6,          # last frame
}

_font_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")


def set_font_dir(path):
    global _font_dir
    _font_dir = path


def font(weight, size):
    """weight: 'Bold' | 'SemiBold' | 'Medium'"""
    return ImageFont.truetype(os.path.join(_font_dir, f"Poppins-{weight}.ttf"), size)


def _spaced(d, xy, text, f, fill, spacing):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + spacing


def _spaced_width(d, text, f, spacing):
    return sum(d.textlength(c, font=f) + spacing for c in text) - spacing


def _vertical_fade(h, a_bottom, y0, y1):
    """Mask: 0 above y0, ramps to a_bottom at y1, stays a_bottom below."""
    m = Image.new("L", (W, h), 0)
    d = ImageDraw.Draw(m)
    for y in range(y0, h):
        a = a_bottom if y > y1 else int(a_bottom * (y - y0) / (y1 - y0))
        d.line([(0, y), (W, y)], fill=a)
    return m


# ---------------------------------------------------------------- cover background
GLOBE = {"cx": W // 2 + 160, "cy": 520, "r": 480}
COVER_PINS = [(-120, -60), (40, 60), (-260, 120), (150, -170), (-40, -230)]   # offsets from globe centre


def cover_background():
    """Charcoal→black gradient + faint globe grid + 40 dots + 5 red news pins + bottom fade. 1080×1350."""
    h = POST_H
    bg = Image.new("RGB", (W, h), BLACK)
    d = ImageDraw.Draw(bg)
    for y in range(h):
        k = y / h
        d.line([(0, y), (W, y)], fill=tuple(int(CHARCOAL[i] * (1 - k) + BLACK[i] * k) for i in range(3)))

    cx, cy, r = GLOBE["cx"], GLOBE["cy"], GLOBE["r"]
    layer = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    line = (255, 255, 255, 26)
    g.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 50), width=3)
    for lon in range(15, 90, 15):
        hw = r * math.cos(math.radians(lon))
        g.ellipse([cx - hw, cy - r, cx + hw, cy + r], outline=line, width=2)
    g.line([(cx, cy - r), (cx, cy + r)], fill=line, width=2)
    for lat in range(-75, 90, 15):
        y = cy + r * math.sin(math.radians(lat))
        hw = r * math.cos(math.radians(lat))
        g.line([(cx - hw, y), (cx + hw, y)], fill=line, width=2)
    rnd = random.Random(7)                      # fixed seed → same dots every time
    for _ in range(40):
        a, rr = rnd.uniform(0, 6.28), r * math.sqrt(rnd.uniform(0, 1))
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        g.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 255, 255, 60))
    bg.paste(layer, (0, 0), layer.filter(ImageFilter.GaussianBlur(0.6)))

    pins = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(pins)
    for dx, dy in COVER_PINS:
        x, y = cx + dx, cy + dy
        for rr, a in ((46, 40), (28, 80)):
            g.ellipse([x - rr, y - rr, x + rr, y + rr], outline=RED + (a,), width=3)
        g.ellipse([x - 10, y - 10, x + 10, y + 10], fill=RED + (255,))
        g.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 255, 255, 255))
    bg.paste(pins, (0, 0), pins)

    bg.paste(Image.new("RGB", (W, h), BLACK), (0, 0), _vertical_fade(h, 245, int(h * .38), int(h * .70)))
    return bg


def paste_logo(img, logo_path, x=M, y=M, width=330):
    logo = Image.open(logo_path).convert("RGBA")
    logo = logo.resize((width, int(logo.height * width / logo.width)), Image.LANCZOS)
    img.paste(logo, (x, y), logo)


# ---------------------------------------------------------------- cover (1080×1350)
HOOK_FONT = 46
HOOK_MAX_W = W - 2 * M - 30          # 922 px: one hook sentence must fit one line


def split_hook(hook, d=None):
    """Hook = 2 short sentences. One line if it fits, else split at the first '. '.
    Returns list of lines. Raises ValueError if a line still does not fit
    (then ask Gemini for a shorter hook — max ~32 characters per sentence)."""
    d = d or ImageDraw.Draw(Image.new("L", (1, 1)))
    f = font("SemiBold", HOOK_FONT)
    if d.textlength(hook, font=f) <= HOOK_MAX_W:
        return [hook]
    if ". " not in hook:
        raise ValueError("hook too long and has no '. ' to split: " + hook)
    a, b = hook.split(". ", 1)
    lines = [a + ".", b]
    for ln in lines:
        if d.textlength(ln, font=f) > HOOK_MAX_W:
            raise ValueError("hook line too long: " + ln)
    return lines


def make_cover(date, part_no, total_parts, part_name, hook, logo_path):
    """date: datetime.date of the NEWS day (New York). Returns RGB 1080×1350."""
    img = cover_background()
    d = ImageDraw.Draw(img)
    paste_logo(img, logo_path)

    # 1) red label box "PART 1/3 · WAR & CONFLICT"   (top y=600, height 52, text SemiBold 26, letter-spacing 4)
    label = f"PART {part_no}/{total_parts} · {part_name.upper()}"
    f = font("SemiBold", 26)
    lw = _spaced_width(d, label, f, 4)
    d.rectangle([M, 600, M + lw + 40, 652], fill=RED)
    _spaced(d, (M + 20, 606), label, f, WHITE, 4)

    # 2) "NOV 15"   Bold 190 at y=668; month white, day number red; black shadow +3,+4
    mon, day = date.strftime("%b").upper(), date.strftime("%d")
    fb = font("Bold", 190)
    d.text((M + 3, 672), mon, font=fb, fill=(0, 0, 0))
    d.text((M, 668), mon, font=fb, fill=WHITE)
    x2 = M + d.textlength(mon + " ", font=fb)
    d.text((x2 + 3, 672), day, font=fb, fill=(0, 0, 0))
    d.text((x2, 668), day, font=fb, fill=RED)

    # 3) "TOP STORIES"   Bold 84 at y=885, white, shadow +2,+3   (never a number, never "TODAY'S")
    fs = font("Bold", 84)
    d.text((M + 2, 888), "TOP STORIES", font=fs, fill=(0, 0, 0))
    d.text((M, 885), "TOP STORIES", font=fs, fill=WHITE)

    # 4) hook   SemiBold 46, white, x=M+30, first line y=1012, line step 56; red bar 8 px wide at x=M from y=1010
    lines = split_hook(hook, d)
    d.rectangle([M, 1010, M + 8, 1010 + 66 + 56 * (len(lines) - 1)], fill=RED)
    hf = font("SemiBold", HOOK_FONT)
    for k, ln in enumerate(lines):
        d.text((M + 30, 1012 + 56 * k), ln, font=hf, fill=WHITE)

    # 5) weekday line "SUNDAY · 2026"   SemiBold 36, SOFT grey, y=1150 (1 hook line) or 1170 (2 lines). No letter-spacing.
    d.text((M, 1150 if len(lines) == 1 else 1170), f"{date.strftime('%A').upper()} · {date.year}",
           font=font("SemiBold", 36), fill=SOFT)

    # 6) footer: red line y=1238..1241 from M to W-M; "VERIFIED WORLD NEWS · EVERY DAY" Medium 24 SOFT at y=1268;
    #    "SWIPE" SemiBold 28 white letter-spacing 3 + red arrow at the right
    ft = POST_H - 112
    d.rectangle([M, ft, W - M, ft + 3], fill=RED)
    d.text((M, ft + 30), "VERIFIED WORLD NEWS · EVERY DAY", font=font("Medium", 24), fill=SOFT)
    sw = font("SemiBold", 28)
    tw = _spaced_width(d, "SWIPE", sw, 3)
    _spaced(d, (W - M - tw - 70, ft + 26), "SWIPE", sw, WHITE, 3)
    ax, ay = W - M - 50, ft + 47
    d.line([(ax, ay), (ax + 46, ay)], fill=RED, width=6)
    d.polygon([(ax + 50, ay), (ax + 32, ay - 14), (ax + 32, ay + 14)], fill=RED)
    return img


def cover_9x16(cover):
    """1080×1920: cover at y=285; top 285 px filled with the cover's own top colour; below it (8,8,8)."""
    fr = Image.new("RGB", (W, VID_H), FILL_BOTTOM_9x16)
    fr.paste(Image.new("RGB", (W, OY), cover.getpixel((540, 2))), (0, 0))
    fr.paste(cover, (0, OY))
    return fr


# ---------------------------------------------------------------- story frames (1080×1920)
def story_canvas(post_no_headline):
    """post_no_headline: the bot's own 1080×1350 render with hide_headline=True.
    Above the post: blurred (radius 34), 45 %-darkened zoom of the PHOTO area (post rows 170–900),
    feathered into the sharp post over 120 px starting 10 px above it. Below the post: the post's
    bottom colour (pixel 540, 1347)."""
    post = post_no_headline.convert("RGB")
    src = post.crop((0, 170, W, 900))
    sc = VID_H / src.height
    big = src.resize((int(W * sc), VID_H), Image.LANCZOS)
    x = (big.width - W) // 2
    bg = big.crop((x, 0, x + W, VID_H)).filter(ImageFilter.GaussianBlur(34))
    bg = Image.blend(bg, Image.new("RGB", (W, VID_H), BLACK), 0.45)

    col = Image.new("L", (1, VID_H), 0)
    for y in range(VID_H):
        if y < OY - 10:
            a = 0
        elif y < OY + 110:
            a = int(255 * ((y - (OY - 10)) / 120) ** 1.2)
        elif y < OY + POST_H:
            a = 255
        else:
            a = 0
        col.putpixel((0, y), a)
    full = Image.new("RGB", (W, VID_H), BLACK)
    full.paste(post, (0, OY))
    bg.paste(full, (0, 0), col.resize((W, VID_H)))

    below = Image.new("L", (1, VID_H), 0)
    for y in range(OY + POST_H, VID_H):
        below.putpixel((0, y), 255)
    bg.paste(Image.new("RGB", (W, VID_H), post.getpixel((540, POST_H - 3))), (0, 0), below.resize((W, VID_H)))
    return bg


def draw_counter(frame, idx, n):
    """Progress line y 0–8 (track black 55 %, fill red up to idx/n) + pill '01 / 13' top-right of the post:
    SemiBold 30 white, black 59 % pill, height 50, radius 25, right edge at W-M, top at OY+70. No border."""
    d = ImageDraw.Draw(frame, "RGBA")
    d.rectangle([0, 0, W, 8], fill=(0, 0, 0, 140))
    d.rectangle([0, 0, int(W * idx / n), 8], fill=RED + (255,))
    f = font("SemiBold", 30)
    txt = f"{idx:02d} / {n:02d}"
    tw = d.textlength(txt, font=f)
    x1 = W - M
    x0 = x1 - tw - 36
    y0 = OY + 70
    d.rounded_rectangle([x0, y0, x1, y0 + 50], radius=25, fill=(0, 0, 0, 150))
    d.text(((x0 + x1) / 2, y0 + 25), txt, font=f, fill=WHITE, anchor="mm")
    return frame


def typing_frame(base, lines, headline_font, size, top_y, line_h, nchars, cursor):
    """Draw the first nchars of the headline. lines/size/top_y/line_h = the bot's OWN headline layout
    (same as render_image) shifted down by OY. Cursor: red block 13 % of size wide, from 18 % to 112 % of size."""
    fr = base.copy()
    d = ImageDraw.Draw(fr)
    left = nchars
    cx = cy = None
    for li, ln in enumerate(lines):
        if left <= 0:
            break
        part = ln[:left]
        left -= len(ln)
        d.text((M, top_y + li * line_h), part, font=headline_font, fill=WHITE)
        cx, cy = M + d.textlength(part, font=headline_font), top_y + li * line_h
    if cursor:
        if cx is None:
            cx, cy = M, top_y
        d.rectangle([cx + 6, cy + int(size * 0.18), cx + 6 + int(size * 0.13), cy + int(size * 1.12)], fill=RED)
    return fr


def typing_frame_count(lines):
    total = sum(len(ln) for ln in lines)
    s = min(TIMING["type_max_s"], max(TIMING["type_min_s"], total * TIMING["type_s_per_char"]))
    return int(s * FPS)


def wipe(frame, k, direction):
    """k = 0..wipe_frames. 'out': red panel comes in from the right; 'in': red panel leaves to the left.
    White edge 12 px wide, 6 px from the red panel edge. Smoothstep easing."""
    n = TIMING["wipe_frames"]
    fr = frame.copy()
    d = ImageDraw.Draw(fr)
    t = k / n
    t = t * t * (3 - 2 * t)
    h = fr.height
    if direction == "out":
        x0 = int(W * (1 - t))
        d.rectangle([x0, 0, W, h], fill=RED)
        if x0 > 0:
            d.rectangle([x0 - 18, 0, x0 - 6, h], fill=WHITE)
    else:
        x1 = int(W * (1 - t))
        d.rectangle([0, 0, x1, h], fill=RED)
        if x1 < W:
            d.rectangle([x1 + 6, 0, x1 + 18, h], fill=WHITE)
    return fr


def end_frame(logo_path):
    """Last frame 1080×1920 on BLACK: logo 660 px wide centred, top y=767; red bar 120×6 centred at y=930;
    'FOLLOW FOR MORE' Bold 58 centred, top y=1000; 'VERIFIED WORLD NEWS · EVERY DAY' Medium 30 SOFT, top y=1085."""
    fr = Image.new("RGB", (W, VID_H), BLACK)
    logo = Image.open(logo_path).convert("RGBA")
    lw = 660
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    fr.paste(logo, ((W - lw) // 2, 767), logo)
    d = ImageDraw.Draw(fr)
    d.rectangle([W // 2 - 60, 930, W // 2 + 60, 936], fill=RED)
    d.text((W // 2, 1000), "FOLLOW FOR MORE", font=font("Bold", 58), fill=WHITE, anchor="ma")
    d.text((W // 2, 1085), "VERIFIED WORLD NEWS · EVERY DAY", font=font("Medium", 30), fill=SOFT, anchor="ma")
    return fr


# ---------------------------------------------------------------- sounds
SR = 44100


def _bandnoise(n, lo, hi, rng):
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    fq = np.fft.rfftfreq(n, 1 / SR)
    X[(fq < lo) | (fq > hi)] = 0
    return np.fft.irfft(X, n)


def build_audio(events, duration_s, path):
    """events: list of (seconds, 'boom' | 'key' | 'whoosh').
    boom = at the cover; key = one per typed non-space character; whoosh = at the start of every swipe-out
    (played 0.12 s early). Writes a 44.1 kHz stereo WAV."""
    rng = np.random.default_rng(7)
    a = np.zeros(int((duration_s + 1) * SR))
    for t, kind in events:
        s0 = int(t * SR)
        if kind == "key":
            n = int(0.035 * SR)
            c = _bandnoise(n, 1800, 6000, rng) * np.exp(-np.linspace(0, 9, n))
            c = c / (np.abs(c).max() + 1e-9) * rng.uniform(0.10, 0.17)
            s0 += int(rng.uniform(0, 0.01) * SR)
        elif kind == "whoosh":
            n = int(0.55 * SR)
            out = np.zeros(n)
            for b in range(0, n, 1024):
                fc = 300 + 2600 * np.sin(np.pi * b / n) ** 2
                seg = _bandnoise(min(1024, n - b), fc * 0.6, fc * 1.6, rng)
                out[b:b + len(seg)] = seg
            c = out * np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5
            c = c / (np.abs(c).max() + 1e-9) * 0.42
            s0 -= int(0.12 * SR)
        else:  # boom
            n = int(1.2 * SR)
            tt = np.linspace(0, 1.2, n)
            c = np.sin(2 * np.pi * (55 * tt + 25 * np.exp(-tt * 6))) * np.exp(-tt * 3.5) * 0.6
            c += _bandnoise(n, 60, 400, rng) * np.exp(-tt * 12) * 0.02
        s0 = max(0, s0)
        a[s0:s0 + len(c)] += c[: len(a) - s0]
    a = a[: int(duration_s * SR)]
    a = np.clip(a / max(1.0, np.abs(a).max() / 0.9), -1, 1)
    st = np.repeat((a * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(st.tobytes())


# ---------------------------------------------------------------- golden images (self-test)
if __name__ == "__main__":
    import datetime
    import sys
    logo, outdir = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 3:
        set_font_dir(sys.argv[3])
    os.makedirs(outdir, exist_ok=True)
    day = datetime.date(2026, 11, 15)
    examples = [
        (1, "WAR & CONFLICT", "Iran targets US base in Bahrain. Houthis advance."),
        (2, "US NEWS", "FAA ground stop. SpaceX catches Starship."),
        (3, "WORLD NEWS", "Czechs protest in Prague. Mexican drug lord dies at 80."),
    ]
    for p, name, hook in examples:
        c = make_cover(day, p, 3, name, hook, logo)
        c.save(f"{outdir}/golden_cover_p{p}_1080x1350.png")
        cover_9x16(c).save(f"{outdir}/golden_cover_p{p}_1080x1920.png")
    end_frame(logo).save(f"{outdir}/golden_end_1080x1920.png")
    print("golden images written to", outdir)
