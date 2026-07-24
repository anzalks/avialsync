# DECISIONS.md — lightweight ADR log
Format per entry: date · decision · context · alternatives rejected · consequences.
Agents: read before coding; append when making irreversible choices; never silently reverse entries.

## 2026-07 · D-001 · Master time = float64 seconds, UTC epoch
Context: need one representation across video, 50 kHz data, UI. Alternatives: int ns (rerun-style),
per-source relative time. float64 gives ~µs precision at epoch scale — sufficient (50 kHz = 20 µs
sample spacing); simpler math everywhere. Consequence: never use float32 for time anywhere.

## 2026-07 · D-002 · Video playback = libmpv only
Alternatives rejected: QtMultimedia (inaccurate seeks), OpenCV (no proper playback pipeline),
GStreamer (dependency pain on Windows/macOS). Consequence: bundle LGPL mpv in installers.

## 2026-07 · D-003 · License Apache-2.0; no GPL deps
Enables commercialization and permissive reuse. PyQt (GPL) banned; PySide6 (LGPL) allowed.

## 2026-07 · D-004 · Sidecar cache format
Parsed time series → `<file>.kcache/` dir: `meta.json`, `t.npy`-style raw mmap arrays per channel,
`pyr_16.bin`/`pyr_256.bin`/`pyr_4096.bin` min/max pairs. Invalidation key: (path, size, mtime, loader
version). Alternatives: HDF5 (heavy dep), Parquet-only (no mmap random access win for pyramids).

## 2026-07 · D-005 · Chunked ingest is the only ingest path
TimeSeriesSource.read_chunks() iterator; cache builder pulls incrementally. Enables 50 GB files
and streaming later without API break. Full-array loading banned even for small files.

## 2026-07 · D-006 · VideoSource conversion hook is first-class
needs_conversion()/prepare() in the ABC. Image sequences, .cine, split files are plugins, not hacks.

## 2026-07 · D-007 · Frame stepping uses actual frame timestamps
Never 1/fps arithmetic. VFR and dropped-frame footage are normal field conditions.

## 2026-07 · D-008 · Cache key gets content-hash tail
(path, size, mtime, loader_version, xxhash first+last 64 KB). Supersedes D-004 key. Stale-cache
silence is a trust-destroying bug class in a measurement tool.

## 2026-07 · D-009 · Gaps and NaN are rendered honestly
gap_mask at 10× median dt; lines break at gaps; NaN skipped via nanmin/nanmax; sentinel→NaN only
by explicit user config. We never invent data the logger didn't record.

## 2026-07 · D-010 · No-data state is uniform and explicit
Outside a source's bounds: dimmed placeholder (video), empty axis (plot), "—" (readout). Never
freeze the last frame. Timeline = union of source bounds with coverage shading.

## 2026-07 · D-011 · macOS mpv path built first
Render-API embedding on macOS is the project's highest integration risk; Phase 2 starts there.

## 2026-07 · D-012 · Distribution channels & zero-step guarantee
Release = ONE tag → CI builds ALL channels: (a) OS installers (Inno .exe, .dmg, AppImage) with
LGPL libmpv + ffmpeg BUNDLED — end user does nothing but install & run; (b) PyPI wheel+sdist —
pip users get everything Python-side automatically; libmpv/ffmpeg gap handled by startup probe
(D-013) and Windows auto-fetch (D-014). conda-forge recipe as supplementary channel.
Never ship a release where installers and PyPI are out of version sync.

## 2026-07 · D-013 · Lazy mpv import + startup probe (never crash on missing libmpv)
`import mpv` is FORBIDDEN at module top level anywhere. video_pane imports lazily after
diagnostics probes for libmpv. Missing lib → app still opens, shows an OS-detected dialog with
the exact install one-liner (apt/dnf/pacman/brew) or the Windows auto-fetch offer. A ctypes
traceback at launch is a release-blocking bug.

## 2026-07 · D-014 · Windows pip auto-fetch of libmpv
First run without libmpv on Windows: offer one-click download of the pinned LGPL libmpv build
(URL + SHA256 hardcoded per release) into the app data dir; loaded from there. Makes pip on
Windows effectively zero-step. Optional `kinochronix[media]` binary companion wheel is post-1.0.

## 2026-07 · D-015 · LGPL-configured libmpv ONLY in bundles
libmpv is dual GPL/LGPL; bundling a GPL-configured build would poison D-003. Packaging must use
LGPL builds (-Dgpl=false; e.g. shinchiro LGPL Windows builds) and CI release asserts the build
flavor before bundling. Same for ffmpeg (LGPL configuration, no --enable-gpl).

## 2026-07 · D-016 · Code signing: stubbed at v1.0, hooks ready
v1.0 ships unsigned (SmartScreen "Run anyway" / macOS right-click-Open documented in README +
docs). Release workflow contains signing/notarization steps behind secrets-present conditionals
so enabling later = adding secrets, zero code change. Buy Apple $99/yr + Windows signing at
first commercial interest or when Mac-user friction reports appear.

## 2026-07 · D-017 · python-mpv naming
Dependency is `python-mpv` on PyPI; imported module is `mpv`. The unrelated PyPI package named
`mpv` must never be installed. Pin in pyproject: python-mpv>=1.0.7.

## 2026-07 · D-018 · Product name = KinoChronix (final)
Brand/display: `KinoChronix`. Package/module/CLI/entry-point group/paths: `kinochronix`
(lowercase, single word). Session ext `.kcx`; cache sidecar `<file>.kcache/`; installers
`KinoChronix-Setup.exe` / `KinoChronix.dmg` / `KinoChronix.AppImage`; env vars `KINOCHRONIX_*`;
third-party plugins `kinochronix-plugin-<name>`. Casing table is binding (AGENTS.md §Naming).
Agents must not introduce spelling variants or rename anything. ACTION FOR OWNER: register
`kinochronix` on PyPI (stub 0.0.1) and the GitHub org/repo before Phase 0 work begins.
