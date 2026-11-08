//! Test root: every module's own tests plus the end-to-end checks against the
//! Python renderer (hashes computed from chart.py on the same fixture).
const std = @import("std");
const tu = @import("timeutil.zig");
const fc = @import("forecast.zig");
const render = @import("render.zig");
const chart = @import("chart.zig");

comptime {
    _ = @import("timeutil.zig");
    _ = @import("render.zig");
    _ = @import("png.zig");
    _ = @import("forecast.zig");
    _ = @import("chart.zig");
    _ = @import("api.zig");
}

const run_fixture: i64 = 1793448000; // 31.10.2026 12 UTC, the Warszawa fixture

test "sun and local time" {
    const sun = tu.sunTimes(52.23, 21.01, @floatFromInt(run_fixture)) orelse return error.TestUnexpectedResult;
    const rise = tu.localF(sun.rise);
    const sset = tu.localF(sun.set);
    // Warszawa, 31.10.2026 (CET): sunrise 06:28, sunset 16:10 (timeanddate.com)
    try std.testing.expectEqual(@as(i64, 6), rise.hour);
    try std.testing.expectEqual(@as(i64, 28), rise.minute);
    try std.testing.expectEqual(@as(i64, 16), sset.hour);
    try std.testing.expectEqual(@as(i64, 10), sset.minute);
    try std.testing.expectEqual(@as(i64, 3600), tu.localOffset(run_fixture));
    const march = tu.timegm(2026, 3, 29, 1, 0, 0); // last Sunday of March 2026
    try std.testing.expectEqual(@as(i64, 3600), tu.localOffset(march - 1));
    try std.testing.expectEqual(@as(i64, 7200), tu.localOffset(march));
    const october = tu.timegm(2026, 10, 25, 1, 0, 0);
    try std.testing.expectEqual(@as(i64, 7200), tu.localOffset(october - 1));
    try std.testing.expectEqual(@as(i64, 3600), tu.localOffset(october));
    var buf: [32]u8 = undefined;
    try std.testing.expectEqualStrings("52°13'47\"N", tu.dms(&buf, 52.2298, "N", "S"));
    try std.testing.expectEqualStrings("21°00'42\"E", tu.dms(&buf, 21.0117, "E", "W"));
}

fn loadFixture(gpa: std.mem.Allocator) !fc.Forecast {
    return fc.parseForecast(gpa, @embedFile("fixtures/um4_60_warszawa_2026-10-31.json"), run_fixture, 52.2298, 21.0117);
}

test "chart pixels equal the python renderer" {
    const gpa = std.testing.allocator;
    var fonts = try render.loadFonts(gpa);
    defer fonts.deinit(gpa);
    var f = try loadFixture(gpa);
    defer fc.freeForecast(gpa, &f);
    // sha256 of b"".join(canvas.rows) from chart.Chart(forecast, scale).draw() in Python
    const expected = [_]struct { scale: f64, w: u32, h: u32, sha: []const u8 }{
        .{ .scale = 1.0, .w = 1060, .h = 660, .sha = "e65594c2b02f4acd1ae9d5f076ff24816fcb9186a5f2fab42cf683ec04a79de3" },
        .{ .scale = 1.5, .w = 1590, .h = 990, .sha = "430fe59e6d5e7736b16f1620462d22e659f7b80e163e22536130935c8b74dd7c" },
    };
    for (expected) |e| {
        const pic = try chart.renderRgb(gpa, &fonts, &f, e.scale);
        defer gpa.free(pic.px);
        try std.testing.expectEqual(e.w, pic.width);
        try std.testing.expectEqual(e.h, pic.height);
        var digest: [32]u8 = undefined;
        std.crypto.hash.sha2.Sha256.hash(pic.px, &digest, .{});
        const hex = std.fmt.bytesToHex(digest, .lower);
        try std.testing.expectEqualStrings(e.sha, &hex);
    }
}

test "missing values do not crash" {
    const gpa = std.testing.allocator;
    var fonts = try render.loadFonts(gpa);
    defer fonts.deinit(gpa);
    var f = try loadFixture(gpa);
    defer fc.freeForecast(gpa, &f);
    for (f.series) |s| @memset(s, null);
    const pic = try chart.renderRgb(gpa, &fonts, &f, 1.0);
    gpa.free(pic.px);
    var g = try loadFixture(gpa);
    defer fc.freeForecast(gpa, &g);
    @memset(g.series[@backingInt(fc.Series.pcpttl_max)], 50.0); // over the scale
    @memset(g.series[@backingInt(fc.Series.storm_max)], 1.0);
    const pic2 = try chart.renderRgb(gpa, &fonts, &g, 2.0);
    gpa.free(pic2.px);
}
