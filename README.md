# AvialView

**The Advanced Video and Instrument Alignment Library.**

AvialView is a desktop viewer for looking through an experiment in time.

Use it when you have video from one or more cameras together with recordings such as sensors,
electrodes, behavioural tracking, or other time-stamped measurements. It places them on one shared
timeline so you can move to an event and inspect what each recording shows at that moment.

It is designed for visual inspection and careful alignment. It does not acquire recordings and it
does not perform scientific analysis for you. Your lab can add support for its own file types and
workflows through plugins.

## Why use it?

- View several camera recordings together.
- Inspect sensor and tracking traces alongside the video.
- Move through an experiment with one shared time control.
- Align recordings with offsets, drift, or TTL/event evidence, while keeping the original files
  unchanged.
- Mark events, compare time ranges, and export snapshots or selected data for analysis elsewhere.

## Install and open your first experiment

The simplest route is the desktop artifact from the [GitHub Releases page](https://github.com/anzalks/avialview/releases):
use `AvialView-Setup.exe` on Windows, open `AvialView.dmg` on macOS, or mark
`AvialView.AppImage` executable and open it on Linux. The AppImage is portable: no system-wide
installation is required. Then open **AvialView** like any other desktop application.

If you use Python, install it from PyPI with Python 3.11 or 3.12:

```bash
python -m pip install avialview
avialview
```

### Windows source checkout prerequisites

The release installer bundles its media runtime. If you run AvialView from a Git checkout instead,
install Python 3.11 or 3.12, FFmpeg (for `ffprobe.exe`), and libmpv before starting the application.
Create the project environment and install its dependencies with:

```powershell
conda create -n avialview python=3.12 -y
conda run -n avialview python -m pip install -e ".[dev]"
```

Install a standalone shared FFmpeg build (for example, `winget install --id Gyan.FFmpeg.Shared -e`).
AvialView discovers the standard WinGet FFmpeg location even if `conda activate` changes `PATH`.
Install a compatible Windows libmpv
build and put its `libmpv-2.dll` in the conda environment's `Library\bin` directory, or otherwise
ensure that DLL is on `PATH`. Do not use conda's FFmpeg package for this checkout: it can conflict
with the Qt DLLs. A current GPU driver is also required for the Windows OpenGL video renderer. These
two native components cannot be supplied by the Python `.[dev]` install; the desktop installer bundles
and validates them, so end users do not perform these steps.

Run the application or its demo with:

```powershell
conda run -n avialview avialview
conda run -n avialview python tools/launch_demo.py
conda run -n avialview avialview demo
```

After `conda activate avialview`, the equivalent commands are `avialview` and
`python C:\path\to\avialview\tools\launch_demo.py`. The `python` prefix is required for the demo
script; running a `.py` file directly can use Windows' unrelated file association. The launcher
delegates to `avialview demo`, so both launch paths have identical behavior.
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

Start with the [Quickstart](docs/quickstart.md), then use the [first-session tutorial](docs/tutorials/first-session.md).
The documentation also includes [supported formats](docs/formats.md), [troubleshooting](docs/troubleshooting.md),
[synchronization guidance](docs/tutorials/synchronization.md), and a separate
[technical reference](docs/technical/index.md) for people maintaining the software or writing plugins.

## How it compares

Neighbouring open-source tools, described as their authors position them. Pick
the one that matches your problem — they overlap less than the names suggest.

| | **AvialView** | PlotJuggler | Rerun | Foxglove |
|---|---|---|---|---|
| Primary use | Scrub multi-camera video against dense signals | Plot and analyse time series | Log and replay multimodal robot data | Inspect and visualise robotics data |
| Video playback | libmpv, frame-exact when paused | Not a focus | Yes, alongside other modalities | Yes |
| Dense signals | 50 kHz × many channels via a decimation pyramid | Strong, its core purpose | Yes | Yes |
| Per-source offset/drift | Yes, with evidence-based TTL alignment | Manual offsets | Timeline-based | Timeline-based |
| Data model | Reads your files in place | Reads your files in place | You log into its own format | ROS/MCAP-oriented |
| Licence | Apache-2.0 | MPL-2.0 | Apache-2.0 | Source-available + hosted |

If you mainly plot signals, PlotJuggler is likely a better fit. If you are in a
ROS ecosystem, Foxglove and Rerun are built for it. AvialView exists for the
narrower case where **the video and the signal have to agree on the same
instant**, and the recordings came off independently-clocked hardware.

## What AvialView does not do

AvialView is not an acquisition system, a replacement for your analysis pipeline, or a tool that
silently changes scientific timestamps. It helps you inspect and align recordings; analysis remains
in your existing tools or in lab-provided plugins.

## For developers

The documentation site is built with Read the Docs. Local preview:

```bash
python -m pip install -e ".[docs]"
sphinx-build -W --keep-going -b html docs docs/_build/html
```

## Development

```bash
conda run -n avialview pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest -x -q
```

GitHub Actions is the sole publisher for release artifacts and PyPI distributions. Do not upload
packages from a developer workstation. A release tag runs cross-platform validation, builds the
wheel and source distribution, and smoke-tests the wheel in a clean environment before building
the platform installers. PyPI publishing starts only after every installer succeeds, and GitHub
creates the release last.

Release administrators configure PyPI trusted publishing. The release workflow itself pins and
verifies the AppImage build tool before creating the Linux AppImage; no package-upload token or
repository variable is needed.

To prepare a future tag release from a clean `main` checkout, use the guarded helper rather than
editing versions or creating tags by hand:

```bash
conda run -n avialview python tools/prepare_release.py 0.1.0b1 --dry-run
conda run -n avialview python tools/prepare_release.py 0.1.0b1
```

It validates the version, updates both package-version authorities, builds and checks wheel/sdist,
commits the change, creates annotated `v0.1.0b1`, and pushes it. GitHub Actions remains the sole
publisher. The helper permits only the offline `graphify-out/graph.json` as a pre-existing dirty
file; commit or resolve every other change first.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup,
the four-command gate every change must pass, and the architecture rules that
exist because breaking them caused real bugs. Participation is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md).

Good places to start are format plugins (the `TimeSeriesSource` /`VideoSource`
contracts are frozen — see [the plugin guide](docs/plugin-guide.md)), platform
verification on real hardware, and the open items in `RECOVERY_PLAN.md`.
