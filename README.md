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

The simplest route is the desktop installer from the [GitHub Releases page](https://github.com/anzalks/avialview/releases).
Install it,
then open **AvialView** like any other desktop application.

If you use Python, install it from PyPI with Python 3.11 or 3.12:

```bash
python -m pip install avialview
avialview
```

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
