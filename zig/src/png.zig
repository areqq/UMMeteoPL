//! Minimal PNG writer: 8-bit RGB, filter 0 on every row, one zlib IDAT. The same
//! layout render.py produces, so a decoder sees the same picture either way.
//!
//! Level 0 (the default of the CLI) writes stored deflate blocks: no compression
//! at all. On a 750 MHz MIPS the flate matcher took ~1 s for the 4.7 MB of a
//! FullHD chart, while the file only goes to a tmpfs and is decoded once by
//! ePicLoad, so the bytes are cheaper than the CPU.
const std = @import("std");
const Io = std.Io;

/// `level`: 0 = stored blocks (no compression), 1..9 = flate levels.
pub fn encode(gpa: std.mem.Allocator, width: u32, height: u32, rgb: []const u8, level: u8) ![]u8 {
    const stride: usize = @as(usize, width) * 3;
    std.debug.assert(rgb.len == stride * height);
    // filter byte 0 in front of every row
    const raw = try gpa.alloc(u8, (stride + 1) * height);
    defer gpa.free(raw);
    var y: usize = 0;
    while (y < height) : (y += 1) {
        raw[y * (stride + 1)] = 0;
        @memcpy(raw[y * (stride + 1) + 1 ..][0..stride], rgb[y * stride ..][0..stride]);
    }
    var idat = try Io.Writer.Allocating.initCapacity(gpa, if (level == 0) raw.len + raw.len / 1000 + 64 else raw.len / 4 + 1024);
    defer idat.deinit();
    const window = try gpa.alloc(u8, std.compress.flate.max_window_len);
    defer gpa.free(window);
    if (level == 0) {
        var stored = try std.compress.flate.Compress.Raw.init(&idat.writer, window, .zlib);
        try stored.writer.writeAll(raw);
        try stored.finish();
    } else {
        var comp = try std.compress.flate.Compress.init(&idat.writer, window, .zlib, levelOptions(level));
        try comp.writer.writeAll(raw);
        try comp.finish();
    }
    try idat.writer.flush();

    var out = try Io.Writer.Allocating.initCapacity(gpa, idat.written().len + 64);
    errdefer out.deinit();
    const w = &out.writer;
    try w.writeAll("\x89PNG\r\n\x1a\n");
    var ihdr: [13]u8 = undefined;
    std.mem.writeInt(u32, ihdr[0..4], width, .big);
    std.mem.writeInt(u32, ihdr[4..8], height, .big);
    ihdr[8] = 8; // bit depth
    ihdr[9] = 2; // colour type: RGB
    ihdr[10] = 0;
    ihdr[11] = 0;
    ihdr[12] = 0;
    try chunk(w, "IHDR", &ihdr);
    try chunk(w, "IDAT", idat.written());
    try chunk(w, "IEND", "");
    return out.toOwnedSlice();
}

fn levelOptions(level: u8) std.compress.flate.Compress.Options {
    const O = std.compress.flate.Compress.Options;
    return switch (level) {
        1 => O.level_1,
        2 => O.level_2,
        3 => O.level_3,
        4 => O.level_4,
        5 => O.level_5,
        6 => O.level_6,
        7 => O.level_7,
        8 => O.level_8,
        else => O.level_9,
    };
}

fn chunk(w: *Io.Writer, kind: *const [4]u8, data: []const u8) !void {
    try w.writeInt(u32, @intCast(data.len), .big);
    try w.writeAll(kind);
    try w.writeAll(data);
    var crc = std.hash.Crc32.init();
    crc.update(kind);
    crc.update(data);
    try w.writeInt(u32, crc.final(), .big);
}

test "png header" {
    const gpa = std.testing.allocator;
    const px = [_]u8{ 255, 0, 0, 0, 255, 0 };
    const png = try encode(gpa, 2, 1, &px, 4);
    defer gpa.free(png);
    const stored = try encode(gpa, 2, 1, &px, 0);
    defer gpa.free(stored);
    try std.testing.expect(stored.len > png.len - 8); // stored: 7 raw bytes + zlib framing
    try std.testing.expectEqualSlices(u8, "\x89PNG\r\n\x1a\n", png[0..8]);
    try std.testing.expectEqual(@as(u32, 2), std.mem.readInt(u32, png[16..20], .big));
    try std.testing.expectEqual(@as(u32, 1), std.mem.readInt(u32, png[20..24], .big));
    try std.testing.expectEqualSlices(u8, "IEND", png[png.len - 8 .. png.len - 4]);
}
