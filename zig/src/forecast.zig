//! The meteo.pl UM forecast for a point (meteogram.py): series names, the JSON of
//! /meteorograms/available and /meteorograms/um4_60, the request body, coords.tsv.
const std = @import("std");
const tu = @import("timeutil.zig");

pub const api = "https://devmgramapi.meteo.pl/meteorograms";
pub const model = "um4_60";
pub const user_agent = "UMMeteoPL (enigma2 plugin, zig)";
/// The API marks 'no value' with a huge negative number.
pub const missing: f64 = -1e6;

pub const Series = enum {
    airtmp_point,
    airtmp_min,
    airtmp_max,
    grdtmp_min,
    grdtmp_max,
    dwptmp_point,
    wchill_point,
    wchill_min,
    wchill_max,
    pcpttl_aver,
    pcpttl_max,
    pcpttl_type_max,
    pcpttlprob_point,
    storm_max,
    flash_max,
    realhum_aver,
    slpres_point,
    wind10_sd_true_prev_point,
    wind_gust_max,
    wind10_dr_deg_true_prev_point,
    cldbse01,
    cldbse25,
    cldbse45,
    cldbse65,
    cldbse79,
    cldtop,
    visibl_min,
    cldvlow_aver,
    cldlow_aver,
    cldmed_aver,
    cldhigh_aver,
    cldtot_aver,
    fog_max,
};
pub const series_count = @typeInfo(Series).@"enum".field_names.len;

/// pcpttl_type_max codes (app.meteo.pl: none, rain, snow, sleet)
pub const rain = 1;
pub const snow = 2;
pub const sleet = 3;

pub const Forecast = struct {
    run_time: i64, // model run, unix time (UTC)
    start: i64, // first hourly value, unix time
    interval: i64, // seconds between values (3600)
    lat: f64,
    lon: f64,
    row: ?i64,
    col: ?i64,
    steps: usize,
    series: [series_count][]?f64,

    pub fn get(f: *const Forecast, s: Series) []const ?f64 {
        return f.series[@backingInt(s)];
    }

    /// "31.10.2026 06 UTC" - the status line of the meteogram screen.
    pub fn run(f: *const Forecast, buf: []u8) []const u8 {
        const c = tu.gmtime(f.run_time);
        return std.fmt.bufPrint(buf, "{d:0>2}.{d:0>2}.{d} {d:0>2} UTC", .{ @as(u64, @intCast(c.day)), @as(u64, @intCast(c.month)), @as(u64, @intCast(c.year)), @as(u64, @intCast(c.hour)) }) catch unreachable;
    }

    pub fn timeAt(f: *const Forecast, i: usize) i64 {
        return f.start + @as(i64, @intCast(i)) * f.interval;
    }
};

pub const Error = error{ UnknownAvailableList, UnknownResponse, EmptyForecast, NoCoordinates };

fn numberOf(v: std.json.Value) ?f64 {
    return switch (v) {
        .integer => |i| @floatFromInt(i),
        .float => |x| x,
        .number_string => |s| std.fmt.parseFloat(f64, s) catch null,
        .string => |s| std.fmt.parseFloat(f64, s) catch null,
        else => null,
    };
}

fn intOf(v: std.json.Value) ?i64 {
    return switch (v) {
        .integer => |i| i,
        .float => |x| @intFromFloat(x),
        .number_string, .string => |s| std.fmt.parseInt(i64, s, 10) catch null,
        else => null,
    };
}

/// /meteorograms/available -> model runs (unix time), newest first. Allocated with `gpa`.
pub fn parseAvailable(gpa: std.mem.Allocator, raw: []const u8) ![]i64 {
    var arena = std.heap.ArenaAllocator.init(gpa);
    defer arena.deinit();
    const doc = std.json.parseFromSliceLeaky(std.json.Value, arena.allocator(), raw, .{}) catch return Error.UnknownAvailableList;
    const obj = switch (doc) {
        .object => |o| o,
        else => return Error.UnknownAvailableList,
    };
    const list = obj.get(model) orelse return Error.UnknownAvailableList;
    const arr = switch (list) {
        .array => |a| a,
        else => return Error.UnknownAvailableList,
    };
    var runs = try gpa.alloc(i64, arr.items.len);
    errdefer gpa.free(runs);
    for (arr.items, 0..) |item, i| runs[i] = intOf(item) orelse return Error.UnknownAvailableList;
    std.mem.sort(i64, runs, {}, std.sort.desc(i64));
    return runs;
}

/// POST /meteorograms/<model> response -> Forecast (series allocated with `gpa`).
pub fn parseForecast(gpa: std.mem.Allocator, raw: []const u8, run_time: i64, lat: f64, lon: f64) !Forecast {
    var arena = std.heap.ArenaAllocator.init(gpa);
    defer arena.deinit();
    const doc = std.json.parseFromSliceLeaky(std.json.Value, arena.allocator(), raw, .{}) catch return Error.UnknownResponse;
    const data = switch (doc) {
        .object => |o| switch (o.get("data") orelse return Error.UnknownResponse) {
            .object => |d| d,
            else => return Error.UnknownResponse,
        },
        else => return Error.UnknownResponse,
    };
    const ref = switch (data.get("airtmp_point") orelse return Error.UnknownResponse) {
        .object => |o| o,
        else => return Error.UnknownResponse,
    };
    const start = intOf(ref.get("first_timestamp") orelse return Error.UnknownResponse) orelse return Error.UnknownResponse;
    const interval = intOf(ref.get("interval") orelse return Error.UnknownResponse) orelse return Error.UnknownResponse;
    const ref_data = switch (ref.get("data") orelse return Error.UnknownResponse) {
        .array => |a| a,
        else => return Error.UnknownResponse,
    };
    const steps = ref_data.items.len;
    if (steps < 2 or interval <= 0) return Error.EmptyForecast;

    var out: Forecast = .{ .run_time = run_time, .start = start, .interval = interval, .lat = lat, .lon = lon, .row = null, .col = null, .steps = steps, .series = undefined };
    inline for (@typeInfo(Series).@"enum".field_names, 0..) |name, idx| {
        const values = try gpa.alloc(?f64, steps);
        @memset(values, null);
        if (data.get(name)) |item| {
            if (item == .object) {
                if (item.object.get("data")) |d| {
                    if (d == .array) {
                        for (d.array.items, 0..) |v, i| {
                            if (i >= steps) break;
                            if (numberOf(v)) |x| {
                                if (x >= missing) values[i] = x;
                            }
                        }
                    }
                }
            }
        }
        out.series[idx] = values;
    }
    if (ref.get("point")) |pt| {
        if (pt == .object) {
            if (pt.object.get("row")) |r| out.row = intOf(r);
            if (pt.object.get("col")) |c| out.col = intOf(c);
        }
    }
    return out;
}

pub fn freeForecast(gpa: std.mem.Allocator, f: *Forecast) void {
    for (f.series) |s| gpa.free(s);
}

/// The JSON document app.meteo.pl posts: {"point": {"lat": "52.2298", "lon": "21.0117"}, "date": 1793448000}
pub fn requestBody(buf: []u8, lat: f64, lon: f64, run_time: i64) []const u8 {
    return std.fmt.bufPrint(buf, "{{\"point\": {{\"lat\": \"{d:.4}\", \"lon\": \"{d:.4}\"}}, \"date\": {d}}}", .{ lat, lon, run_time }) catch unreachable;
}

pub const Coords = struct { lat: f64, lon: f64 };

/// coords.tsv (embedded): location id -> coordinates.
pub fn lookupCoords(table: []const u8, id: []const u8) ?Coords {
    var lines = std.mem.splitScalar(u8, table, '\n');
    while (lines.next()) |line| {
        var cols = std.mem.tokenizeAny(u8, line, " \t\r");
        const first = cols.next() orelse continue;
        if (!std.mem.eql(u8, first, id)) continue;
        const lat = std.fmt.parseFloat(f64, cols.next() orelse continue) catch continue;
        const lon = std.fmt.parseFloat(f64, cols.next() orelse continue) catch continue;
        return .{ .lat = lat, .lon = lon };
    }
    return null;
}

pub const coords_table = @embedFile("coords.tsv");

test "available list, newest first" {
    const runs = try parseAvailable(std.testing.allocator, @embedFile("fixtures/available_2026-10-31.json"));
    defer std.testing.allocator.free(runs);
    try std.testing.expectEqual(@as(i64, 1793448000), runs[0]);
    try std.testing.expect(runs[1] < runs[0]);
}

test "forecast fixture" {
    const gpa = std.testing.allocator;
    var f = try parseForecast(gpa, @embedFile("fixtures/um4_60_warszawa_2026-10-31.json"), 1793448000, 52.2298, 21.0117);
    defer freeForecast(gpa, &f);
    try std.testing.expectEqual(@as(usize, 60), f.steps);
    try std.testing.expectEqual(@as(i64, 1793451600), f.start);
    try std.testing.expectEqual(@as(i64, 3600), f.interval);
    try std.testing.expectEqual(@as(?i64, 212), f.row);
    try std.testing.expectEqual(@as(?i64, 252), f.col);
    try std.testing.expectEqual(@as(?f64, 9.475), f.get(.airtmp_point)[0]);
    var buf: [32]u8 = undefined;
    try std.testing.expectEqualStrings("31.10.2026 12 UTC", f.run(&buf));
    var body: [96]u8 = undefined;
    try std.testing.expectEqualStrings("{\"point\": {\"lat\": \"52.2298\", \"lon\": \"21.0117\"}, \"date\": 1793448000}", requestBody(&body, 52.2298, 21.0117, 1793448000));
}

test "coords table" {
    const c = lookupCoords(coords_table, "2119") orelse return error.TestUnexpectedResult;
    try std.testing.expect(c.lat > 52 and c.lat < 53);
    try std.testing.expect(lookupCoords(coords_table, "999999") == null);
}
