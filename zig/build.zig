const std = @import("std");

// zig build                                              native, ReleaseFast
// zig build -Dtarget=mipsel-linux-musl -Dcpu=mips32      Zgemma H3 (BCM7362, o32, little-endian)
// zig build -Dtarget=arm-linux-musleabihf -Dcpu=cortex_a7-neon-d32   every ARMv7 box (Zgemma H8.2H: A7, no NEON, D16)
// zig build -Dtarget=arm-linux-musleabihf -Dcpu=cortex_a15           Uno 4K SE (NEON); SIGILL on an A7 without NEON
// zig build test
// zig build release                                       the four binaries the plugin ships: zig-out/release/<arch>/ummeteo
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

    // `zig build release`: bin/ummeteo-<arch> of the plugin (scripts/publish.sh copies
    // them, install.sh keeps the one matching `uname -m`; renderer.py picks the same way)
    const release = b.step("release", "Build the plugin's binaries for every supported box");
    const Row = struct { name: []const u8, q: std.Target.Query };
    const rows = [_]Row{
        // Zgemma H3 and other BCM73xx: MIPS32 r1 (r2 is an illegal instruction there), little-endian o32
        .{ .name = "mipsel", .q = .{ .cpu_arch = .mipsel, .os_tag = .linux, .abi = .musl, .cpu_model = .{ .explicit = &std.Target.mips.cpu.mips32 } } },
        // every ARMv7 box: Cortex-A7 without NEON and with 16 D registers (Zgemma H8.2H has no more)
        .{ .name = "arm", .q = .{ .cpu_arch = .arm, .os_tag = .linux, .abi = .musleabihf, .cpu_model = .{ .explicit = &std.Target.arm.cpu.cortex_a7 }, .cpu_features_sub = std.Target.arm.featureSet(&.{ .neon, .d32 }) } },
        .{ .name = "aarch64", .q = .{ .cpu_arch = .aarch64, .os_tag = .linux, .abi = .musl } },
        // enigma2 built for a PC (the test containers)
        .{ .name = "x86_64", .q = .{ .cpu_arch = .x86_64, .os_tag = .linux, .abi = .musl } },
    };
    for (rows) |r| {
        const bin = b.addExecutable(.{
            .name = "ummeteo",
            .root_module = b.createModule(.{
                .root_source_file = b.path("src/main.zig"),
                .target = b.resolveTargetQuery(r.q),
                .optimize = .fast,
                .strip = true,
            }),
        });
        const install = b.addInstallArtifact(bin, .{ .dest_dir = .{ .override = .{ .custom = b.fmt("release/{s}", .{r.name}) } } });
        release.dependOn(&install.step);
    }
}
