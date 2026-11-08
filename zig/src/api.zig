//! HTTPS to the meteo.pl API with std.http.Client. The system CA bundle is read by
//! hand: std's `Bundle.rescan` sizes the file with `statx`, which the 4.10 kernel
//! of a Zgemma H3 does not have, so the PEM is read in a plain loop and parsed with
//! the bundle's own `parseCert`.
const std = @import("std");
const Io = std.Io;
const fc = @import("forecast.zig");

pub const default_ca_path = "/etc/ssl/certs/ca-certificates.crt";

pub const Client = struct {
    http: std.http.Client,
    gpa: std.mem.Allocator,
    io: Io,
    certs: usize = 0,

    pub fn init(gpa: std.mem.Allocator, io: Io, ca_path: []const u8) !Client {
        var c: Client = .{ .http = .{ .allocator = gpa, .io = io }, .gpa = gpa, .io = io };
        try c.loadCa(ca_path);
        return c;
    }

    pub fn deinit(c: *Client) void {
        c.http.deinit();
    }

    fn loadCa(c: *Client, path: []const u8) !void {
        const pem = try readWholeFile(c.gpa, c.io, path);
        defer c.gpa.free(pem);
        const now = Io.Clock.real.now(c.io);
        var bundle: std.crypto.Certificate.Bundle = .empty;
        errdefer bundle.deinit(c.gpa);
        c.certs = try addPem(&bundle, c.gpa, pem, now.toSeconds());
        c.http.ca_bundle = bundle;
        c.http.now = now; // non-null: the client will not rescan
    }

    pub fn get(c: *Client, url: []const u8) ![]u8 {
        return c.fetch(url, .GET, null);
    }

    pub fn post(c: *Client, url: []const u8, body: []const u8) ![]u8 {
        return c.fetch(url, .POST, body);
    }

    fn fetch(c: *Client, url: []const u8, method: std.http.Method, body: ?[]const u8) ![]u8 {
        var aw = Io.Writer.Allocating.init(c.gpa);
        errdefer aw.deinit();
        const res = try c.http.fetch(.{
            .location = .{ .url = url },
            .method = method,
            .payload = body,
            .response_writer = &aw.writer,
            .headers = .{
                .user_agent = .{ .override = fc.user_agent },
                .content_type = if (body != null) .{ .override = "application/json" } else .default,
            },
        });
        if (res.status != .ok) {
            std.debug.print("ummeteo: meteo.pl odpowiada błędem {d}\n", .{@backingInt(res.status)});
            return error.HttpStatus;
        }
        return aw.toOwnedSlice();
    }
};

/// Whole file without `stat` (open + read loop).
pub fn readWholeFile(gpa: std.mem.Allocator, io: Io, path: []const u8) ![]u8 {
    const f = if (std.fs.path.isAbsolute(path)) try Io.Dir.openFileAbsolute(io, path, .{}) else try Io.Dir.cwd().openFile(io, path, .{});
    defer f.close(io);
    var list: std.ArrayList(u8) = .empty;
    errdefer list.deinit(gpa);
    var buf: [64 * 1024]u8 = undefined;
    while (true) {
        const n = f.readStreaming(io, &.{&buf}) catch |e| switch (e) {
            error.EndOfStream => break, // readStreaming signals EOF with an error, 0 means "try again"
            else => return e,
        };
        try list.appendSlice(gpa, buf[0..n]);
    }
    return list.toOwnedSlice(gpa);
}

/// Like Bundle.addCertsFromFile, from memory. Returns the number of certificates kept.
fn addPem(cb: *std.crypto.Certificate.Bundle, gpa: std.mem.Allocator, pem: []const u8, now_sec: i64) !usize {
    const decoded_upper = pem.len / 4 * 3;
    try cb.bytes.ensureUnusedCapacity(gpa, decoded_upper);
    const begin_marker = "-----BEGIN CERTIFICATE-----";
    const end_marker = "-----END CERTIFICATE-----";
    const decoder = std.base64.standard.decoderWithIgnore(" \t\r\n");
    var count: usize = 0;
    var start: usize = 0;
    while (std.mem.indexOfPos(u8, pem, start, begin_marker)) |b| {
        const cert_start = b + begin_marker.len;
        const cert_end = std.mem.indexOfPos(u8, pem, cert_start, end_marker) orelse return error.MissingEndCertificateMarker;
        start = cert_end + end_marker.len;
        const encoded = std.mem.trim(u8, pem[cert_start..cert_end], " \t\r\n");
        const decoded_start: u32 = @intCast(cb.bytes.items.len);
        const dest = cb.bytes.allocatedSlice()[decoded_start..];
        const n = decoder.decode(dest, encoded) catch continue;
        cb.bytes.items.len += n;
        const before = cb.map.count();
        cb.parseCert(gpa, decoded_start, now_sec) catch {
            cb.bytes.items.len = decoded_start;
            continue;
        };
        if (cb.map.count() > before) count += 1;
    }
    return count;
}

test "pem parsing keeps valid certificates" {
    // the system store, when present on the test machine
    const pem = readWholeFile(std.testing.allocator, std.testing.io, default_ca_path) catch return;
    defer std.testing.allocator.free(pem);
    var bundle: std.crypto.Certificate.Bundle = .empty;
    defer bundle.deinit(std.testing.allocator);
    const n = try addPem(&bundle, std.testing.allocator, pem, 1_793_448_000);
    try std.testing.expect(n > 50);
}
