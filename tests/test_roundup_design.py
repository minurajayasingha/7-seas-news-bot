"""Golden test for the roundup design (bot/roundup_design.py). Must pass before pushing.

    python tests/test_roundup_design.py        (or: python -m pytest tests/)

Renders the 3 golden covers (Nov 15 2026, parts/hooks as in roundup_design.__main__) and the end frame with
assets/logo-extracted-for-tests.png and compares them PIXEL BY PIXEL with tests/golden/*.png
(max difference 2 allowed for tiny font-file differences). On a mismatch a diff image is saved next to this file
(tests/diff_<name>.png) and the test stops.
Needs Pillow WITH raqm (kerning; normal on Linux / GitHub Actions; on a Mac: brew install fribidi).
"""
import datetime
import os
import sys

from PIL import Image, ImageChops, ImageDraw, features

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bot"))
import roundup_design as RD  # noqa: E402

GOLDEN = os.path.join(HERE, "golden")
LOGO = os.path.join(ROOT, "assets", "logo-extracted-for-tests.png")
FONTS = os.path.join(ROOT, "fonts")
DAY = datetime.date(2026, 11, 15)
EXAMPLES = [
    (1, "WAR & CONFLICT", "Iran targets US base in Bahrain. Houthis advance."),
    (2, "US NEWS", "FAA ground stop. SpaceX catches Starship."),
    (3, "WORLD NEWS", "Czechs protest in Prague. Mexican drug lord dies at 80."),
]
TOLERANCE = 2


def ensure_fonts():
    """The bot's own Poppins files (fonts/, downloaded by main.font() if missing)."""
    if not all(os.path.exists(os.path.join(FONTS, f"Poppins-{w}.ttf")) for w in ("Bold", "SemiBold", "Medium")):
        import main  # noqa: F401  (main.font downloads them)
        for w in ("Bold", "SemiBold", "Medium"):
            main.font(f"Poppins-{w}.ttf", 10)
    RD.set_font_dir(FONTS)


def same(img, name):
    gold = Image.open(os.path.join(GOLDEN, name)).convert("RGB")
    img = img.convert("RGB")
    assert img.size == gold.size, f"{name}: size {img.size} != golden {gold.size}"
    diff = ImageChops.difference(img, gold)
    worst = max(hi for _, hi in diff.getextrema())
    if worst > TOLERANCE:
        out = os.path.join(HERE, "diff_" + name)
        diff.point(lambda v: 255 if v > TOLERANCE else 0).save(out)
        raise AssertionError(f"{name}: differs from golden by up to {worst} (area {diff.getbbox()}); diff saved: {out}")


def test_raqm():
    assert features.check("raqm"), "Pillow has no raqm (kerning) — golden images need it (Mac: brew install fribidi)"


def test_covers_and_end_frame():
    ensure_fonts()
    for p, name, hook in EXAMPLES:
        c = RD.make_cover(DAY, p, 3, name, hook, LOGO)
        assert c.size == (1080, 1350)
        same(c, f"golden_cover_p{p}_1080x1350.png")
        t = RD.cover_9x16(c)
        assert t.size == (1080, 1920)
        same(t, f"golden_cover_p{p}_1080x1920.png")
    e = RD.end_frame(LOGO)
    assert e.size == (1080, 1920)
    same(e, "golden_end_1080x1920.png")


def test_story_frame_size():
    ensure_fonts()
    post = Image.new("RGB", (1080, 1350), (40, 60, 80))
    fr = RD.draw_counter(RD.story_canvas(post), 1, 13)
    assert fr.size == (1080, 1920)
    f = RD.font("Bold", 60)
    fr = RD.typing_frame(fr, ["Test headline"], f, 60, 900 + RD.OY, 70, 5, True)
    assert fr.size == (1080, 1920)
    assert RD.wipe(fr, 4, "out").size == (1080, 1920)


def test_split_hook():
    ensure_fonts()
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    for _, _, hook in EXAMPLES:
        assert RD.split_hook(hook, d)
    long = "A" + "b" * 48 + "."                  # 50 characters, one sentence
    assert len(long) == 50
    try:
        RD.split_hook(long, d)
    except ValueError:
        pass
    else:
        raise AssertionError("a 50-character single sentence must raise ValueError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("ALL ROUNDUP DESIGN TESTS PASSED")
