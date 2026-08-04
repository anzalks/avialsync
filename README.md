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

It is designed for visual inspection and careful alignment. It does not acquire recordings and it
does not perform scientific analysis for you. Your lab can add support for its own file types and
workflows through plugins.

![Three synchronised camera views of a head-fixed mouse with 2D pose overlays, a 3D pose view, and
the wheel encoder velocity trace, all on one master timeline.](https://raw.githubusercontent.com/anzalks/avialsync/main/docs/_static/screenshots/aol_session_overview.png)

*A real recording session: three cameras at 230 fps with per-camera 2D pose drawn over each view,
triangulated 3D pose on the right, and wheel-encoder velocity below — every source on one master
clock, at one instant. The whole folder was opened by dropping it on the window: a
[session plugin](https://github.com/anzalks/avialsync/blob/main/docs/plugin-guide.md#session-plugins) recognised the layout and placed each file,
including the shared time base. Nothing in AvialSync knows this lab's format.*

## Why use it?

- View several camera recordings together.
- Inspect sensor and tracking traces alongside the video.
- Move through an experiment with one shared time control.
- Align recordings with offsets, drift, or TTL/event evidence, while keeping the original files
  unchanged.
- Mark events, compare time ranges, and export snapshots or selected data for analysis elsewhere.

## Install and open your first experiment

The simplest route is the desktop artifact from the [GitHub Releases page](https://github.com/anzalks/avialsync/releases):
use `AvialSync-Setup.exe` on Windows, open `AvialSync.dmg` on macOS and drag **AvialSync** to
Applications, or mark `AvialSync.AppImage` executable and open it on Linux. The AppImage is
portable: no system-wide installation is required. Then open **AvialSync** like any other desktop
application.

These artifacts are not yet code-signed or notarized, so the operating system warns about an
unidentified developer on first launch. On macOS, right-click **AvialSync** and choose **Open**
once (or run `xattr -dr com.apple.quarantine /Applications/AvialSync.app`); on Windows, choose
**More info → Run anyway** in the SmartScreen prompt.

Two installers have a deliberate support boundary; use the PyPI install below if you fall outside
one:

| Installer | Requires | Otherwise |
|---|---|---|
| `AvialSync.dmg` | Apple silicon | Intel Macs: `pip install avialsync` |
| `AvialSync.AppImage` | glibc 2.39 or newer (Ubuntu 24.04+, Fedora 40+) | Debian 12, Ubuntu 22.04: `pip install avialsync` |

The AppImage also needs FUSE 2 to mount itself; without it, run
`./AvialSync.AppImage --appimage-extract-and-run`.

If you use Python, install it from PyPI with Python 3.11 or 3.12:

```bash
python -m pip install avialsync
avialsync
```

### Native prerequisites for a pip install

The installers above bundle everything. A pip install does not: two runtime components are native
libraries rather than Python packages, so `pip` cannot supply them. **libmpv** plays video, and
**FFmpeg** (`ffmpeg` and `ffprobe`) probes files and writes exports. The `python-mpv` dependency is
only a binding — it loads a libmpv that already exists on the machine and ships no copy of its own.
Without them AvialSync still opens and its time-series features work; video stays disabled and a
`Missing libmpv` dialog names the step for your platform.

| Platform | Command |
|---|---|
| macOS | `brew install ffmpeg mpv` |
| Debian / Ubuntu | `sudo apt install ffmpeg libmpv2` (`libmpv1` on releases before that package) |
| Fedora | `sudo dnf install ffmpeg mpv-libs` |
| Arch | `sudo pacman -S ffmpeg mpv` |

No Windows package manager ships `libmpv-2.dll`, so fetch it directly: download an
`mpv-dev-x86_64-*` archive from the [mpv-player-windows libmpv
files](https://sourceforge.net/projects/mpv-player-windows/files/libmpv/), extract it, and point
AvialSync at the folder that holds the DLL.

```powershell
winget install --id Gyan.FFmpeg.Shared -e
setx AVIALSYNC_MEDIA_ROOT "C:\path\to\mpv-dev"
```

`AVIALSYNC_MEDIA_ROOT` must name the directory that directly contains `libmpv-2.dll`; AvialSync
searches it before the conda environment and `PATH`, and it may hold `ffmpeg.exe` and `ffprobe.exe`
alongside the DLL. Open a new terminal after `setx` so the variable is set, then run `avialsync`.

Open **Help → Diagnostics** at any time to see whether libmpv and hardware decoding were found.

### Windows source checkout prerequisites

The release installer bundles its media runtime. If you run AvialSync from a Git checkout instead,
install Python 3.11 or 3.12, FFmpeg (for `ffprobe.exe`), and libmpv before starting the application.
Create the project environment and install its dependencies with:

```powershell
conda create -n avialsync python=3.12 -y
conda run -n avialsync python -m pip install -e ".[dev]"
```

Install a standalone shared FFmpeg build (for example, `winget install --id Gyan.FFmpeg.Shared -e`).
AvialSync discovers the standard WinGet FFmpeg location even if `conda activate` changes `PATH`.
Install a compatible Windows libmpv
build and put its `libmpv-2.dll` in the conda environment's `Library\bin` directory, or otherwise
ensure that DLL is on `PATH`. Do not use conda's FFmpeg package for this checkout: it can conflict
with the Qt DLLs. A current GPU driver is also required for the Windows OpenGL video renderer. These
two native components cannot be supplied by the Python `.[dev]` install; the desktop installer bundles
and validates them, so end users do not perform these steps.

Run the application or its demo with:

```powershell
conda run -n avialsync avialsync
conda run -n avialsync python tools/launch_demo.py
conda run -n avialsync avialsync demo
```

After `conda activate avialsync`, the equivalent commands are `avialsync` and
`python C:\path\to\avialsync\tools\launch_demo.py`. The `python` prefix is required for the demo
script; running a `.py` file directly can use Windows' unrelated file association. The launcher
delegates to `avialsync demo`, so both launch paths have identical behavior.
The demo creates three 30 fps CFR cameras, one VFR camera, a four-channel sensor trace, a dense
ephys/TTL trace with gaps, and DLC-style tracking in your platform application-data folder. Camera 2
has a known +1.234 s mapping and camera 3 a known 1000 ppm drift mapping. First-run generation is
shown in the progress-and-log dialog; later runs validate and reuse the cached files.

When the window opens:

1. Drag video and recording files into the window, or use **Open Videos** and **Open Sensor/Ephys Data**.
2. Video appears at the top; traces appear below it.
3. Drag the shared time bar to inspect a moment across every available recording.
4. If recordings do not line up, use the synchronization tools to align a visible event or TTL pulse.

If a camera has no recording at the selected time, it clearly shows **No Footage**. The **Data Streams**
section shows when each file is available on the shared timeline.

## Documentation

![One camera and three signal channels of the bundled sample session on a shared timeline, with the
Data Streams coverage bar below.](https://raw.githubusercontent.com/anzalks/avialsync/main/docs/_static/screenshots/demo_step3_csv_loaded.png)

*The bundled sample session, which needs no data of your own. Unlike the recording at the top of
this page, this one reproduces from a clean clone:
`conda run -n avialsync python tools/generate_demo_screenshots.py`.*

Start with the [Quickstart](https://github.com/anzalks/avialsync/blob/main/docs/quickstart.md), then use the [first-session tutorial](https://github.com/anzalks/avialsync/blob/main/docs/tutorials/first-session.md).
The documentation also includes [supported formats](https://github.com/anzalks/avialsync/blob/main/docs/formats.md), [troubleshooting](https://github.com/anzalks/avialsync/blob/main/docs/troubleshooting.md),
[synchronization guidance](https://github.com/anzalks/avialsync/blob/main/docs/tutorials/synchronization.md), and a separate
[technical reference](https://github.com/anzalks/avialsync/blob/main/docs/technical/index.md) for people maintaining the software or writing plugins.

## How it compares

Neighbouring open-source tools, described as their authors position them. Pick
the one that matches your problem — they overlap less than the names suggest.

| | **AvialSync** | PlotJuggler | Rerun | Foxglove |
|---|---|---|---|---|
| Primary use | Scrub multi-camera video against dense signals | Plot and analyse time series | Log and replay multimodal robot data | Inspect and visualise robotics data |
| Video playback | libmpv, frame-exact when paused | Not a focus | Yes, alongside other modalities | Yes |
| Dense signals | 50 kHz × many channels via a decimation pyramid | Strong, its core purpose | Yes | Yes |
| Per-source offset/drift | Yes, with evidence-based TTL alignment | Manual offsets | Timeline-based | Timeline-based |
| Data model | Reads your files in place | Reads your files in place | You log into its own format | ROS/MCAP-oriented |
| Licence | AGPL-3.0 | MPL-2.0 | Apache-2.0 | Source-available + hosted |

If you mainly plot signals, PlotJuggler is likely a better fit. If you are in a
ROS ecosystem, Foxglove and Rerun are built for it. AvialSync exists for the
narrower case where **the video and the signal have to agree on the same
instant**, and the recordings came off independently-clocked hardware.

## What AvialSync does not do

AvialSync is not an acquisition system, a replacement for your analysis pipeline, or a tool that
silently changes scientific timestamps. It helps you inspect and align recordings; analysis remains
in your existing tools or in lab-provided plugins.

## For developers

The documentation site is built with Read the Docs from `.readthedocs.yaml`. Local preview:

```bash
python -m pip install -e ".[docs]"
sphinx-build -W --keep-going -b html docs docs/_build/html
```

### Publishing the documentation site

The repository is already configured — `.readthedocs.yaml` pins Ubuntu 22.04, Python 3.11, and
installs the `docs` extra, with `fail_on_warning: true` so a warning fails the build exactly as CI
does. What remains is connecting the project once:

1. Sign in at [readthedocs.org](https://readthedocs.org/) with the GitHub account that owns the
   repository, and grant it access to `anzalks/avialsync`.
2. **Import a Project → Import Manually** (or pick the repository from the list). Set the name to
   `avialsync` so the site lands on `https://avialsync.readthedocs.io/`, which is the address the
   badge above and the links below already use. A different name means editing both.
3. Leave the default branch as `main`. Read the Docs finds `.readthedocs.yaml` itself; do not set a
   configuration path.
4. **Admin → Automation Rules** is worth one rule: activate and set as default any tag matching
   `.*`, so a released version's docs are published and `/en/stable/` tracks the newest release
   rather than the tip of `main`.
5. Trigger the first build from **Builds → Build version**. It takes about a minute.

The webhook is installed by the GitHub connection, so later pushes and tags build automatically.
Until step 2 is done the documentation badge stays grey and
`https://avialsync.readthedocs.io/` returns 404 — everything else in this README works regardless,
and the same pages render locally with the command above.

## Development

```bash
conda run -n avialsync pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest -x -q
```

GitHub Actions is the sole publisher for release artifacts and PyPI distributions. Do not upload
packages from a developer workstation. A release tag runs cross-platform validation, builds the
wheel and source distribution, and smoke-tests the wheel in a clean environment before building
the platform installers. PyPI publishing starts only after every installer succeeds, and GitHub
creates the release last.

The release workflow itself pins and verifies the AppImage build tool before creating the Linux
AppImage; no package-upload token or repository variable is needed.

Two things must exist before a tag can complete, and neither lives in this repository. Both fail
late — after every installer has already been built — so confirm them before tagging:

1. **PyPI trusted publishing** for the `avialsync` project, naming this repository, the `Release`
   workflow, and the `pypi` environment. If the `pypi` GitHub environment has required reviewers,
   the release waits for an approval rather than failing.
2. **A tag reachable from `main`.** The workflow refuses to publish a side branch, and it also
   requires the tag, `pyproject.toml`, and `src/avialsync/__init__.py` to name one identical
   version — which is what `tools/prepare_release.py` guarantees.

Release artifacts are not yet code-signed or notarized. `packaging/windows/sign.ps1` and
`packaging/macos/sign_notarize.sh` are placeholders, and nothing in CI invokes them; signing needs
an Apple Developer account and a Windows code-signing certificate. Until then, every download
carries the first-launch warnings described under [Install](#install-and-open-your-first-experiment).

To prepare a future tag release from a clean `main` checkout, use the guarded helper rather than
editing versions or creating tags by hand:

```bash
conda run -n avialsync python tools/prepare_release.py 0.1.0b1 --dry-run
conda run -n avialsync python tools/prepare_release.py 0.1.0b1
```

It validates the version, updates both package-version authorities, builds and checks wheel/sdist,
commits the change, creates annotated `v0.1.0b1`, and pushes it. GitHub Actions remains the sole
publisher. The helper permits only the offline `graphify-out/graph.json` as a pre-existing dirty
file; commit or resolve every other change first.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](https://github.com/anzalks/avialsync/blob/main/CONTRIBUTING.md) for setup,
the four-command gate every change must pass, and the architecture rules that
exist because breaking them caused real bugs. Participation is governed by our
[Code of Conduct](https://github.com/anzalks/avialsync/blob/main/CODE_OF_CONDUCT.md).

Good places to start are format plugins (the `TimeSeriesSource` /`VideoSource`
contracts are frozen — see [the plugin guide](https://github.com/anzalks/avialsync/blob/main/docs/plugin-guide.md)), platform
verification on real hardware, and the open items under "Pending" in `HANDOUT.md`.

Contributions are accepted under the terms in
[CLA.md](https://github.com/anzalks/avialsync/blob/main/CLA.md): you keep the copyright in your
work and grant the right to ship it under both licences below. One line in your first pull request
covers it.

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

Contributions are accepted under [CLA.md](https://github.com/anzalks/avialsync/blob/main/CLA.md).
