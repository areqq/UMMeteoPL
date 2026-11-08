//! Test root: every module's own tests plus the end-to-end checks of the whole chart
//! (pixel hashes of the fixture, a regression guard).
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

test "chart pixels match the reference" {
    // Regression guard: the full-screen layout rendered on the Warszawa fixture with the
    // title "Warszawa 1/5". The hashes come from this very renderer after a visual check
    // (2026-11-08); an intentional layout change updates them.
    const gpa = std.testing.allocator;
    var fonts = try render.loadFonts(gpa);
    defer fonts.deinit(gpa);
    var f = try loadFixture(gpa);
    defer fc.freeForecast(gpa, &f);
    const expected = [_]struct { scale: f64, w: u32, h: u32, sha: []const u8 }{
        .{ .scale = 1.0, .w = 1280, .h = 720, .sha = "6225b42f7cc62a562b22f00b6117a5f9f753c13fec8fe1e5ad3e0227334b88e0" },
        .{ .scale = 1.5, .w = 1920, .h = 1080, .sha = "a43bb555f439582559e6d2b7b7907bb9688ae1ada9d5de23597fc008bfc13976" },
    };
    for (expected) |e| {
        const pic = try chart.renderRgb(gpa, &fonts, &f, e.scale, "Warszawa", "1/5");
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
    const pic = try chart.renderRgb(gpa, &fonts, &f, 1.0, "", "");
    gpa.free(pic.px);
    var g = try loadFixture(gpa);
    defer fc.freeForecast(gpa, &g);
    @memset(g.series[@backingInt(fc.Series.pcpttl_max)], 50.0); // over the scale
    @memset(g.series[@backingInt(fc.Series.storm_max)], 1.0);
    const pic2 = try chart.renderRgb(gpa, &fonts, &g, 2.0, "Zakopane, pow.tatrzański", "4/5");
    gpa.free(pic2.px);
    const ph = try chart.placeholder(gpa, &fonts, 1.5, "Pobieram prognozę...", "meteo.pl, model UM", chart.placeholder_blue);
    gpa.free(ph.px);
}
