//! The meteogram in the 'retro' layout of old.meteo.pl, a port of chart.py. Design
//! pixels of a 1280x720 skin scaled by `scale`; the arithmetic and rounding follow
//! the Python line by line so both renderers paint the same pixels.
const std = @import("std");
const render = @import("render.zig");
const tu = @import("timeutil.zig");
const fc = @import("forecast.zig");

const Canvas = render.Canvas;
const Rgb = render.Rgb;
const Font = render.Font;
const Point = render.Point;
const pyround = tu.pyround;
const pyint = tu.pyint;

pub const width = 1060;
pub const height = 660;
const plot_x0 = 300; // the time axis
const plot_x1 = 1000;
const legend_x = 8;
const top = 48; // first panel
const gap = 6;
const PanelKey = enum { temp, precip, pressure, wind, winddir, cloudbase, clouds };
const Panel = struct { key: PanelKey, height: i64 };
const panels = [_]Panel{
    .{ .key = .temp, .height = 112 },  .{ .key = .precip, .height = 90 },  .{ .key = .pressure, .height = 68 },
    .{ .key = .wind, .height = 72 },   .{ .key = .winddir, .height = 18 }, .{ .key = .cloudbase, .height = 84 },
    .{ .key = .clouds, .height = 90 },
};

const white: Rgb = .{ 255, 255, 255 };
const black: Rgb = .{ 0, 0, 0 };
const grey_text: Rgb = .{ 80, 80, 80 };
const grid: Rgb = .{ 200, 200, 200 };
const night: Rgb = .{ 228, 228, 228 };
const frame: Rgb = .{ 60, 60, 60 };
const red: Rgb = .{ 220, 30, 30 };
const red_light: Rgb = .{ 250, 190, 190 };
const dark_red: Rgb = .{ 150, 20, 20 };
const blue: Rgb = .{ 40, 90, 230 };
const blue_light: Rgb = .{ 190, 210, 250 };
const blue_dot: Rgb = .{ 60, 60, 200 };
const green: Rgb = .{ 30, 150, 40 };
const green_light: Rgb = .{ 150, 220, 150 };
const snow_c: Rgb = .{ 50, 100, 240 };
const snow_light: Rgb = .{ 170, 190, 250 };
const sleet_c: Rgb = .{ 70, 160, 190 };
const sleet_light: Rgb = .{ 170, 215, 230 };
const yellow: Rgb = .{ 255, 220, 60 };
const wind_c: Rgb = .{ 40, 100, 200 };
const gust_c: Rgb = .{ 220, 40, 40 };
const prob_c: Rgb = .{ 120, 120, 120 };
const hum_c: Rgb = .{ 220, 40, 40 };
const cloud_shades = [_]Rgb{ .{ 216, 216, 216 }, .{ 168, 168, 168 }, .{ 112, 112, 112 }, .{ 56, 56, 56 } }; // high .. very low
const base_shades = [_]Rgb{ .{ 255, 255, 255 }, .{ 200, 200, 200 }, .{ 144, 144, 144 }, .{ 80, 80, 80 }, .{ 0, 0, 0 } };
const fog_c: Rgb = .{ 240, 150, 30 };
const vis_c: Rgb = .{ 240, 130, 20 };
const top_c: Rgb = .{ 220, 40, 40 };

const days = [_][]const u8{ "pon", "wt", "śr", "czw", "pt", "sob", "nie" };

pub const max_steps = 256;

// --- axis helpers -----------------------------------------------------------------

/// Value -> pixel y. `linear` is chart.py's `linear()` (with `div` for the
/// `lambda v: y_of(v / 8.0)` of the cloud panel), `piecewise` its `Piecewise`.
const YOf = struct {
    kind: enum { linear, piecewise },
    lo: f64 = 0,
    span: f64 = 1,
    div: f64 = 1,
    points: []const f64 = &.{},
    y0: f64,
    y1: f64,

    fn linear(lo: f64, hi: f64, y0: i64, y1: i64) YOf {
        var span = hi - lo;
        if (span == 0) span = 1.0;
        return .{ .kind = .linear, .lo = lo, .span = span, .y0 = @floatFromInt(y0), .y1 = @floatFromInt(y1) };
    }

    fn piecewise(points: []const f64, y0: i64, y1: i64) YOf {
        return .{ .kind = .piecewise, .points = points, .y0 = @floatFromInt(y0), .y1 = @floatFromInt(y1) };
    }

    fn at(a: YOf, v_in: f64) f64 {
        switch (a.kind) {
            .linear => {
                const v = v_in / a.div;
                return a.y1 - (v - a.lo) / a.span * (a.y1 - a.y0);
            },
            .piecewise => {
                const p = a.points;
                const v = @min(@max(v_in, p[0]), p[p.len - 1]);
                var i: usize = 0;
                while (i + 1 < p.len) : (i += 1) {
                    if (v <= p[i + 1]) {
                        const frac = (@as(f64, @floatFromInt(i)) + (v - p[i]) / (p[i + 1] - p[i])) / @as(f64, @floatFromInt(p.len - 1));
                        return a.y1 - frac * (a.y1 - a.y0);
                    }
                }
                return a.y0;
            },
        }
    }
};

const Range = struct { lo: f64, hi: f64 };

fn niceRange(vals: []const f64, step: f64, pad: f64, minimum_span: ?f64) Range {
    if (vals.len == 0) return .{ .lo = 0.0, .hi = step * 2 };
    var mn = vals[0];
    var mx = vals[0];
    for (vals) |v| {
        mn = @min(mn, v);
        mx = @max(mx, v);
    }
    var lo = @floor((mn - pad) / step) * step;
    var hi = @ceil((mx + pad) / step) * step;
    if (minimum_span) |ms| {
        if (hi - lo < ms) {
            const extra = ms - (hi - lo);
            lo -= @floor(extra / 2 / step) * step;
            hi = lo + @ceil(ms / step) * step;
        }
    }
    return .{ .lo = lo, .hi = hi };
}

fn frange(buf: []f64, lo: f64, hi: f64, step: f64) []f64 {
    const n = pyround((hi - lo) / step);
    var i: i64 = 0;
    while (i <= n and i < buf.len) : (i += 1) buf[@intCast(i)] = lo + @as(f64, @floatFromInt(i)) * step;
    return buf[0..@intCast(@min(n + 1, @as(i64, @intCast(buf.len))))];
}

/// chart.fmt(): `{v:g}` for fractions, the integer otherwise.
fn fmtNum(buf: []u8, v: f64) []const u8 {
    const r = pyround(v);
    if (@abs(v - @as(f64, @floatFromInt(r))) > 1e-9) return std.fmt.bufPrint(buf, "{d}", .{v}) catch unreachable;
    return std.fmt.bufPrint(buf, "{d}", .{r}) catch unreachable;
}

const Marker = enum { line, thin, dash, dots, bar, dot, tri, whisker, none };
const LegendItem = struct { marker: Marker, colour: Rgb, text: []const u8 };

pub const Chart = struct {
    gpa: std.mem.Allocator,
    f: *const fc.Forecast,
    scale: f64,
    canvas: Canvas,
    small: *const Font,
    normal: *const Font,
    big: *const Font,
    thin: i64,
    thick: i64,
    t0: i64, // the run hour: left edge
    t1: i64,
    xs: []f64,
    hour_w: f64,
    bottom: i64 = 0,

    pub fn init(gpa: std.mem.Allocator, fonts: *const render.Fonts, f: *const fc.Forecast, scale: f64) !Chart {
        if (f.steps < 2 or f.steps > max_steps) return error.EmptyForecast;
        var c: Chart = .{
            .gpa = gpa,
            .f = f,
            .scale = scale,
            .canvas = undefined,
            .small = fonts.font(pyround(9 * scale)),
            .normal = fonts.font(pyround(11 * scale)),
            .big = fonts.font(pyround(13 * scale)),
            .thin = @max(1, pyround(scale)),
            .thick = @max(2, pyround(2 * scale)),
            .t0 = f.timeAt(0) - f.interval,
            .t1 = f.timeAt(f.steps - 1),
            .xs = undefined,
            .hour_w = 0,
        };
        c.canvas = try Canvas.init(gpa, @intCast(c.p(width)), @intCast(c.p(height)), white);
        errdefer gpa.free(c.canvas.px);
        c.xs = try gpa.alloc(f64, f.steps);
        for (c.xs, 0..) |*x, i| x.* = c.xpos(@floatFromInt(f.timeAt(i)));
        c.hour_w = c.xs[1] - c.xs[0];
        return c;
    }

    pub fn deinit(c: *Chart) void {
        c.gpa.free(c.xs);
        c.gpa.free(c.canvas.px);
    }

    // --- geometry -----------------------------------------------------------------
    fn p(c: *const Chart, v: f64) i64 {
        return pyround(v * c.scale);
    }

    fn pf(c: *const Chart, v: f64) f64 {
        return @floatFromInt(c.p(v));
    }

    fn xpos(c: *const Chart, t: f64) f64 {
        const x0 = c.pf(plot_x0);
        const x1 = c.pf(plot_x1);
        const t0: f64 = @floatFromInt(c.t0);
        const t1: f64 = @floatFromInt(c.t1);
        return x0 + (t - t0) / (t1 - t0) * (x1 - x0);
    }

    // --- the whole picture --------------------------------------------------------
    pub fn draw(c: *Chart) !void {
        var y = c.p(top);
        var rects: [panels.len][2]i64 = undefined;
        for (panels, 0..) |pan, i| {
            rects[i] = .{ y, y + c.p(@floatFromInt(pan.height)) };
            y += c.p(@floatFromInt(pan.height + gap));
        }
        c.bottom = rects[panels.len - 1][1];
        c.header();
        for (panels, 0..) |pan, i| c.background(rects[i][0], rects[i][1], pan.key != .winddir);
        c.timeAxes();
        try c.temperature(rects[0][0], rects[0][1]);
        try c.precipitation(rects[1][0], rects[1][1]);
        try c.pressure(rects[2][0], rects[2][1]);
        try c.wind(rects[3][0], rects[3][1]);
        c.windDirection(rects[4][0], rects[4][1]);
        try c.cloudBase(rects[5][0], rects[5][1]);
        try c.clouds(rects[6][0], rects[6][1]);
        c.footer();
    }

    // --- common parts -------------------------------------------------------------
    fn background(c: *Chart, y0: i64, y1: i64, with_nights: bool) void {
        const cv = &c.canvas;
        const x0 = c.p(plot_x0);
        const x1 = c.p(plot_x1);
        if (with_nights) {
            var buf: [8][2]f64 = undefined;
            const t0: f64 = @floatFromInt(c.t0);
            const t1: f64 = @floatFromInt(c.t1);
            for (c.nights(&buf)) |n| {
                cv.fill(pyint(c.xpos(@max(n[0], t0))), y0, pyround(c.xpos(@min(n[1], t1))), y1, night);
            }
        }
        var mbuf: [16]Mark = undefined;
        for (c.marks(&mbuf)) |m| {
            const x = pyround(c.xpos(@floatFromInt(m.t)));
            if (m.midnight) cv.vline(x, y0, y1, frame, c.thin) else cv.dottedVline(x, y0, y1, grid, c.thin, 2 * c.thin);
        }
        cv.vline(x0, y0, y1, frame, c.thin);
        cv.vline(x1 - c.thin, y0, y1, frame, c.thin);
        cv.hline(x0, x1, y0, frame, c.thin);
        cv.hline(x0, x1, y1 - c.thin, frame, c.thin);
    }

    /// (sunset, next sunrise) pairs overlapping the chart.
    fn nights(c: *const Chart, buf: *[8][2]f64) [][2]f64 {
        var n: usize = 0;
        var day = @divFloor(c.t0, 86400) * 86400 - 86400;
        const t0: f64 = @floatFromInt(c.t0);
        const t1: f64 = @floatFromInt(c.t1);
        while (day < c.t1 + 86400) : (day += 86400) {
            const sun = tu.sunTimes(c.f.lat, c.f.lon, @floatFromInt(day + 43200));
            const nxt = tu.sunTimes(c.f.lat, c.f.lon, @floatFromInt(day + 86400 + 43200));
            if (sun != null and nxt != null) {
                const a = sun.?.set;
                const b = nxt.?.rise;
                if (b > t0 and a < t1 and n < buf.len) {
                    buf[n] = .{ a, b };
                    n += 1;
                }
            }
        }
        return buf[0..n];
    }

    const Mark = struct { t: i64, loc: tu.Civil, midnight: bool };

    /// Every 6 hours of local time.
    fn marks(c: *const Chart, buf: *[16]Mark) []Mark {
        var n: usize = 0;
        var t = c.t0 - @mod(c.t0, 3600);
        while (t <= c.t1) : (t += 3600) {
            const loc = tu.local(t);
            if (@mod(loc.hour, 6) == 0 and t >= c.t0 and n < buf.len) {
                buf[n] = .{ .t = t, .loc = loc, .midnight = loc.hour == 0 };
                n += 1;
            }
        }
        return buf[0..n];
    }

    fn zone(c: *const Chart) []const u8 {
        return if (tu.localOffset(c.f.start) == 7200) "CEST" else "CET";
    }

    fn header(c: *Chart) void {
        const cv = &c.canvas;
        const f = c.f;
        const y_info = c.pf(13);
        var buf: [128]u8 = undefined;
        if (tu.sunTimes(f.lat, f.lon, @floatFromInt(f.start))) |sun| {
            const rise = tu.localF(sun.rise);
            const sset = tu.localF(sun.set);
            const s = std.fmt.bufPrint(&buf, "wschód słońca {d:0>2}:{d:0>2}   zachód {d:0>2}:{d:0>2} {s}", .{ u(rise.hour), u(rise.minute), u(sset.hour), u(sset.minute), c.zone() }) catch unreachable;
            cv.text(c.pf(plot_x0), y_info, s, c.normal, blue, .left, .baseline);
        }
        var b1: [32]u8 = undefined;
        var b2: [32]u8 = undefined;
        const coords = std.fmt.bufPrint(&buf, "{s}  {s}", .{ tu.dms(&b1, f.lat, "N", "S"), tu.dms(&b2, f.lon, "E", "W") }) catch unreachable;
        cv.text(@floatFromInt(@divFloor(c.p(plot_x0) + c.p(plot_x1), 2)), y_info, coords, c.normal, blue, .center, .baseline);
        if (f.row != null and f.col != null) {
            const s = std.fmt.bufPrint(&buf, "siatka UM: wiersz {d}, kolumna {d}", .{ f.row.?, f.col.? }) catch unreachable;
            cv.text(c.pf(plot_x1), y_info, s, c.normal, grey_text, .right, .baseline);
        }
        cv.text(c.pf(legend_x), y_info, "UM 4 km, 60 h", c.big, black, .left, .baseline);
        var rb: [32]u8 = undefined;
        const start = std.fmt.bufPrint(&buf, "start {s}", .{f.run(&rb)}) catch unreachable;
        cv.text(c.pf(legend_x), c.pf(28), start, c.normal, grey_text, .left, .baseline);
        cv.text(c.pf(legend_x), c.pf(41), "szare pasma: noc", c.small, grey_text, .left, .baseline);
    }

    fn timeAxes(c: *Chart) void {
        const cv = &c.canvas;
        const y_days = c.pf(28);
        const y_local = c.pf(40);
        const y_utc: f64 = @floatFromInt(c.bottom + c.p(12));
        const y_days2: f64 = @floatFromInt(c.bottom + c.p(24));
        const z = c.zone();
        cv.text(c.pf(plot_x0) - c.pf(4), y_local, z, c.small, black, .right, .baseline);
        cv.text(c.pf(plot_x1) + c.pf(4), y_local, z, c.small, black, .left, .baseline);
        cv.text(c.pf(plot_x0) - c.pf(4), y_utc, "UTC", c.small, black, .right, .baseline);
        cv.text(c.pf(plot_x1) + c.pf(4), y_utc, "UTC", c.small, black, .left, .baseline);
        var buf: [32]u8 = undefined;
        var mbuf: [16]Mark = undefined;
        for (c.marks(&mbuf)) |m| {
            const x = c.xpos(@floatFromInt(m.t));
            cv.text(x, y_local, std.fmt.bufPrint(&buf, "{d:0>2}", .{u(m.loc.hour)}) catch unreachable, c.small, black, .center, .baseline);
            cv.text(x, y_utc, std.fmt.bufPrint(&buf, "{d:0>2}", .{u(tu.gmtime(m.t).hour)}) catch unreachable, c.small, black, .center, .baseline);
        }
        // day names centred on each local day inside the range
        var day_start = c.t0 - @mod(c.t0 + tu.localOffset(c.t0), 86400);
        while (day_start < c.t1) {
            const day_end = day_start + 86400;
            const a = @max(day_start, c.t0);
            const b = @min(day_end, c.t1);
            if (b - a >= 4 * 3600) {
                const loc = tu.local(day_start + 43200);
                const label = std.fmt.bufPrint(&buf, "{s}, {d:0>2}.{d:0>2}", .{ days[@intCast(loc.wday)], u(loc.day), u(loc.month) }) catch unreachable;
                const xm = (c.xpos(@floatFromInt(a)) + c.xpos(@floatFromInt(b))) / 2;
                cv.text(xm, y_days, label, c.normal, black, .center, .baseline);
                cv.text(xm, y_days2, label, c.normal, black, .center, .baseline);
            }
            day_start = day_end;
        }
    }

    fn footer(c: *Chart) void {
        const y: f64 = @floatFromInt(c.p(height) - c.p(5));
        c.canvas.text(c.pf(plot_x0), y, "dane: meteo.pl (ICM, Uniwersytet Warszawski), model UM", c.small, grey_text, .left, .baseline);
        c.canvas.text(c.pf(plot_x1), y, "wykres: UM Meteo.pl dla enigmy2", c.small, grey_text, .right, .baseline);
    }

    fn axisLeft(c: *Chart, y_of: YOf, ticks: []const f64, show_grid: bool, colour: Rgb) void {
        const cv = &c.canvas;
        const x0 = c.p(plot_x0);
        const x1 = c.p(plot_x1);
        var buf: [32]u8 = undefined;
        for (ticks) |v| {
            const y = pyround(y_of.at(v));
            cv.hline(x0 - c.p(3), x0, y, frame, c.thin);
            cv.text(@floatFromInt(x0 - c.p(6)), @floatFromInt(y), fmtNum(&buf, v), c.small, colour, .right, .middle);
            if (show_grid and v != ticks[0]) cv.dottedHline(x0, x1, y, grid, c.thin, 2 * c.thin);
        }
    }

    fn axisRight(c: *Chart, y_of: YOf, ticks: []const f64, labels: ?[]const []const u8, colour: Rgb, unit: ?[]const u8, y0: i64) void {
        const cv = &c.canvas;
        const x1 = c.p(plot_x1);
        var buf: [32]u8 = undefined;
        for (ticks, 0..) |v, i| {
            const y = pyround(y_of.at(v));
            cv.hline(x1, x1 + c.p(3), y, frame, c.thin);
            const label = if (labels) |l| l[i] else fmtNum(&buf, v);
            cv.text(@floatFromInt(x1 + c.p(6)), @floatFromInt(y), label, c.small, colour, .left, .middle);
        }
        if (unit) |un| cv.text(@floatFromInt(x1 - c.p(5)), @floatFromInt(y0 + c.p(9)), un, c.small, colour, .right, .middle);
    }

    fn legend(c: *Chart, y_in: i64, items: []const LegendItem, title: ?[]const u8) i64 {
        const cv = &c.canvas;
        const x = c.p(legend_x);
        const line_h = c.p(12);
        var y = y_in;
        if (title) |t| {
            cv.text(@floatFromInt(x), @floatFromInt(y + c.p(11)), t, c.big, black, .left, .baseline);
            y += c.p(15);
        }
        for (items) |it| {
            const ym = y + c.p(6);
            const mx0 = x;
            const mx1 = x + c.p(22);
            switch (it.marker) {
                .line => cv.hline(mx0, mx1, ym, it.colour, c.thick),
                .thin => cv.hline(mx0, mx1, ym, it.colour, c.thin),
                .dash => cv.line(@floatFromInt(mx0), @floatFromInt(ym), @floatFromInt(mx1), @floatFromInt(ym), it.colour, c.thin, .{ 3 * c.thin, 2 * c.thin }),
                .dots => {
                    var dx: i64 = 0;
                    while (dx < mx1 - mx0 + 1) : (dx += c.p(6)) cv.disc(@floatFromInt(mx0 + dx), @floatFromInt(ym), c.thin, it.colour, null);
                },
                .bar => cv.fill(mx0, ym - c.p(5), mx1, ym + c.p(5), it.colour),
                .dot => cv.disc(@floatFromInt(@divFloor(mx0 + mx1, 2)), @floatFromInt(ym), @max(2, c.p(2.5)), it.colour, if (std.mem.eql(u8, &it.colour, &white)) grey_text else null),
                .tri => {
                    const m = @divFloor(mx0 + mx1, 2);
                    cv.polygon(&.{ pt(m - c.p(5), ym + c.p(4)), pt(m + c.p(5), ym + c.p(4)), pt(m, ym - c.p(4)) }, it.colour);
                },
                .whisker => {
                    const m = @divFloor(mx0 + mx1, 2);
                    cv.vline(m, ym - c.p(5), ym + c.p(5), it.colour, c.thin);
                    cv.hline(m - c.p(2), m + c.p(2), ym - c.p(5), it.colour, c.thin);
                    cv.hline(m - c.p(2), m + c.p(2), ym + c.p(5), it.colour, c.thin);
                },
                .none => {},
            }
            cv.text(@floatFromInt(x + c.p(28)), @floatFromInt(ym), it.text, c.normal, black, .left, .middle);
            y += line_h;
        }
        return y;
    }

    /// One bar per hour, from y_base up to the value; cap -> overflow marker.
    fn bars(c: *Chart, values: []const ?f64, y_of: YOf, y_base: i64, colour: Rgb, cap: ?f64, columns: ?[]const bool) void {
        const cv = &c.canvas;
        const w = @max(1, pyint(c.hour_w) - c.thin);
        for (values, 0..) |v_opt, i| {
            const v = v_opt orelse continue;
            if (v <= 0) continue;
            if (columns) |cols| if (!cols[i]) continue;
            const x1 = pyround(c.xs[i]);
            const x0 = x1 - w;
            const top_y = pyround(y_of.at(if (cap) |cp| @min(v, cp) else v));
            cv.fill(x0, top_y, x1, y_base, colour);
            if (cap) |cp| {
                if (v > cp) {
                    const m = @divFloor(x0 + x1, 2);
                    cv.polygon(&.{ pt(x0, top_y + c.p(5)), pt(x1, top_y + c.p(5)), pt(m, top_y - c.p(1)) }, red);
                }
            }
        }
    }

    fn ys(c: *const Chart, buf: []?f64, s: fc.Series, y_of: YOf) []?f64 {
        const src = c.f.get(s);
        for (src, 0..) |v, i| buf[i] = if (v) |x| y_of.at(x) else null;
        return buf[0..src.len];
    }

    /// chart.Chart.band(): the band is split where a value is missing.
    fn bandSeries(c: *Chart, ys_low: []const ?f64, ys_high: []const ?f64, colour: Rgb) void {
        var xs: [max_steps]f64 = undefined;
        var lo: [max_steps]f64 = undefined;
        var hi: [max_steps]f64 = undefined;
        var n: usize = 0;
        for (c.xs, ys_low, ys_high) |x, a, b| {
            if (a != null and b != null) {
                xs[n] = x;
                lo[n] = a.?;
                hi[n] = b.?;
                n += 1;
            } else if (n > 1) {
                c.canvas.band(xs[0..n], lo[0..n], hi[0..n], colour);
                n = 0;
            }
        }
        if (n > 1) c.canvas.band(xs[0..n], lo[0..n], hi[0..n], colour);
    }

    /// Area under a series skipping missing values (the xs/seg lists of chart.py).
    fn areaSeries(c: *Chart, values: []const ?f64, y_of: YOf, base_y: i64, colour: Rgb, clamp01: bool) void {
        var xs: [max_steps]f64 = undefined;
        var seg: [max_steps]f64 = undefined;
        var n: usize = 0;
        for (c.xs, values) |x, v_opt| {
            if (v_opt) |v| {
                xs[n] = x;
                seg[n] = y_of.at(if (clamp01) @min(@max(v, 0.0), 1.0) else v);
                n += 1;
            }
        }
        if (n > 1) c.canvas.area(xs[0..n], seg[0..n], @floatFromInt(base_y), colour);
    }

    // --- panels -------------------------------------------------------------------
    fn temperature(c: *Chart, y0: i64, y1: i64) !void {
        const cv = &c.canvas;
        const f = c.f;
        const names = [_]fc.Series{ .airtmp_point, .airtmp_min, .airtmp_max, .grdtmp_min, .grdtmp_max, .dwptmp_point, .wchill_point, .wchill_min, .wchill_max };
        const allv = try c.gpa.alloc(f64, names.len * f.steps);
        defer c.gpa.free(allv);
        var n: usize = 0;
        for (names) |name| for (f.get(name)) |v| {
            if (v) |x| {
                allv[n] = x;
                n += 1;
            }
        };
        const r = niceRange(allv[0..n], 5, 1.0, 15);
        const step: f64 = if (r.hi - r.lo <= 35) 5 else 10;
        const y_of = YOf.linear(r.lo, r.hi, y0 + c.p(4), y1 - c.p(4));
        var tbuf: [64]f64 = undefined;
        const ticks = frange(&tbuf, r.lo, r.hi, step);
        c.axisLeft(y_of, ticks, true, black);
        c.axisRight(y_of, ticks, null, black, null, 0);
        if (r.lo < 0 and 0 < r.hi) cv.hline(c.p(plot_x0), c.p(plot_x1), pyround(y_of.at(0)), frame, c.thin);
        // ground temperature min..max whiskers
        for (f.get(.grdtmp_min), f.get(.grdtmp_max), 0..) |a, b, i| {
            if (a != null and b != null) {
                const x = pyround(c.xs[i]);
                cv.vline(x, pyround(y_of.at(b.?)), pyround(y_of.at(a.?)), dark_red, c.thin);
            }
        }
        var b1: [max_steps]?f64 = undefined;
        var b2: [max_steps]?f64 = undefined;
        c.bandSeries(c.ys(&b1, .wchill_min, y_of), c.ys(&b2, .wchill_max, y_of), blue_light);
        c.bandSeries(c.ys(&b1, .airtmp_min, y_of), c.ys(&b2, .airtmp_max, y_of), red_light);
        cv.polyline(c.xs, c.ys(&b1, .wchill_point, y_of), blue, c.thick, null);
        cv.polyline(c.xs, c.ys(&b1, .airtmp_point, y_of), red, c.thick, null);
        for (c.xs, c.ys(&b1, .dwptmp_point, y_of)) |x, y| {
            if (y) |yy| cv.disc(x, yy, c.thin, blue_dot, null);
        }
        _ = c.legend(y0, &.{
            .{ .marker = .line, .colour = red, .text = "temperatura (pasmo: min–max)" },
            .{ .marker = .line, .colour = blue, .text = "odczuwalna (min–max)" },
            .{ .marker = .dots, .colour = blue_dot, .text = "punkt rosy" },
            .{ .marker = .whisker, .colour = dark_red, .text = "temp. gruntu min–max" },
        }, "Temperatura [°C]");
    }

    fn precipitation(c: *Chart, y0: i64, y1: i64) !void {
        const cv = &c.canvas;
        const f = c.f;
        const strip = c.p(10); // storm markers at the top
        const top_y = y0 + strip;
        const bottom = y1 - c.thin;
        var peak: f64 = 0;
        for (f.get(.pcpttl_max)) |v| if (v) |x| {
            peak = @max(peak, x);
        };
        for (f.get(.pcpttl_aver)) |v| if (v) |x| {
            peak = @max(peak, x);
        };
        var cap: f64 = 20;
        var tick_step: f64 = 5;
        for ([_][2]f64{ .{ 1, 0.25 }, .{ 2, 0.5 }, .{ 5, 1 }, .{ 10, 2 }, .{ 20, 5 } }) |cs| {
            if (cs[0] >= peak) {
                cap = cs[0];
                tick_step = cs[1];
                break;
            }
        }
        const y_of = YOf.linear(0, cap, top_y, bottom);
        var tbuf: [64]f64 = undefined;
        c.axisLeft(y_of, frange(&tbuf, 0, cap, tick_step), true, black);
        const y_pct = YOf.linear(0, 100, top_y, bottom);
        c.axisRight(y_pct, &.{ 0, 25, 50, 75, 100 }, null, hum_c, "%", y0 + strip);
        var kinds: [max_steps]i64 = undefined;
        for (f.get(.pcpttl_type_max), 0..) |t, i| kinds[i] = if (t) |x| pyround(x) else 0;
        var cols: [max_steps]bool = undefined;
        const kind_colours = [_]struct { kind: i64, light: Rgb, dark: Rgb }{
            .{ .kind = fc.rain, .light = green_light, .dark = green },
            .{ .kind = fc.snow, .light = snow_light, .dark = snow_c },
            .{ .kind = fc.sleet, .light = sleet_light, .dark = sleet_c },
        };
        for (kind_colours) |kc| {
            for (kinds[0..f.steps], 0..) |k, i| cols[i] = k == kc.kind;
            c.bars(f.get(.pcpttl_max), y_of, bottom, kc.light, cap, cols[0..f.steps]);
            c.bars(f.get(.pcpttl_aver), y_of, bottom, kc.dark, cap, cols[0..f.steps]);
        }
        // whatever has an amount but no type: treat as rain
        for (kinds[0..f.steps], f.get(.pcpttl_aver), 0..) |k, a, i| cols[i] = k == 0 and a != null and a.? > 0;
        c.bars(f.get(.pcpttl_max), y_of, bottom, green_light, cap, cols[0..f.steps]);
        c.bars(f.get(.pcpttl_aver), y_of, bottom, green, cap, cols[0..f.steps]);
        for (f.get(.storm_max), f.get(.flash_max), 0..) |storm, flash, i| {
            const x = pyround(c.xs[i] - c.hour_w / 2);
            if (storm != null and storm.? > 0)
                cv.polygon(&.{ pt(x - c.p(4), y0 + strip - c.p(2)), pt(x + c.p(4), y0 + strip - c.p(2)), pt(x, y0 + c.p(2)) }, yellow);
            if (flash != null and flash.? > 0)
                cv.polygon(&.{ pt(x - c.p(2), y0 + strip - c.p(3)), pt(x + c.p(2), y0 + strip - c.p(3)), pt(x, y0 + c.p(4)) }, red);
        }
        var b1: [max_steps]?f64 = undefined;
        cv.polyline(c.xs, c.ys(&b1, .pcpttlprob_point, y_pct), prob_c, c.thin, .{ 3 * c.thin, 3 * c.thin });
        cv.polyline(c.xs, c.ys(&b1, .realhum_aver, y_pct), hum_c, c.thick, null);
        _ = c.legend(y0, &.{
            .{ .marker = .bar, .colour = green, .text = "deszcz (ciemniej: średni, jaśniej: max)" },
            .{ .marker = .bar, .colour = snow_c, .text = "śnieg" },
            .{ .marker = .bar, .colour = sleet_c, .text = "deszcz ze śniegiem" },
            .{ .marker = .tri, .colour = yellow, .text = "burza   (czerwony: wyładowania)" },
            .{ .marker = .line, .colour = hum_c, .text = "wilgotność względna [%]" },
            .{ .marker = .dash, .colour = prob_c, .text = "prawdopodobieństwo opadu [%]" },
        }, "Opad [mm/h]");
    }

    fn pressure(c: *Chart, y0: i64, y1: i64) !void {
        const cv = &c.canvas;
        const f = c.f;
        var hpa: [max_steps]?f64 = undefined;
        var vals: [max_steps]f64 = undefined;
        var n: usize = 0;
        for (f.get(.slpres_point), 0..) |v, i| {
            hpa[i] = if (v) |x| x / 100.0 else null;
            if (v) |x| {
                vals[n] = x / 100.0;
                n += 1;
            }
        }
        const r = niceRange(vals[0..n], 5, 1.0, 10);
        const step: f64 = if (r.hi - r.lo <= 30) 5 else 10;
        const y_of = YOf.linear(r.lo, r.hi, y0 + c.p(4), y1 - c.thin);
        var tbuf: [64]f64 = undefined;
        const ticks = frange(&tbuf, r.lo, r.hi, step);
        c.axisLeft(y_of, ticks, true, black);
        var lbuf: [64][16]u8 = undefined;
        var labels: [64][]const u8 = undefined;
        for (ticks, 0..) |v, i| labels[i] = std.fmt.bufPrint(&lbuf[i], "{d:.0}", .{v * 0.750062}) catch unreachable;
        c.axisRight(y_of, ticks, labels[0..ticks.len], black, "mmHg", y0);
        var yb: [max_steps]?f64 = undefined;
        for (hpa[0..f.steps], 0..) |v, i| yb[i] = if (v) |x| y_of.at(x) else null;
        c.areaSeries(hpa[0..f.steps], y_of, y1 - c.thin, yellow, false);
        cv.polyline(c.xs, yb[0..f.steps], black, c.thick, null);
        _ = c.legend(y0, &.{
            .{ .marker = .line, .colour = black, .text = "zredukowane do poziomu morza" },
            .{ .marker = .none, .colour = black, .text = "prawa oś: mmHg" },
        }, "Ciśnienie [hPa]");
    }

    fn wind(c: *Chart, y0: i64, y1: i64) !void {
        const cv = &c.canvas;
        const f = c.f;
        var mx: f64 = 0;
        var any = false;
        for (f.get(.wind10_sd_true_prev_point)) |v| if (v) |x| {
            mx = if (any) @max(mx, x) else x;
            any = true;
        };
        for (f.get(.wind_gust_max)) |v| if (v) |x| {
            mx = if (any) @max(mx, x) else x;
            any = true;
        };
        const hi: f64 = @max(10, @as(f64, @floatFromInt(pyint(@ceil(mx / 5.0)) * 5)));
        const step: f64 = if (hi <= 25) 5 else 10;
        const y_of = YOf.linear(0, hi, y0 + c.p(4), y1 - c.thin);
        var tbuf: [64]f64 = undefined;
        const ticks = frange(&tbuf, 0, hi, step);
        c.axisLeft(y_of, ticks, true, black);
        var lbuf: [64][16]u8 = undefined;
        var labels: [64][]const u8 = undefined;
        for (ticks, 0..) |v, i| labels[i] = std.fmt.bufPrint(&lbuf[i], "{d:.0}", .{v * 3.6}) catch unreachable;
        c.axisRight(y_of, ticks, labels[0..ticks.len], black, "km/h", y0);
        c.areaSeries(f.get(.wind10_sd_true_prev_point), y_of, y1 - c.thin, wind_c, false);
        var b1: [max_steps]?f64 = undefined;
        cv.polyline(c.xs, c.ys(&b1, .wind_gust_max, y_of), gust_c, c.thin, .{ 4 * c.thin, 3 * c.thin });
        _ = c.legend(y0, &.{
            .{ .marker = .bar, .colour = wind_c, .text = "prędkość średnia" },
            .{ .marker = .dash, .colour = gust_c, .text = "maksymalne porywy" },
            .{ .marker = .none, .colour = black, .text = "prawa oś: km/h" },
        }, "Wiatr na 10 m [m/s]");
    }

    fn windDirection(c: *Chart, y0: i64, y1: i64) void {
        const cv = &c.canvas;
        const ym = @divFloor(y0 + y1, 2);
        const ymf: f64 = @floatFromInt(ym);
        const length = @as(f64, @floatFromInt(y1 - y0)) * 0.42;
        for (c.f.get(.wind10_dr_deg_true_prev_point), 0..) |d_opt, i| {
            const d = d_opt orelse continue;
            if (i % 2 != 0) continue;
            const a = (d + 180) * (std.math.pi / 180.0); // the arrow points where the wind blows to
            const dx = @sin(a) * length;
            const dy = -@cos(a) * length;
            const x = c.xs[i] - c.hour_w / 2;
            const x0 = x - dx;
            const y0a = ymf - dy;
            const x1 = x + dx;
            const y1a = ymf + dy;
            cv.line(x0, y0a, x1, y1a, wind_c, c.thin, null);
            for ([_]f64{ 2.6, -2.6 }) |side| {
                const hx = x1 - @sin(a + side) * length * 0.6;
                const hy = y1a + @cos(a + side) * length * 0.6;
                cv.line(x1, y1a, hx, hy, wind_c, c.thin, null);
            }
        }
        cv.text(c.pf(plot_x1) + c.pf(6), ymf, "N u góry", c.small, black, .left, .middle);
        cv.text(c.pf(legend_x), ymf, "Kierunek wiatru (strzałka: dokąd wieje, N u góry)", c.normal, black, .left, .middle);
    }

    fn cloudBase(c: *Chart, y0: i64, y1: i64) !void {
        const cv = &c.canvas;
        const f = c.f;
        const top_y = y0 + c.p(4);
        const bottom = y1 - c.thin;
        const km_points = [_]f64{ 0, 0.5, 1, 2, 5, 7, 15 };
        const y_km = YOf.piecewise(&km_points, top_y, bottom);
        c.axisLeft(y_km, &km_points, true, black);
        const vis_points = [_]f64{ 0, 1, 5, 10, 20, 50 };
        const y_vis = YOf.piecewise(&vis_points, top_y, bottom);
        c.axisRight(y_vis, &.{ 0.2, 1, 5, 10, 20, 50 }, &.{ "0.2", "1", "5", "10", "20", "50" }, vis_c, "widzialność km", y0);
        var b1: [max_steps]?f64 = undefined;
        for (f.get(.visibl_min), 0..) |v, i| b1[i] = if (v) |x| y_vis.at(x / 1000.0) else null;
        cv.polyline(c.xs, b1[0..f.steps], vis_c, c.thick, null);
        const r = @max(2, c.p(2.5));
        const base_series = [_]fc.Series{ .cldbse01, .cldbse25, .cldbse45, .cldbse65, .cldbse79 };
        for (base_series, base_shades) |name, shade| {
            for (c.xs, f.get(name)) |x, v| {
                if (v != null and v.? >= 0) cv.disc(x, y_km.at(v.?), r, shade, if (std.mem.eql(u8, &shade, &white)) grey_text else null);
            }
        }
        for (c.xs, f.get(.cldtop)) |x, v| {
            if (v != null and v.? > 0) cv.disc(x, y_km.at(v.?), r, top_c, null);
        }
        _ = c.legend(y0, &.{
            .{ .marker = .dot, .colour = top_c, .text = "wierzchołek chmur" },
            .{ .marker = .dot, .colour = base_shades[4], .text = "podstawa chmur, pokrycie > 7.9 okt." },
            .{ .marker = .dot, .colour = base_shades[2], .text = "> 4.5 okt.   (biały: > 0.1, jasny: > 2.5)" },
            .{ .marker = .dot, .colour = base_shades[3], .text = "> 6.5 okt." },
            .{ .marker = .line, .colour = vis_c, .text = "widzialność [km], prawa oś" },
        }, "Podstawa chmur [km]");
    }

    fn clouds(c: *Chart, y0: i64, y1: i64) !void {
        const cv = &c.canvas;
        const f = c.f;
        const top_y = y0 + c.p(4);
        const bottom = y1 - c.thin;
        const y_of = YOf.linear(0, 1, top_y, bottom);
        var y_okt = y_of;
        y_okt.div = 8.0;
        c.axisLeft(y_okt, &.{ 0, 2, 4, 6, 8 }, true, black);
        c.axisRight(y_of, &.{ 0, 0.25, 0.5, 0.75, 1.0 }, null, black, "frakcja", y0);
        const layers = [_]fc.Series{ .cldhigh_aver, .cldmed_aver, .cldlow_aver, .cldvlow_aver };
        for (layers, cloud_shades) |name, shade| c.areaSeries(f.get(name), y_of, bottom, shade, true);
        c.bars(f.get(.fog_max), y_of, bottom, fog_c, 1.0, null);
        var b1: [max_steps]?f64 = undefined;
        for (f.get(.cldtot_aver), 0..) |v, i| b1[i] = if (v) |x| y_of.at(@min(@max(x, 0.0), 1.0)) else null;
        cv.polyline(c.xs, b1[0..f.steps], black, c.thin, .{ 2 * c.thin, 2 * c.thin });
        _ = c.legend(y0, &.{
            .{ .marker = .bar, .colour = cloud_shades[0], .text = "wysokie" },
            .{ .marker = .bar, .colour = cloud_shades[1], .text = "średnie" },
            .{ .marker = .bar, .colour = cloud_shades[2], .text = "niskie" },
            .{ .marker = .bar, .colour = cloud_shades[3], .text = "bardzo niskie" },
            .{ .marker = .bar, .colour = fog_c, .text = "mgła (frakcja)" },
            .{ .marker = .dash, .colour = black, .text = "zachmurzenie całkowite" },
        }, "Zachmurzenie [okt.]");
    }
};

fn pt(x: i64, y: i64) Point {
    return .{ @floatFromInt(x), @floatFromInt(y) };
}

fn u(v: i64) u64 {
    return @intCast(v);
}

/// Forecast -> RGB pixels (width*height*3) of the chart at `scale`. Caller frees.
pub fn renderRgb(gpa: std.mem.Allocator, fonts: *const render.Fonts, f: *const fc.Forecast, scale: f64) !struct { px: []u8, width: u32, height: u32 } {
    var c = try Chart.init(gpa, fonts, f, scale);
    defer gpa.free(c.xs);
    errdefer gpa.free(c.canvas.px);
    try c.draw();
    return .{ .px = c.canvas.px, .width = @intCast(c.canvas.width), .height = @intCast(c.canvas.height) };
}

test "axis helpers" {
    const r = niceRange(&.{ 3.0, 9.6 }, 5, 1.0, 15);
    try std.testing.expectEqual(@as(f64, 0), r.lo);
    try std.testing.expectEqual(@as(f64, 15), r.hi);
    const r2 = niceRange(&.{ 1012.3, 1013.1 }, 5, 1.0, 10);
    try std.testing.expectEqual(@as(f64, 10), r2.hi - r2.lo);
    var buf: [16]f64 = undefined;
    const t = frange(&buf, 0, 1, 0.25);
    try std.testing.expectEqual(@as(usize, 5), t.len);
    var s: [16]u8 = undefined;
    try std.testing.expectEqualStrings("0.25", fmtNum(&s, 0.25));
    try std.testing.expectEqualStrings("5", fmtNum(&s, 5.0));
    const a = YOf.linear(0, 10, 100, 200);
    try std.testing.expectEqual(@as(f64, 150), a.at(5));
    const pw = YOf.piecewise(&.{ 0, 1, 5 }, 0, 100);
    try std.testing.expectEqual(@as(f64, 50), pw.at(1));
}
