# -*- coding: utf-8 -*-
"""Tiny raster toolkit for chart.py: RGB canvas, lines, filled shapes, bitmap text,
PNG output. Pure Python, no PIL (the decoders do not have it); 8-bit antialiased
glyphs come from glyphs.bin (DejaVu Sans, tools/build_font.py). No enigma2 imports."""
import os
import struct
import zlib

GLYPHS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glyphs.bin")

_fonts = None      # {pixel size: Font}


class Font:
    def __init__(self, size, ascent, descent, glyphs):
        self.size = size
        self.ascent = ascent
        self.descent = descent
        self.height = ascent + descent
        self._glyphs = glyphs          # codepoint -> (left, top, w, h, advance, alpha bytes)
        self._pixels = {}              # codepoint -> [(dx, dy, alpha), ...] (dy from the baseline)

    def glyph(self, ch):
        return self._glyphs.get(ord(ch)) or self._glyphs.get(ord("?"))

    def width(self, text):
        return sum(self.glyph(ch)[4] for ch in text)

    def pixels(self, ch):
        g = self.glyph(ch)
        key = ord(ch)
        if key not in self._pixels:
            left, top, w, h, _adv, bits = g
            self._pixels[key] = [(left + i % w, i // w - top, a) for i, a in enumerate(bits) if a]
        return self._pixels[key]


def _load_fonts():
    global _fonts
    if _fonts is not None:
        return _fonts
    with open(GLYPHS_FILE, "rb") as f:
        raw = zlib.decompress(f.read())
    if raw[:4] != b"UMF1":
        raise ValueError("glyphs.bin: unknown format")
    pos, fonts = 4, {}
    while pos < len(raw):
        size, ascent, descent, count = struct.unpack_from(">BbbH", raw, pos)
        pos += 5
        glyphs = {}
        for _ in range(count):
            code, left, top, w, h, adv = struct.unpack_from(">HbbBBB", raw, pos)
            pos += 7
            glyphs[code] = (left, top, w, h, adv, raw[pos:pos + w * h])
            pos += w * h
        fonts[size] = Font(size, ascent, descent, glyphs)
    _fonts = fonts
    return fonts


def font(size):
    """Font of the nearest available pixel size."""
    fonts = _load_fonts()
    return fonts[min(fonts, key=lambda s: (abs(s - size), s))]


class Canvas:
    """RGB raster; coordinates are pixels, x to the right, y down."""

    def __init__(self, width, height, background=(255, 255, 255)):
        self.width, self.height = width, height
        row = bytes(background) * width
        self.rows = [bytearray(row) for _ in range(height)]

    # --- filled areas --------------------------------------------------------
    def fill(self, x0, y0, x1, y1, rgb):
        """Rectangle [x0, x1) x [y0, y1), clipped."""
        x0, x1 = max(0, min(x0, x1)), min(self.width, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(self.height, max(y0, y1))
        if x0 >= x1 or y0 >= y1:
            return
        px = bytes(rgb) * (x1 - x0)
        for y in range(y0, y1):
            self.rows[y][x0 * 3:x1 * 3] = px

    def hline(self, x0, x1, y, rgb, width=1):
        self.fill(x0, y, x1 + 1, y + width, rgb)

    def vline(self, x, y0, y1, rgb, width=1):
        self.fill(x, y0, x + width, y1 + 1, rgb)

    def dotted_hline(self, x0, x1, y, rgb, on=1, off=2):
        for x in range(x0, x1 + 1, on + off):
            self.fill(x, y, min(x + on, x1 + 1), y + 1, rgb)

    def dotted_vline(self, x, y0, y1, rgb, on=1, off=2):
        for y in range(y0, y1 + 1, on + off):
            self.fill(x, y, x + 1, min(y + on, y1 + 1), rgb)

    def polygon(self, points, rgb):
        """Filled polygon (scanline, even-odd); points [(x, y), ...] as floats or ints."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        y0, y1 = max(0, int(min(ys))), min(self.height - 1, int(max(ys)) + 1)
        n = len(points)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                self.fill(int(round(xs[i])), y, int(round(xs[i + 1])), y + 1, rgb)

    def area(self, xs, ys, base_y, rgb):
        """Fill between the polyline (xs, ys) and the horizontal line base_y, column by column."""
        for i in range(len(xs) - 1):
            xa, xb = int(round(xs[i])), int(round(xs[i + 1]))
            if xb <= xa:
                continue
            for x in range(xa, xb):
                y = ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])
                self.fill(x, int(round(min(y, base_y))), x + 1, int(round(max(y, base_y))), rgb)

    def band(self, xs, ys_low, ys_high, rgb):
        """Fill between two polylines sharing xs."""
        for i in range(len(xs) - 1):
            xa, xb = int(round(xs[i])), int(round(xs[i + 1]))
            if xb <= xa:
                continue
            for x in range(xa, xb):
                t = (x - xs[i]) / (xs[i + 1] - xs[i])
                lo = ys_low[i] + (ys_low[i + 1] - ys_low[i]) * t
                hi = ys_high[i] + (ys_high[i + 1] - ys_high[i]) * t
                self.fill(x, int(round(min(lo, hi))), x + 1, int(round(max(lo, hi))) + 1, rgb)

    def disc(self, cx, cy, r, rgb, outline=None):
        cx, cy = int(round(cx)), int(round(cy))
        if outline:
            self.disc(cx, cy, r + 1, outline)
        r2 = r * r + r * 0.5
        for dy in range(-r, r + 1):
            half = int((r2 - dy * dy) ** 0.5)
            self.fill(cx - half, cy + dy, cx + half + 1, cy + dy + 1, rgb)

    # --- lines -----------------------------------------------------------------
    def line(self, x0, y0, x1, y1, rgb, width=1, dash=None):
        """Bresenham line; width in pixels; dash=(on, off) in steps."""
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        half = width // 2
        step = 0
        px = bytes(rgb) * width
        rows, w, h = self.rows, self.width, self.height
        while True:
            if dash is None or step % (dash[0] + dash[1]) < dash[0]:
                if width == 1:
                    if 0 <= x0 < w and 0 <= y0 < h:
                        rows[y0][x0 * 3:x0 * 3 + 3] = px
                else:
                    xa, xb = max(0, x0 - half), min(w, x0 - half + width)
                    if xa < xb:
                        seg = px[:(xb - xa) * 3]
                        for y in range(max(0, y0 - half), min(h, y0 - half + width)):
                            rows[y][xa * 3:xb * 3] = seg
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
            step += 1

    def polyline(self, xs, ys, rgb, width=1, dash=None):
        for i in range(len(xs) - 1):
            if ys[i] is not None and ys[i + 1] is not None:
                self.line(xs[i], ys[i], xs[i + 1], ys[i + 1], rgb, width, dash)

    # --- text ------------------------------------------------------------------
    def blend(self, x, y, rgb, alpha):
        if 0 <= x < self.width and 0 <= y < self.height:
            row, i = self.rows[y], x * 3
            inv = 255 - alpha
            row[i] = (row[i] * inv + rgb[0] * alpha) // 255
            row[i + 1] = (row[i + 1] * inv + rgb[1] * alpha) // 255
            row[i + 2] = (row[i + 2] * inv + rgb[2] * alpha) // 255

    def text(self, x, y, text, fnt, rgb, align="left", valign="baseline"):
        """Draw text with its anchor at (x, y). align: left/center/right;
        valign: baseline/top/middle/bottom."""
        x = int(round(x))
        if align == "center":
            x -= fnt.width(text) // 2
        elif align == "right":
            x -= fnt.width(text)
        y = int(round(y))
        if valign == "top":
            y += fnt.ascent
        elif valign == "middle":
            y += (fnt.ascent - fnt.descent) // 2
        elif valign == "bottom":
            y -= fnt.descent
        blend = self.blend
        for ch in text:
            for dx, dy, a in fnt.pixels(ch):
                blend(x + dx, y + dy, rgb, a)
            x += fnt.glyph(ch)[4]

    def vtext(self, x, y, text, fnt, rgb, align="center"):
        """Text rotated 90 degrees counter-clockwise (reads bottom to top); (x, y) is the
        baseline x and the anchor along the text (align: top/center/bottom of the run)."""
        x, y = int(round(x)), int(round(y))
        length = fnt.width(text)
        if align == "center":
            y += length // 2
        elif align == "top":
            y += length
        blend = self.blend
        for ch in text:
            for dx, dy, a in fnt.pixels(ch):
                blend(x + dy, y - dx, rgb, a)
            y -= fnt.glyph(ch)[4]

    # --- output ------------------------------------------------------------------
    def png(self, level=3):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        ihdr = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        raw = b"".join(b"\x00" + bytes(r) for r in self.rows)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, level))
                + chunk(b"IEND", b""))
