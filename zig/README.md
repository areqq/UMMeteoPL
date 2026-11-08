# ummeteo — meteogram w czystym Zigu (0.17.1)

Port `meteogram.py` + `chart.py` + `render.py` do Ziga, na razie **obok** wtyczki:
samodzielna, statyczna binarka bez zależności, która pobiera prognozę UM z API
app.meteo.pl i zapisuje meteogram jako PNG. Rysuje **dokładnie te same piksele**
co Python (test `chart pixels equal the python renderer` porównuje SHA-256 surowych
pikseli z wynikiem `chart.Chart(...).draw()` na tej samej próbce, w skali 1,0 i 1,5).

```
ummeteo --id 2119 [--scale 1.5] [--out meteogram.png]
ummeteo --lat 52.2298 --lon 21.0117 --save-json odp.json
ummeteo --json odp.json --lat 52.2298 --lon 21.0117 --run 1793448000   # bez sieci
ummeteo -v                                                             # czasy etapów
```

Na sukces wypisuje jedną linię: `ok 1590x990 run=<unix> start=<unix> steps=60 out=<plik>`.

## Budowanie

```sh
export PATH=/home/q/zig-x86_64-linux-0.17.1:$PATH
zig build                                                   # natywnie, ReleaseFast
zig build test
zig build -Dtarget=mipsel-linux-musl -Dcpu=mips32 --prefix zig-out/mipsel              # Zgemma H3 (BCM7362)
zig build -Dtarget=arm-linux-musleabihf -Dcpu=cortex_a7-neon-d32 --prefix zig-out/arm-a7  # każdy ARMv7 (Zgemma H8.2H: A7 bez NEON, 16 rej. D)
zig build -Dtarget=arm-linux-musleabihf -Dcpu=cortex_a15 --prefix zig-out/arm           # Uno 4K SE (NEON); na A7 bez NEON = SIGILL
```

Dla ARM-a bezpieczny jest wariant `cortex_a7-neon-d32`: samo `-neon` nie wystarcza,
bo kompilator dalej używa rejestrów D16–D31, a Zgemma H8.2H (Hi3716MV430) ich nie ma
(sprawdzone 2026-11-08: `cortex_a7-neon` ginie z SIGILL od razu po starcie, `-neon-d32`
działa). MIPS: `mips32`, nie r2.

`src/glyphs.bin`, `src/coords.tsv` i `src/fixtures` to dowiązania do plików wtyczki
(`@embedFile` nie sięga poza katalog modułu). Katalog `zig/` nie trafia do paczki
wtyczki (`scripts/publish.sh` go wyklucza).

## Pliki

| plik | rola |
|---|---|
| `src/forecast.zig` | serie, JSON `available` i `um4_60`, treść POST, `coords.tsv` |
| `src/api.zig` | `std.http.Client`; pakiet CA czytany ręcznie (jądro 4.10 nie ma `statx`, więc `Bundle.rescan` std by padł) |
| `src/chart.zig` | układ meteogramu, linia po linii za `chart.py` (Python `round` = do parzystej: `timeutil.pyround`) |
| `src/render.zig` | płótno RGB, scanline polygon, linie jako prostokąty-odcinki, glify z `glyphs.bin` |
| `src/png.zig` | PNG RGB, filtr 0; poziom 0 = bloki `stored` (bez kompresji), 1–9 = deflate |
| `src/timeutil.zig` | kalendarz UTC, czas polski (reguła UE), wschód/zachód słońca, D°M'S" |
| `src/main.zig` | CLI, strażnik limitu czasu (wątek + `Io.sleep` + `exit 3`) |

## Zmierzone (skala 1,5)

| etap | Python 26.11.08, Zgemma H3 | Zig, Zgemma H3 (MIPS 750 MHz) | Zig, Zgemma H8.2H (Cortex-A7) |
|---|---|---|---|
| czcionki | — (import) | 32 ms | 14 ms |
| pakiet CA (120 certów) | — | 19–58 ms | 9 ms |
| lista przebiegów (TLS + GET) | — | ~390 ms | ~270 ms |
| prognoza (POST) | — | ~70 ms | ~60 ms |
| rysowanie | 3,5–4 s | 86–91 ms | 29 ms |
| PNG bez kompresji (4,7 MB) | 0,5 s (zlib 3) | 240 ms | 110 ms |
| PNG deflate poziom 1 / 4 / 6 | — | 1,0 / 1,1 / 1,5 s | — |
| całość z pobraniem | ~5 s | 0,9 s | 0,5 s |

Oba dekodery mają jądro bez `statx` (4.10 i 4.4) — ręczne wczytanie pakietu CA działa
na obu. Na H8.2H (skórka HD, skala 1) rysowanie 18 ms, PNG 51 ms.

ReleaseSmall (1,4 MB zamiast 2,5 MB) rysuje 1,6× wolniej, kompresuje 2× wolniej —
zostaje ReleaseFast. Suma SHA-256 pikseli na dekoderze = na PC = Python.

## Integracja z wtyczką (jeszcze nie)

Wtyczka nadal rysuje w Pythonie. Plan: Meteo.py woła binarkę pasującą do
architektury (`--id`, `--scale`, `--out` w katalogu tymczasowym), a gdy jej nie ma
albo zwróci błąd, wraca do Pythona.
