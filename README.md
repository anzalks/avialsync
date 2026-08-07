# AvialSync

**The Advanced Video and Instrument Alignment Library.**

[![PyPI](https://img.shields.io/pypi/v/avialsync.svg)](https://pypi.org/project/avialsync/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://pypi.org/project/avialsync/)
[![CI](https://github.com/anzalks/avialsync/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/anzalks/avialsync/actions/workflows/ci.yml)
[![Documentation](https://readthedocs.org/projects/avialsync/badge/?version=latest)](https://avialsync.readthedocs.io/en/latest/)
[![Licence](https://img.shields.io/badge/licence-AGPL--3.0-blue.svg)](https://github.com/anzalks/avialsync/blob/main/LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://github.com/anzalks/avialsync/releases)

AvialSync is a desktop viewer for looking through an experiment in time.

Use it when you have video from one or more cameras together with recordings such as sensors,
electrodes, behavioural tracking, or other time-stamped measurements. It places them on one shared
timeline so you can move to an event and inspect what each recording shows at that moment.

It exists for the case where **the video and the signal have to agree on the same instant**, and the
recordings came off independently-clocked hardware. It is built for visual inspection and careful
alignment: it does not acquire recordings, it does not analyse them for you, and it never silently
changes a scientific timestamp. Your lab can add support for its own file types and workflows
through plugins.

![A one-second loop of three synchronised camera views of a head-fixed mouse with 2D pose overlays,
a 3D pose view, and the wheel encoder velocity trace advancing together on one master
timeline.](https://raw.githubusercontent.com/anzalks/avialsync/main/docs/_static/screenshots/aol_session_overview.gif)

*A real recording session: three cameras at 230 fps with per-camera 2D pose drawn over each view,
triangulated 3D pose on the right, and wheel-encoder velocity below — one second of it, at the speed
it was recorded, every source moving on one master clock. The whole folder was opened by dropping it
on the window; a [session plugin](https://avialsync.readthedocs.io/en/latest/plugin-guide.html)
recognised the layout and placed each file, including the shared time base. Nothing in AvialSync
knows this lab's format.*

## What it gives you

- Several camera recordings playing together on one clock.
- Sensor, electrode, and tracking traces beside the video, up to 50 kHz across many channels.
- Alignment by offset, drift, or TTL/event evidence, with the original files left unchanged.
- Event marks, A/B time ranges, and exports of snapshots or selected spans for analysis elsewhere.

## Install

**Desktop installer (recommended).** Download from the
[Releases page](https://github.com/anzalks/avialsync/releases): `AvialSync-Setup.exe` on Windows,
`AvialSync.dmg` on macOS, or `AvialSync.AppImage` on Linux. Everything needed is bundled. The
artifacts are not yet code-signed, so the first launch needs
[one extra click](https://avialsync.readthedocs.io/en/latest/install.html#first-launch-security-warnings).

**PyPI**, on Python 3.11 or 3.12:

```bash
python -m pip install avialsync
avialsync
```

That is the whole install. Video decoding ships inside the Python packages, so there is no library
to install separately and nothing to configure.

Two things worth knowing:

- **On Linux**, Qt itself needs the usual desktop graphics libraries (`libgl1`, `libxkbcommon`, and
  the xcb set). Every normal desktop already has them; bare containers and minimal server images do
  not. No packaging choice removes this — it is Qt's floor, not AvialSync's.
- **FFmpeg on your `PATH`** is still needed for three extras: proxy generation, clip export, and the
  `avialsync demo` sample generator. Playback, scrubbing, and alignment do not use it.

Apple silicon is required for the `.dmg`, and glibc 2.39+ for the AppImage; outside those, use pip.
See [Installation](https://avialsync.readthedocs.io/en/latest/install.html) for details.

## First session

```bash
avialsync demo
```

That generates and opens a complete sample session — four cameras, sensor and ephys traces, tracking
— so you can try everything before touching your own data. With your own recordings:

1. Drag video and data files onto the window, or use **Open Videos** and **Open Sensor/Ephys Data**.
2. Video appears at the top, traces below it.
3. Drag the shared time bar to inspect one moment across every recording.
4. If recordings do not line up, use the synchronization tools to align a visible event or TTL pulse.

A camera with no coverage at the selected time shows **No Footage** rather than a stale frame, and
**Data Streams** shows when each file has data.

## Documentation

Full documentation is at **[avialsync.readthedocs.io](https://avialsync.readthedocs.io/en/latest/)**
— [quickstart](https://avialsync.readthedocs.io/en/latest/quickstart.html),
[first-session tutorial](https://avialsync.readthedocs.io/en/latest/tutorials/first-session.html),
[supported formats](https://avialsync.readthedocs.io/en/latest/formats.html),
[synchronization](https://avialsync.readthedocs.io/en/latest/tutorials/synchronization.html),
[troubleshooting](https://avialsync.readthedocs.io/en/latest/troubleshooting.html),
[plugin guide](https://avialsync.readthedocs.io/en/latest/plugin-guide.html), and a
[technical reference](https://avialsync.readthedocs.io/en/latest/technical/index.html) covering
architecture, data handling, performance, and the development and release process.

## Contributing

Contributions are welcome — see
[CONTRIBUTING.md](https://github.com/anzalks/avialsync/blob/main/CONTRIBUTING.md) for setup, the
four-command gate every change must pass, and the architecture rules that exist because breaking
them caused real bugs. Participation is governed by our
[Code of Conduct](https://github.com/anzalks/avialsync/blob/main/CODE_OF_CONDUCT.md).

Good places to start are format plugins (the `TimeSeriesSource` / `VideoSource` contracts are frozen
— see the [plugin guide](https://avialsync.readthedocs.io/en/latest/plugin-guide.html)), platform
verification on real hardware, and the open items under "Pending" in `HANDOUT.md`.

Contributions are accepted under [CLA.md](https://github.com/anzalks/avialsync/blob/main/CLA.md):
you keep the copyright in your work and grant the right to ship it under both licences below. One
line in your first pull request covers it.

## Licence

AvialSync is free software under the
[GNU AGPL v3 or later](https://github.com/anzalks/avialsync/blob/main/LICENSE). Use it, study it,
modify it, redistribute it. The one condition is reciprocity: if you convey a modified version —
including letting others use it over a network — you publish your changes under the same licence.

Running it in your lab, modifying it for your own use, publishing results, and writing plugins for
your own rig all sit inside this and cost nothing. A plugin that uses only the documented
`TimeSeriesSource`, `VideoSource` and `SessionSource` interfaces is your own work and you choose its
licence, so a loader for a proprietary instrument format need not be published.

Other arrangements are possible in situations the AGPL cannot accommodate; see
[licensing](https://avialsync.readthedocs.io/en/latest/licensing.html) in the documentation.
