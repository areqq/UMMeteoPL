//! Raster toolkit mirroring render.py: an RGB canvas with fills, scanline polygons,
//! run-based lines, dotted lines, discs and antialiased bitmap text from glyphs.bin
//! (DejaVu Sans, tools/build_font.py). Pixel results are identical to the Python
//! renderer: the same rounding (Python `round` = ties to even) in the same places.
const std = @import("std");
const tu = @import("timeutil.zig");
const pyround = tu.pyround;
const pyint = tu.pyint;

pub const Rgb = [3]u8;

pub const Glyph = struct {
    left: i32,
    top: i32,
    w: u16,
    h: u16,
    adv: u16,
    bits: []const u8, // w*h alpha bytes
};

pub const Font = struct {
    size: u8,
    ascent: i32,
    descent: i32,
    glyphs: std.AutoHashMapUnmanaged(u32, Glyph),

    pub fn glyph(f: *const Font, cp: u32) Glyph {
        return f.glyphs.get(cp) orelse f.glyphs.get('?') orelse Glyph{ .left = 0, .top = 0, .w = 0, .h = 0, .adv = 0, .bits = &.{} };
    }

    pub fn width(f: *const Font, text: []const u8) i32 {
        var total: i32 = 0;
        var it = std.unicode.Utf8View.initUnchecked(text).iterator();
        while (it.nextCodepoint()) |cp| total += f.glyph(cp).adv;
        return total;
    }
};

pub const Fonts = struct {
    list: []Font,
    raw: []u8, // decompressed glyphs.bin; the glyph bitmaps point into it

    pub fn deinit(fs: *Fonts, gpa: std.mem.Allocator) void {
        for (fs.list) |*f| f.glyphs.deinit(gpa);
        gpa.free(fs.list);
        gpa.free(fs.raw);
    }

    /// Font of the nearest available pixel size (ties: the smaller one), like render.font().
    pub fn font(fs: *const Fonts, size: i64) *const Font {
        var best: *const Font = &fs.list[0];
        for (fs.list) |*f| {
            const d_new = @abs(@as(i64, f.size) - size);
            const d_best = @abs(@as(i64, best.size) - size);
            if (d_new < d_best or (d_new == d_best and f.size < best.size)) best = f;
        }
        return best;
    }
};

/// Parse glyphs.bin (zlib, "UMF1": per font ">BbbH", per glyph ">HbbBBB" + alpha bytes).
pub fn loadFonts(gpa: std.mem.Allocator) !Fonts {
    const blob = @embedFile("glyphs.bin");
    var r = std.Io.Reader.fixed(blob);
    const window = try gpa.alloc(u8, std.compress.flate.max_window_len);
    defer gpa.free(window);
    var d = std.compress.flate.Decompress.init(&r, .zlib, window);
    const raw = try d.reader.allocRemaining(gpa, .limited(8 << 20));
    errdefer gpa.free(raw);
    if (raw.len < 4 or !std.mem.eql(u8, raw[0..4], "UMF1")) return error.UnknownGlyphFormat;
    var fonts: std.ArrayList(Font) = .empty;
    var pos: usize = 4;
    while (pos + 5 <= raw.len) {
        const size = raw[pos];
        const ascent: i8 = @bitCast(raw[pos + 1]);
        const descent: i8 = @bitCast(raw[pos + 2]);
        const count = std.mem.readInt(u16, raw[pos + 3 ..][0..2], .big);
        pos += 5;
        var glyphs: std.AutoHashMapUnmanaged(u32, Glyph) = .empty;
        try glyphs.ensureTotalCapacity(gpa, count);
        var i: usize = 0;
        while (i < count) : (i += 1) {
            if (pos + 7 > raw.len) return error.TruncatedGlyphs;
            const code = std.mem.readInt(u16, raw[pos..][0..2], .big);
            const left: i8 = @bitCast(raw[pos + 2]);
            const top: i8 = @bitCast(raw[pos + 3]);
            const w = raw[pos + 4];
            const h = raw[pos + 5];
            const adv = raw[pos + 6];
            pos += 7;
            const n: usize = @as(usize, w) * h;
            if (pos + n > raw.len) return error.TruncatedGlyphs;
            glyphs.putAssumeCapacity(code, .{ .left = left, .top = top, .w = w, .h = h, .adv = adv, .bits = raw[pos .. pos + n] });
            pos += n;
        }
        try fonts.append(gpa, .{ .size = size, .ascent = ascent, .descent = descent, .glyphs = glyphs });
    }
    return .{ .list = try fonts.toOwnedSlice(gpa), .raw = raw };
}

pub const Align = enum { left, center, right };
pub const VAlign = enum { baseline, top, middle, bottom };
pub const Point = [2]f64;

fn ceilDiv(p: i64, q: i64) i64 {
    return -@divFloor(-p, q);
}

pub const Canvas = struct {
    width: i32,
    height: i32,
    px: []u8, // width*height*3, rows top to bottom

    pub fn init(gpa: std.mem.Allocator, width: i32, height: i32, background: Rgb) !Canvas {
        const n: usize = @as(usize, @intCast(width)) * @as(usize, @intCast(height));
        const px = try gpa.alloc(u8, n * 3);
        var i: usize = 0;
        while (i < px.len) : (i += 3) {
            px[i] = background[0];
            px[i + 1] = background[1];
            px[i + 2] = background[2];
        }
        return .{ .width = width, .height = height, .px = px };
    }

    inline fn row(c: *Canvas, y: i64) []u8 {
        const stride: usize = @as(usize, @intCast(c.width)) * 3;
        const start = @as(usize, @intCast(y)) * stride;
        return c.px[start .. start + stride];
    }

    inline fn setPixel(c: *Canvas, x: i64, y: i64, rgb: Rgb) void {
        const r = c.row(y);
        const i: usize = @intCast(x * 3);
        r[i] = rgb[0];
        r[i + 1] = rgb[1];
        r[i + 2] = rgb[2];
    }

    fn fillRow(c: *Canvas, y: i64, x0: i64, x1: i64, rgb: Rgb) void {
        const r = c.row(y);
        var i: usize = @intCast(x0 * 3);
        const end: usize = @intCast(x1 * 3);
        while (i < end) : (i += 3) {
            r[i] = rgb[0];
            r[i + 1] = rgb[1];
            r[i + 2] = rgb[2];
        }
    }

    /// Rectangle [x0, x1) x [y0, y1), clipped.
    pub fn fill(c: *Canvas, x0_in: i64, y0_in: i64, x1_in: i64, y1_in: i64, rgb: Rgb) void {
        const x0: i64 = @max(@as(i64, 0), @min(x0_in, x1_in));
        const x1: i64 = @min(@as(i64, c.width), @max(x0_in, x1_in));
        const y0: i64 = @max(@as(i64, 0), @min(y0_in, y1_in));
        const y1: i64 = @min(@as(i64, c.height), @max(y0_in, y1_in));
        if (x0 >= x1 or y0 >= y1) return;
        var y = y0;
        while (y < y1) : (y += 1) c.fillRow(y, x0, x1, rgb);
    }

    pub fn hline(c: *Canvas, x0: i64, x1: i64, y: i64, rgb: Rgb, width: i64) void {
        c.fill(x0, y, x1 + 1, y + width, rgb);
    }

    pub fn vline(c: *Canvas, x: i64, y0: i64, y1: i64, rgb: Rgb, width: i64) void {
        c.fill(x, y0, x + width, y1 + 1, rgb);
    }

    /// 1 px high, dashes of `on` px every on+off px from x0 to x1 inclusive.
    pub fn dottedHline(c: *Canvas, x0_in: i64, x1_in: i64, y: i64, rgb: Rgb, on: i64, off: i64) void {
        if (y < 0 or y >= c.height) return;
        const x0: i64 = @max(@as(i64, 0), x0_in);
        const x1: i64 = @min(@as(i64, c.width) - 1, x1_in);
        const period = on + off;
        var j: i64 = 0;
        while (j < on) : (j += 1) {
            var x = x0 + j;
            while (x <= x1) : (x += period) c.setPixel(x, y, rgb);
        }
    }

    /// 1 px wide, dashes of `on` px every on+off px from y0 to y1 inclusive.
    pub fn dottedVline(c: *Canvas, x: i64, y0_in: i64, y1_in: i64, rgb: Rgb, on: i64, off: i64) void {
        if (x < 0 or x >= c.width) return;
        const y0: i64 = @max(@as(i64, 0), y0_in);
        const y1: i64 = @min(@as(i64, c.height) - 1, y1_in);
        var y = y0;
        while (y <= y1) : (y += on + off) {
            var yy = y;
            const stop = @min(y + on, y1 + 1);
            while (yy < stop) : (yy += 1) c.setPixel(x, yy, rgb);
        }
    }

    const Edge = struct { ay: f64, by: f64, ax: f64, slope: f64 };

    /// Filled polygon (scanline, even-odd). A self-intersecting outline (a curve
    /// crossing its base line) fills both lobes, like render.py.
    pub fn polygon(c: *Canvas, points: []const Point, rgb: Rgb) void {
        var edge_buf: [256]Edge = undefined;
        var xs_buf: [256]f64 = undefined;
        var n_edges: usize = 0;
        const n = points.len;
        for (points, 0..) |a, i| {
            const b = points[(i + 1) % n];
            var ax, var ay, var bx, var by = .{ a[0], a[1], b[0], b[1] };
            if (ay != by) {
                if (ay > by) {
                    std.mem.swap(f64, &ax, &bx);
                    std.mem.swap(f64, &ay, &by);
                }
                if (n_edges == edge_buf.len) return; // chart polygons have at most ~130 edges
                edge_buf[n_edges] = .{ .ay = ay, .by = by, .ax = ax, .slope = (bx - ax) / (by - ay) };
                n_edges += 1;
            }
        }
        if (n_edges < 2) return;
        const edges = edge_buf[0..n_edges];
        var min_y = edges[0].ay;
        var max_y = edges[0].by;
        for (edges) |e| {
            min_y = @min(min_y, e.ay);
            max_y = @max(max_y, e.by);
        }
        const y0: i64 = @max(@as(i64, 0), pyint(min_y));
        const y1: i64 = @min(@as(i64, c.height) - 1, pyint(max_y) + 1);
        var y = y0;
        while (y <= y1) : (y += 1) {
            const yc: f64 = @as(f64, @floatFromInt(y)) + 0.5;
            var k: usize = 0;
            for (edges) |e| {
                if (e.ay <= yc and yc < e.by) {
                    xs_buf[k] = e.ax + (yc - e.ay) * e.slope;
                    k += 1;
                }
            }
            const xs = xs_buf[0..k];
            std.mem.sort(f64, xs, {}, std.sort.asc(f64));
            var i: usize = 0;
            while (i + 1 < k) : (i += 2) {
                const xa: i64 = @max(@as(i64, 0), pyround(xs[i]));
                const xb: i64 = @min(@as(i64, c.width), pyround(xs[i + 1]));
                if (xa < xb) c.fillRow(y, xa, xb, rgb);
            }
        }
    }

    /// Fill between the polyline (xs, ys) and the horizontal line base_y.
    pub fn area(c: *Canvas, xs: []const f64, ys: []const f64, base_y: f64, rgb: Rgb) void {
        if (xs.len < 2) return;
        var buf: [128]Point = undefined;
        if (xs.len + 2 > buf.len) return;
        for (xs, ys, 0..) |x, y, i| buf[i] = .{ x, y };
        buf[xs.len] = .{ xs[xs.len - 1], base_y };
        buf[xs.len + 1] = .{ xs[0], base_y };
        c.polygon(buf[0 .. xs.len + 2], rgb);
    }

    /// Fill between two polylines sharing xs.
    pub fn band(c: *Canvas, xs: []const f64, lo: []const f64, hi: []const f64, rgb: Rgb) void {
        if (xs.len < 2) return;
        var buf: [256]Point = undefined;
        if (xs.len * 2 > buf.len) return;
        for (xs, lo, 0..) |x, y, i| buf[i] = .{ x, y };
        for (0..xs.len) |j| {
            const i = xs.len - 1 - j;
            buf[xs.len + j] = .{ xs[i], hi[i] };
        }
        c.polygon(buf[0 .. xs.len * 2], rgb);
    }

    pub fn disc(c: *Canvas, cx_in: f64, cy_in: f64, r: i64, rgb: Rgb, outline: ?Rgb) void {
        const cx = pyround(cx_in);
        const cy = pyround(cy_in);
        if (outline) |o| c.discInt(cx, cy, r + 1, o);
        c.discInt(cx, cy, r, rgb);
    }

    fn discInt(c: *Canvas, cx: i64, cy: i64, r: i64, rgb: Rgb) void {
        const r2: f64 = @as(f64, @floatFromInt(r * r)) + @as(f64, @floatFromInt(r)) * 0.5;
        var dy = -r;
        while (dy <= r) : (dy += 1) {
            const half = pyint(@sqrt(r2 - @as(f64, @floatFromInt(dy * dy))));
            c.fill(cx - half, cy + dy, cx + half + 1, cy + dy + 1, rgb);
        }
    }

    /// Line of `width` px (a width x width square around every pixel of the 1 px
    /// line); dash = (on, off) in pixels along the longer axis.
    pub fn line(c: *Canvas, x0: f64, y0: f64, x1: f64, y1: f64, rgb: Rgb, width: i64, dash: ?[2]i64) void {
        c.solid(pyround(x0), pyround(y0), pyround(x1), pyround(y1), rgb, width, dash);
    }

    /// One rectangle per run: per row when shallow, per column when steep.
    fn solid(c: *Canvas, x0: i64, y0: i64, x1: i64, y1: i64, rgb: Rgb, width: i64, dash: ?[2]i64) void {
        const half = @divFloor(width, 2);
        const adx = @abs(x1 - x0);
        const ady = @abs(y1 - y0);
        const steep = ady > adx;
        const a0: i64, const b0: i64, const a1: i64, const b1: i64, const n: i64, const m: i64 = if (steep)
            .{ y0, x0, y1, x1, @intCast(ady), @intCast(adx) }
        else
            .{ x0, y0, x1, y1, @intCast(adx), @intCast(ady) };
        const sa: i64 = if (a0 <= a1) 1 else -1;
        const sb: i64 = if (b0 <= b1) 1 else -1;
        var k: i64 = 0;
        while (k <= m) : (k += 1) {
            var lo: i64 = 0;
            var hi: i64 = n;
            if (m != 0) {
                lo = @max(@as(i64, 0), ceilDiv((2 * k - 1) * n, 2 * m));
                hi = @min(n, ceilDiv((2 * k + 1) * n, 2 * m) - 1);
            }
            if (lo > hi) continue;
            const cc = b0 + sb * k - half;
            if (dash) |d| {
                const period = d[0] + d[1];
                var s = lo - @mod(lo, period);
                while (s <= hi) : (s += period) {
                    const pa_ = @max(lo, s);
                    const pb_ = @min(hi, s + d[0] - 1);
                    if (pa_ <= pb_) c.run(steep, a0, sa, pa_, pb_, cc, half, width, rgb);
                }
            } else {
                c.run(steep, a0, sa, lo, hi, cc, half, width, rgb);
            }
        }
    }

    fn run(c: *Canvas, steep: bool, a0: i64, sa: i64, lo: i64, hi: i64, cc: i64, half: i64, width: i64, rgb: Rgb) void {
        const pa = a0 + sa * lo;
        const pb = a0 + sa * hi;
        const ra = @min(pa, pb) - half;
        const rb = @max(pa, pb) - half + width;
        if (steep) c.fill(cc, ra, cc + width, rb, rgb) else c.fill(ra, cc, rb, cc + width, rgb);
    }

    pub fn polyline(c: *Canvas, xs: []const f64, ys: []const ?f64, rgb: Rgb, width: i64, dash: ?[2]i64) void {
        var i: usize = 0;
        while (i + 1 < xs.len) : (i += 1) {
            if (ys[i] != null and ys[i + 1] != null)
                c.line(xs[i], ys[i].?, xs[i + 1], ys[i + 1].?, rgb, width, dash);
        }
    }

    pub fn blend(c: *Canvas, x: i64, y: i64, rgb: Rgb, alpha: u8) void {
        if (x < 0 or x >= c.width or y < 0 or y >= c.height) return;
        const r = c.row(y);
        const i: usize = @intCast(x * 3);
        const a: u32 = alpha;
        const inv: u32 = 255 - a;
        r[i] = @intCast((@as(u32, r[i]) * inv + @as(u32, rgb[0]) * a) / 255);
        r[i + 1] = @intCast((@as(u32, r[i + 1]) * inv + @as(u32, rgb[1]) * a) / 255);
        r[i + 2] = @intCast((@as(u32, r[i + 2]) * inv + @as(u32, rgb[2]) * a) / 255);
    }

    /// Draw text with its anchor at (x, y).
    pub fn text(c: *Canvas, x_in: f64, y_in: f64, str: []const u8, fnt: *const Font, rgb: Rgb, al: Align, va: VAlign) void {
        var x = pyround(x_in);
        switch (al) {
            .left => {},
            .center => x -= @divFloor(fnt.width(str), 2),
            .right => x -= fnt.width(str),
        }
        var y = pyround(y_in);
        switch (va) {
            .baseline => {},
            .top => y += fnt.ascent,
            .middle => y += @divFloor(fnt.ascent - fnt.descent, 2),
            .bottom => y -= fnt.descent,
        }
        var it = std.unicode.Utf8View.initUnchecked(str).iterator();
        while (it.nextCodepoint()) |cp| {
            const g = fnt.glyph(cp);
            var gy: usize = 0;
            while (gy < g.h) : (gy += 1) {
                var gx: usize = 0;
                while (gx < g.w) : (gx += 1) {
                    const a = g.bits[gy * g.w + gx];
                    if (a != 0) c.blend(x + g.left + @as(i64, @intCast(gx)), y - g.top + @as(i64, @intCast(gy)), rgb, a);
                }
            }
            x += g.adv;
        }
    }
};

test "fonts load and measure" {
    var fonts = try loadFonts(std.testing.allocator);
    defer fonts.deinit(std.testing.allocator);
    try std.testing.expect(fonts.list.len >= 12);
    const f = fonts.font(11);
    try std.testing.expectEqual(@as(u8, 11), f.size);
    try std.testing.expect(f.width("Temperatura") > f.width("Temp"));
}

test "dotted and dashed lines" {
    const gpa = std.testing.allocator;
    var c = try Canvas.init(gpa, 30, 5, .{ 255, 255, 255 });
    defer gpa.free(c.px);
    c.dottedHline(2, 20, 1, .{ 1, 2, 3 }, 2, 4);
    var got: std.ArrayList(i64) = .empty;
    defer got.deinit(gpa);
    var x: i64 = 0;
    while (x < 30) : (x += 1) {
        const r = c.row(1);
        if (r[@intCast(x * 3)] == 1) try got.append(gpa, x);
    }
    try std.testing.expectEqualSlices(i64, &.{ 2, 3, 8, 9, 14, 15, 20 }, got.items);
    var d = try Canvas.init(gpa, 30, 5, .{ 255, 255, 255 });
    defer gpa.free(d.px);
    d.line(0, 2, 29, 2, .{ 9, 9, 9 }, 1, .{ 3, 2 });
    x = 0;
    while (x < 30) : (x += 1) {
        const lit = d.row(2)[@intCast(x * 3)] == 9;
        try std.testing.expectEqual(@mod(x, 5) < 3, lit);
    }
}
