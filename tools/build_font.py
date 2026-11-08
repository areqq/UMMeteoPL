#!/usr/bin/env python3
"""Rebuild zig/src/glyphs.bin: DejaVu Sans glyph bitmaps for zig/src/render.zig.

Format (zlib-compressed): b"UMF1", then per font: ">BbbH" pixel size, ascent, descent,
glyph count; then per glyph: ">HbbBBB" codepoint, left, top (from the baseline, up),
width, height, advance, followed by width*height 8-bit alpha bytes.

    python3 tools/build_font.py   (from the plugin directory; needs PIL and DejaVu Sans)
"""
import os
import struct
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
# render.zig: base sizes at 720p times the chart scales (1, 1.5, 2, 3)
SIZES = sorted({round(base * scale) for base in (9, 11, 13) for scale in (1, 1.5, 2, 3)})
CHARS = "".join(chr(c) for c in range(32, 127)) + "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ°·×–"


def glyph(font, ch):
    """-> (left, top_from_baseline, width, height, advance, alpha bytes)"""
    ascent, _ = font.getmetrics()
    advance = round(font.getlength(ch))
    x0, y0, x1, y1 = font.getbbox(ch)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return (0, 0, 0, 0, advance, b"")
    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).text((-x0, -y0), ch, font=font, fill=255)
    return (x0, ascent - y0, w, h, advance, img.tobytes())


def main():
    out = [b"UMF1"]
    for size in SIZES:
        font = ImageFont.truetype(FONT, size)
        ascent, descent = font.getmetrics()
        out.append(struct.pack(">BbbH", size, ascent, descent, len(CHARS)))
        for ch in CHARS:
            left, top, w, h, adv, bits = glyph(font, ch)
            out.append(struct.pack(">HbbBBB", ord(ch), left, top, w, h, adv) + bits)
    raw = b"".join(out)
    data = zlib.compress(raw, 9)
    with open(os.path.join(ROOT, "zig", "src", "glyphs.bin"), "wb") as f:
        f.write(data)
    print(f"sizes {SIZES}, {len(CHARS)} glyphs each, {len(raw)} -> {len(data)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
