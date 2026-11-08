# -*- coding: utf-8 -*-
"""Tiny raster toolkit for chart.py: RGB canvas, lines, filled shapes, bitmap text,
PNG output. Pure Python, no PIL (the decoders do not have it); 8-bit antialiased
glyphs come from glyphs.bin (DejaVu Sans, tools/build_font.py). No enigma2 imports.

Written for slow boxes (a 750 MHz MIPS runs Python ~80x slower than a PC), so every
primitive works on whole row slices of the bytearrays, not on single pixels:
areas are scanline polygons, dotted lines are strided slice assignments, glyphs on
a uniform background are cached pre-blended rows."""
import os
import struct
import zlib

GLYPHS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glyphs.bin")

_fonts = None      # {pixel size: Font}
_luts = {}         # (fg, bg) -> [3 bytes for every alpha 0..255]
_discs = {}        # (r, rgb) -> [(dy, half, row bytes)]


def _lut(fg, bg):
    lut = _luts.get((fg, bg))
    if lut is None:
        lut = _luts[(fg, bg)] = [bytes((bg[c] * (255 - a) + fg[c] * a) // 255 for c in range(3))
                                 for a in range(256)]
    return lut


class Font:
    def __init__(self, size, ascent, descent, glyphs):
        self.size = size
        self.ascent = ascent
        self.descent = descent
        self.height = ascent + descent
        self._glyphs = glyphs          # codepoint -> (left, top, w, h, advance, alpha bytes)
        self._pixels = {}              # codepoint -> [(dx, dy, alpha), ...] (dy from the baseline)
        self._rendered = {}            # (codepoint, fg, bg) -> [row bytes] of the glyph box

    def glyph(self, ch):
        return self._glyphs.get(ord(ch)) or self._glyphs.get(ord("?"))

    def width(self, text):
        return sum(self.glyph(ch)[4] for ch in text)

    def pixels(self, ch):
        key = ord(ch)
        if key not in self._pixels:
            left, top, w, h, _adv, bits = self.glyph(ch)
            self._pixels[key] = [(left + i % w, i // w - top, a) for i, a in enumerate(bits) if a]
        return self._pixels[key]

    def rendered(self, ch, fg, bg):
        """Glyph box blended onto a uniform background: one bytes row per glyph row."""
        key = (ord(ch), fg, bg)
        rows = self._rendered.get(key)
        if rows is None:
            _left, _top, w, h, _adv, bits = self.glyph(ch)
            lut = _lut(fg, bg)
            rows = self._rendered[key] = [b"".join(map(lut.__getitem__, bits[r * w:(r + 1) * w]))
                                          for r in range(h)]
        return rows


def _load_fonts():
    """{pixel size: Font}; a Font parses its glyphs on first use (3 of 12 sizes are
    needed for one chart, and the parse is slow on a 750 MHz MIPS)."""
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
        start = pos
        for _ in range(count):
            pos += 7 + raw[pos + 4] * raw[pos + 5]
        fonts[size] = Font(size, ascent, descent, _GlyphTable(raw, start, count))
    _fonts = fonts
    return fonts


class _GlyphTable(dict):
    """codepoint -> (left, top, w, h, advance, alpha bytes), parsed on first access."""

    def __init__(self, raw, pos, count):
        dict.__init__(self)
        self._src = (raw, pos, count)

    def _parse(self):
        if self._src:
            raw, pos, count = self._src
            self._src = None
            for _ in range(count):
                code, left, top, w, h, adv = struct.unpack_from(">HbbBBB", raw, pos)
                pos += 7
                self[code] = (left, top, w, h, adv, raw[pos:pos + w * h])
                pos += w * h

    def get(self, key, default=None):
        self._parse()
        return dict.get(self, key, default)


def font(size):
    """Font of the nearest available pixel size."""
    fonts = _load_fonts()
    return fonts[min(fonts, key=lambda s: (abs(s - size), s))]


def _ceil_div(p, q):
    return -((-p) // q)


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
        """1 px high, dashes of `on` px every on+off px from x0 to x1 inclusive."""
        if not 0 <= y < self.height:
            return
        x0, x1 = max(0, x0), min(self.width - 1, x1)
        row, period, stop = self.rows[y], on + off, (x1 + 1) * 3
        for j in range(on):
            n = len(range(x0 + j, x1 + 1, period))
            if n:
                for c in range(3):
                    row[(x0 + j) * 3 + c:stop:3 * period] = bytes((rgb[c],)) * n

    def dotted_vline(self, x, y0, y1, rgb, on=1, off=2):
        """1 px wide, dashes of `on` px every on+off px from y0 to y1 inclusive."""
        if not 0 <= x < self.width:
            return
        y0, y1 = max(0, y0), min(self.height - 1, y1)
        rows, px, i = self.rows, bytes(rgb), x * 3
        for y in range(y0, y1 + 1, on + off):
            for yy in range(y, min(y + on, y1 + 1)):
                rows[yy][i:i + 3] = px

    def polygon(self, points, rgb):
        """Filled polygon (scanline, even-odd); points [(x, y), ...] as floats or ints.
        Self-intersecting outlines (a curve crossing its base line) fill both lobes."""
        edges = []
        n = len(points)
        for i in range(n):
            (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
            if ay != by:
                if ay > by:
                    ax, ay, bx, by = bx, by, ax, ay
                edges.append((ay, by, ax, (bx - ax) / float(by - ay)))
        if len(edges) < 2:
            return
        y0 = max(0, int(min(e[0] for e in edges)))
        y1 = min(self.height - 1, int(max(e[1] for e in edges)) + 1)
        rows, width, px = self.rows, self.width, bytes(rgb)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = sorted(ax + (yc - ay) * slope for ay, by, ax, slope in edges if ay <= yc < by)
            row = rows[y]
            for i in range(0, len(xs) - 1, 2):
                xa, xb = max(0, int(round(xs[i]))), min(width, int(round(xs[i + 1])))
                if xa < xb:
                    row[xa * 3:xb * 3] = px * (xb - xa)

    def area(self, xs, ys, base_y, rgb):
        """Fill between the polyline (xs, ys) and the horizontal line base_y."""
        if len(xs) > 1:
            self.polygon(list(zip(xs, ys)) + [(xs[-1], base_y), (xs[0], base_y)], rgb)

    def band(self, xs, ys_low, ys_high, rgb):
        """Fill between two polylines sharing xs."""
        if len(xs) > 1:
            self.polygon(list(zip(xs, ys_low)) + list(zip(reversed(xs), reversed(ys_high))), rgb)

    def disc(self, cx, cy, r, rgb, outline=None):
        cx, cy = int(round(cx)), int(round(cy))
        if outline:
            self.disc(cx, cy, r + 1, outline)
        rgb = tuple(rgb)
        spans = _discs.get((r, rgb))
        if spans is None:
            r2, px = r * r + r * 0.5, bytes(rgb)
            spans = _discs[(r, rgb)] = [(dy, half, px * (2 * half + 1))
                                        for dy, half in ((dy, int((r2 - dy * dy) ** 0.5)) for dy in range(-r, r + 1))]
        if r <= cx < self.width - r and r <= cy < self.height - r:
            rows = self.rows
            for dy, half, px in spans:
                rows[cy + dy][(cx - half) * 3:(cx + half + 1) * 3] = px
        else:
            for dy, half, _px in spans:
                self.fill(cx - half, cy + dy, cx + half + 1, cy + dy + 1, rgb)

    # --- lines -----------------------------------------------------------------
    def line(self, x0, y0, x1, y1, rgb, width=1, dash=None):
        """Line of `width` px (a width x width square around every pixel of the
        1 px line); dash=(on, off) in pixels along the longer axis."""
        self._solid(int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)), rgb, width, dash)

    def _solid(self, x0, y0, x1, y1, rgb, width, dash=None):
        """Line as one rectangle per run: per row when shallow, per column when steep.
        The union of the pixel squares along a run is exactly that rectangle."""
        half = width // 2
        adx, ady = abs(x1 - x0), abs(y1 - y0)
        steep = ady > adx
        if steep:
            a0, b0, a1, b1, n, m = y0, x0, y1, x1, ady, adx
        else:
            a0, b0, a1, b1, n, m = x0, y0, x1, y1, adx, ady
        sa, sb = (1 if a0 <= a1 else -1), (1 if b0 <= b1 else -1)
        fill = self.fill
        for k in range(m + 1):
            if m:
                lo = max(0, _ceil_div((2 * k - 1) * n, 2 * m))
                hi = min(n, _ceil_div((2 * k + 1) * n, 2 * m) - 1)
            else:
                lo, hi = 0, n
            if lo > hi:
                continue
            if dash:
                period = dash[0] + dash[1]
                s = lo - lo % period
                pieces = []
                while s <= hi:
                    if max(lo, s) <= min(hi, s + dash[0] - 1):
                        pieces.append((max(lo, s), min(hi, s + dash[0] - 1)))
                    s += period
            else:
                pieces = ((lo, hi),)
            c = b0 + sb * k - half
            for lo, hi in pieces:
                pa, pb = a0 + sa * lo, a0 + sa * hi
                ra, rb = min(pa, pb) - half, max(pa, pb) - half + width
                if steep:
                    fill(c, ra, c + width, rb, rgb)
                else:
                    fill(ra, c, rb, c + width, rgb)

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
        rgb = tuple(rgb)
        rows, width, height, blend = self.rows, self.width, self.height, self.blend
        for ch in text:
            left, top, w, h, adv, _bits = fnt.glyph(ch)
            gx, gy = x + left, y - top
            if w and h and 0 <= gx and gx + w <= width and 0 <= gy and gy + h <= height:
                # glyph box inside the canvas: on a uniform background paste cached rows
                i0, i1 = gx * 3, (gx + w) * 3
                bg = rows[gy][i0:i0 + 3]
                plain = bytes(bg) * w
                if all(rows[gy + r][i0:i1] == plain for r in range(h)):
                    for r, line in enumerate(fnt.rendered(ch, rgb, tuple(bg))):
                        rows[gy + r][i0:i1] = line
                    x += adv
                    continue
            for dx, dy, a in fnt.pixels(ch):
                blend(x + dx, y + dy, rgb, a)
            x += adv

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
