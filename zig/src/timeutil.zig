//! Calendar and sun helpers mirroring chart.py: UTC civil time, Polish local time
//! (EU DST rule, CET/CEST), sunrise/sunset (sunrise equation), D°M'S" formatting.
//! Every integer division follows Python's floor semantics so the results match
//! the plugin bit for bit.
const std = @import("std");

/// Like Python's `round()`: nearest integer, ties to even.
pub fn pyround(x: f64) i64 {
    const fl = @floor(x);
    const diff = x - fl;
    var r = fl;
    if (diff > 0.5) {
        r += 1;
    } else if (diff == 0.5) {
        if (@mod(fl, 2.0) != 0) r += 1;
    }
    return @intFromFloat(r);
}

/// Python `int()` of a float: truncation toward zero.
pub fn pyint(x: f64) i64 {
    return @intFromFloat(@trunc(x));
}

pub const Civil = struct {
    year: i64,
    month: i64, // 1..12
    day: i64, // 1..31
    hour: i64,
    minute: i64,
    second: i64,
    wday: i64, // Monday = 0, like Python's tm_wday
};

/// Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant's algorithm).
pub fn daysFromCivil(y_in: i64, m: i64, d: i64) i64 {
    const y = if (m <= 2) y_in - 1 else y_in;
    const era = @divFloor(y, 400);
    const yoe = y - era * 400;
    const mp = @mod(m + 9, 12);
    const doy = @divFloor(153 * mp + 2, 5) + d - 1;
    const doe = yoe * 365 + @divFloor(yoe, 4) - @divFloor(yoe, 100) + doy;
    return era * 146097 + doe - 719468;
}

const Ymd = struct { y: i64, m: i64, d: i64 };

pub fn civilFromDays(z_in: i64) Ymd {
    const z = z_in + 719468;
    const era = @divFloor(z, 146097);
    const doe = z - era * 146097;
    const yoe = @divFloor(doe - @divFloor(doe, 1460) + @divFloor(doe, 36524) - @divFloor(doe, 146096), 365);
    const y = yoe + era * 400;
    const doy = doe - (365 * yoe + @divFloor(yoe, 4) - @divFloor(yoe, 100));
    const mp = @divFloor(5 * doy + 2, 153);
    const d = doy - @divFloor(153 * mp + 2, 5) + 1;
    const m = if (mp < 10) mp + 3 else mp - 9;
    return .{ .y = if (m <= 2) y + 1 else y, .m = m, .d = d };
}

pub fn gmtime(t: i64) Civil {
    const days = @divFloor(t, 86400);
    const secs = @mod(t, 86400);
    const c = civilFromDays(days);
    return .{
        .year = c.y,
        .month = c.m,
        .day = c.d,
        .hour = @divFloor(secs, 3600),
        .minute = @divFloor(@mod(secs, 3600), 60),
        .second = @mod(secs, 60),
        .wday = @mod(days + 3, 7), // 1970-01-01 was a Thursday
    };
}

pub fn timegm(y: i64, m: i64, d: i64, hh: i64, mm: i64, ss: i64) i64 {
    return daysFromCivil(y, m, d) * 86400 + hh * 3600 + mm * 60 + ss;
}

fn isLeap(y: i64) bool {
    return @mod(y, 4) == 0 and (@mod(y, 100) != 0 or @mod(y, 400) == 0);
}

fn daysInMonth(y: i64, m: i64) i64 {
    return switch (m) {
        1, 3, 5, 7, 8, 10, 12 => 31,
        4, 6, 9, 11 => 30,
        else => if (isLeap(y)) @as(i64, 29) else 28,
    };
}

fn lastSunday(year: i64, month: i64) i64 {
    const last = daysInMonth(year, month);
    const wd = @mod(daysFromCivil(year, month, last) + 3, 7);
    return last - @mod(wd + 1, 7);
}

/// Seconds to add to UTC for Polish time (CET/CEST, EU rule) at unix time t.
pub fn localOffset(t: i64) i64 {
    const year = gmtime(t).year;
    const start = timegm(year, 3, lastSunday(year, 3), 1, 0, 0);
    const end = timegm(year, 10, lastSunday(year, 10), 1, 0, 0);
    return if (start <= t and t < end) 7200 else 3600;
}

pub fn local(t: i64) Civil {
    return gmtime(t + localOffset(t));
}

/// Python's time.gmtime() of a float floors it first.
pub fn localF(t: f64) Civil {
    return local(@intFromFloat(@floor(t)));
}

pub const Sun = struct { rise: f64, set: f64 };

fn radians(deg: f64) f64 {
    return deg * (std.math.pi / 180.0);
}

fn degrees(rad: f64) f64 {
    return rad * (180.0 / std.math.pi);
}

/// (sunrise, sunset) unix times for the UTC day containing `day`, null when the
/// sun does not rise or set (polar).
pub fn sunTimes(lat: f64, lon: f64, day: f64) ?Sun {
    const jd = day / 86400.0 + 2440587.5;
    const n: f64 = @floatFromInt(pyround(jd - 2451545.0 + 0.0008));
    const j_star = n - lon / 360.0;
    const m = radians(@mod(357.5291 + 0.98560028 * j_star, 360.0));
    const c = 1.9148 * @sin(m) + 0.02 * @sin(2 * m) + 0.0003 * @sin(3 * m);
    const lam = radians(@mod(degrees(m) + c + 180 + 102.9372, 360.0));
    const transit = 2451545.0 + j_star + 0.0053 * @sin(m) - 0.0069 * @sin(2 * lam);
    const decl = std.math.asin(@sin(lam) * @sin(radians(23.44)));
    const phi = radians(lat);
    const cos_w = (@sin(radians(-0.83)) - @sin(phi) * @sin(decl)) / (@cos(phi) * @cos(decl));
    if (!(cos_w >= -1 and cos_w <= 1)) return null;
    const w = degrees(std.math.acos(cos_w)) / 360.0;
    return .{ .rise = toUnix(transit - w), .set = toUnix(transit + w) };
}

fn toUnix(j: f64) f64 {
    return (j - 2440587.5) * 86400.0;
}

/// 52.2298 -> 52°13'47"N
pub fn dms(buf: []u8, value_in: f64, pos: []const u8, neg: []const u8) []const u8 {
    const hemi = if (value_in >= 0) pos else neg;
    const value = @abs(value_in);
    const d = pyint(value);
    const df: f64 = @floatFromInt(d);
    const m = pyint((value - df) * 60);
    const mf: f64 = @floatFromInt(m);
    const s = pyround(((value - df) * 60 - mf) * 60);
    return std.fmt.bufPrint(buf, "{d}°{d:0>2}'{d:0>2}\"{s}", .{ @as(u64, @intCast(d)), @as(u64, @intCast(m)), @as(u64, @intCast(s)), hemi }) catch unreachable;
}

test "gmtime and timegm" {
    const c = gmtime(1793448000); // 31.10.2026 12:00 UTC, Saturday
    try std.testing.expectEqual(@as(i64, 2026), c.year);
    try std.testing.expectEqual(@as(i64, 10), c.month);
    try std.testing.expectEqual(@as(i64, 31), c.day);
    try std.testing.expectEqual(@as(i64, 12), c.hour);
    try std.testing.expectEqual(@as(i64, 5), c.wday);
    try std.testing.expectEqual(@as(i64, 1793448000), timegm(2026, 10, 31, 12, 0, 0));
    try std.testing.expectEqual(@as(i64, 0), gmtime(0).wday - 3);
}

test "pyround ties to even" {
    try std.testing.expectEqual(@as(i64, 14), pyround(13.5));
    try std.testing.expectEqual(@as(i64, 16), pyround(16.5));
    try std.testing.expectEqual(@as(i64, 2), pyround(2.5));
    try std.testing.expectEqual(@as(i64, -2), pyround(-2.5));
    try std.testing.expectEqual(@as(i64, 3), pyround(2.51));
    try std.testing.expectEqual(@as(i64, -3), pyint(-3.7));
}
