const std = @import("std");

// zig build                                              native, ReleaseFast
// zig build -Dtarget=mipsel-linux-musl -Dcpu=mips32      Zgemma H3 (BCM7362, o32, little-endian)
// zig build -Dtarget=arm-linux-musleabihf -Dcpu=cortex_a7-neon-d32   every ARMv7 box (Zgemma H8.2H: A7, no NEON, D16)
// zig build -Dtarget=arm-linux-musleabihf -Dcpu=cortex_a15           Uno 4K SE (NEON); SIGILL on an A7 without NEON
// zig build test
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.option(std.builtin.OptimizeMode, "optimize", "Optimization mode (default: ReleaseFast)") orelse .fast;
    const strip = b.option(bool, "strip", "Strip symbols and debug info (default: not in Debug)") orelse (optimize != .debug);

    const exe = b.addExecutable(.{
        .name = "ummeteo",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .strip = strip,
        }),
    });
    b.installArtifact(exe);

    const tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/tests.zig"),
            .target = target,
            .optimize = if (optimize == .debug) .debug else .safe,
        }),
    });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
