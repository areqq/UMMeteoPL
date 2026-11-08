//! ummeteo: the UM meteogram of meteo.pl as a PNG, drawn on the box.
//!
//!   ummeteo --id 2119 [--scale 1.5] [--out meteogram.png]
//!   ummeteo --lat 52.2298 --lon 21.0117 ...
//!   ummeteo --json saved.json --lat .. --lon .. [--run 1793448000]   (offline render)
//!
//! Prints one line on success: `ok <w>x<h> run=<unix> start=<unix> steps=<n> out=<path>`.
const std = @import("std");
const Io = std.Io;
const fc = @import("forecast.zig");
const chart = @import("chart.zig");
const render = @import("render.zig");
const png = @import("png.zig");
const api = @import("api.zig");

pub const std_options: std.Options = .{
    // software AES/TLS at full speed; the forecast is public data
    .side_channels_mitigations = .none,
};

const usage =
    \\użycie: ummeteo (--id ID | --lat LAT --lon LON) [opcje]
    \\  --id ID          miejscowość z katalogu wtyczki (coords.tsv)
    \\  --lat/--lon      współrzędne punktu
    \\  --scale S        skala wykresu (1 = 1060x660, 1.5 = FullHD, 2 = WQHD; domyślnie 1.5)
    \\  --out PLIK       plik PNG (domyślnie meteogram.png)
    \\  --json PLIK      zamiast pobierać: narysuj z zapisanej odpowiedzi API
    \\  --run UNIX       czas przebiegu modelu dla --json (domyślnie 0)
    \\  --save-json PLIK zapisz odpowiedź API
    \\  --ca PLIK        pakiet CA (domyślnie /etc/ssl/certs/ca-certificates.crt)
    \\  --level N        kompresja PNG: 0 = bez (domyślnie, najszybsza), 1..9 = deflate
    \\  --timeout S      limit czasu całości (domyślnie 60)
    \\  -v               czasy etapów na stderr
    \\
;

const Options = struct {
    id: ?[]const u8 = null,
    lat: ?f64 = null,
    lon: ?f64 = null,
    scale: f64 = 1.5,
    out: []const u8 = "meteogram.png",
    json: ?[]const u8 = null,
    run: i64 = 0,
    save_json: ?[]const u8 = null,
    ca: []const u8 = api.default_ca_path,
    level: u8 = 0,
    timeout: u64 = 60,
    verbose: bool = false,
};

fn parseArgs(it: *std.process.Args.Iterator) !Options {
    var o: Options = .{};
    _ = it.skip();
    while (it.next()) |arg| {
        if (std.mem.eql(u8, arg, "-v")) {
            o.verbose = true;
        } else if (std.mem.eql(u8, arg, "-h") or std.mem.eql(u8, arg, "--help")) {
            return error.Help;
        } else {
            const val = it.next() orelse return error.MissingValue;
            if (std.mem.eql(u8, arg, "--id")) {
                o.id = val;
            } else if (std.mem.eql(u8, arg, "--lat")) {
                o.lat = try std.fmt.parseFloat(f64, val);
            } else if (std.mem.eql(u8, arg, "--lon")) {
                o.lon = try std.fmt.parseFloat(f64, val);
            } else if (std.mem.eql(u8, arg, "--scale")) {
                o.scale = try std.fmt.parseFloat(f64, val);
            } else if (std.mem.eql(u8, arg, "--out")) {
                o.out = val;
            } else if (std.mem.eql(u8, arg, "--json")) {
                o.json = val;
            } else if (std.mem.eql(u8, arg, "--run")) {
                o.run = try std.fmt.parseInt(i64, val, 10);
            } else if (std.mem.eql(u8, arg, "--save-json")) {
                o.save_json = val;
            } else if (std.mem.eql(u8, arg, "--ca")) {
                o.ca = val;
            } else if (std.mem.eql(u8, arg, "--level")) {
                o.level = try std.fmt.parseInt(u8, val, 10);
                if (o.level > 9) return error.BadLevel;
            } else if (std.mem.eql(u8, arg, "--timeout")) {
                o.timeout = try std.fmt.parseInt(u64, val, 10);
            } else {
                return error.UnknownOption;
            }
        }
    }
    if (o.scale < 0.5 or o.scale > 4) return error.BadScale;
    return o;
}

fn watchdog(io: Io, secs: u64) void {
    Io.sleep(io, Io.Duration.fromSeconds(@intCast(secs)), .awake) catch {};
    std.debug.print("ummeteo: przekroczony limit czasu {d} s\n", .{secs});
    std.process.exit(3);
}

const Timer = struct {
    io: Io,
    last: Io.Timestamp,
    on: bool,

    fn init(io: Io, on: bool) Timer {
        return .{ .io = io, .last = Io.Clock.awake.now(io), .on = on };
    }

    fn lap(t: *Timer, what: []const u8) void {
        if (!t.on) return;
        const now = Io.Clock.awake.now(t.io);
        const ms = @divFloor(t.last.durationTo(now).nanoseconds, std.time.ns_per_ms);
        std.debug.print("  {s}: {d} ms\n", .{ what, ms });
        t.last = now;
    }
};

pub fn main(init: std.process.Init) !void {
    const gpa = init.gpa;
    const io = init.io;
    var args_it = std.process.Args.Iterator.init(init.minimal.args);
    const opts = parseArgs(&args_it) catch |e| {
        std.debug.print("{s}", .{usage});
        if (e == error.Help) return;
        std.debug.print("ummeteo: błędne argumenty ({t})\n", .{e});
        std.process.exit(2);
    };
    if (opts.timeout > 0) {
        const t = try std.Thread.spawn(.{}, watchdog, .{ io, opts.timeout });
        t.detach();
    }
    var timer = Timer.init(io, opts.verbose);

    // the point
    var lat = opts.lat;
    var lon = opts.lon;
    if (opts.id) |id| {
        const c = fc.lookupCoords(fc.coords_table, id) orelse {
            std.debug.print("ummeteo: brak współrzędnych lokalizacji {s}\n", .{id});
            std.process.exit(1);
        };
        lat = c.lat;
        lon = c.lon;
    }
    if (lat == null or lon == null) {
        std.debug.print("{s}ummeteo: podaj --id albo --lat i --lon\n", .{usage});
        std.process.exit(2);
    }

    var fonts = try render.loadFonts(gpa);
    defer fonts.deinit(gpa);
    timer.lap("czcionki");

    var forecast: fc.Forecast = undefined;
    if (opts.json) |path| {
        const raw = try api.readWholeFile(gpa, io, path);
        defer gpa.free(raw);
        forecast = try fc.parseForecast(gpa, raw, opts.run, lat.?, lon.?);
        timer.lap("json z pliku");
    } else {
        var client = api.Client.init(gpa, io, opts.ca) catch |e| {
            std.debug.print("ummeteo: pakiet CA {s}: {t}\n", .{ opts.ca, e });
            std.process.exit(1);
        };
        defer client.deinit();
        if (opts.verbose) std.debug.print("  certyfikaty CA: {d}\n", .{client.certs});
        timer.lap("pakiet CA");
        const avail_raw = client.get(fc.api ++ "/available") catch |e| {
            std.debug.print("ummeteo: brak połączenia z meteo.pl ({t})\n", .{e});
            std.process.exit(1);
        };
        defer gpa.free(avail_raw);
        const runs = fc.parseAvailable(gpa, avail_raw) catch |e| {
            std.debug.print("ummeteo: meteo.pl: nieznana lista prognoz ({t})\n", .{e});
            std.process.exit(1);
        };
        defer gpa.free(runs);
        if (runs.len == 0) {
            std.debug.print("ummeteo: meteo.pl nie ma żadnej prognozy\n", .{});
            std.process.exit(1);
        }
        timer.lap("lista przebiegów");
        // the newest run can still be incomplete on the server: fall back to the one before
        var got = false;
        var last_err: anyerror = error.NoForecast;
        for (runs[0..@min(2, runs.len)]) |run_time| {
            var body_buf: [128]u8 = undefined;
            const body = fc.requestBody(&body_buf, lat.?, lon.?, run_time);
            const raw = client.post(fc.api ++ "/" ++ fc.model, body) catch |e| {
                last_err = e;
                continue;
            };
            defer gpa.free(raw);
            forecast = fc.parseForecast(gpa, raw, run_time, lat.?, lon.?) catch |e| {
                last_err = e;
                continue;
            };
            if (opts.save_json) |sp| try Io.Dir.cwd().writeFile(io, .{ .sub_path = sp, .data = raw });
            got = true;
            break;
        }
        if (!got) {
            std.debug.print("ummeteo: meteo.pl: nieznana odpowiedź ({t})\n", .{last_err});
            std.process.exit(1);
        }
        timer.lap("prognoza");
    }
    defer fc.freeForecast(gpa, &forecast);

    const pic = try chart.renderRgb(gpa, &fonts, &forecast, opts.scale);
    defer gpa.free(pic.px);
    timer.lap("rysowanie");
    const bytes = try png.encode(gpa, pic.width, pic.height, pic.px, opts.level);
    defer gpa.free(bytes);
    timer.lap("png");
    try Io.Dir.cwd().writeFile(io, .{ .sub_path = opts.out, .data = bytes });
    timer.lap("zapis");

    var out_buf: [256]u8 = undefined;
    var w = Io.File.stdout().writerStreaming(io, &out_buf);
    try w.interface.print("ok {d}x{d} run={d} start={d} steps={d} out={s}\n", .{ pic.width, pic.height, forecast.run_time, forecast.start, forecast.steps, opts.out });
    try w.interface.flush();
}
