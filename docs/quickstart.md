# Quickstart

AvialSync helps you look at an experiment in time. It does not change your original files.

## Before you start

Have one or more video files, plus any sensor, tracking, or recording files you want to inspect.
Standard videos that your local mpv/ffmpeg installation can open are supported. Your lab may also
provide a plugin for its own recording format.

## If you installed with pip

`pip install avialsync` supplies every Python dependency, but not the two native components the
program needs for video: **libmpv** and **FFmpeg**. AvialSync opens either way — without libmpv the
video panes stay disabled and a `Missing libmpv` dialog names the step for your platform, while
every time-series feature keeps working. See
[what pip cannot install](install.md#what-pip-cannot-install) for the one-line fix on each platform,
and **Help → Diagnostics** for what was found on this machine.

Running from a Git checkout instead of an installer or PyPI? See
[development setup](technical/development.md).

## Try it without your own data

```bash
avialsync demo
```

This creates and opens a complete synchronized example: three 30 fps CFR cameras, one VFR camera,
sensor and dense ephys/TTL traces, and frame-indexed tracking. It works from the installer, a pip
installation with its native prerequisites, or a source checkout. The first run shows generation
progress; later runs validate and reuse the application-data cache.

## Open files

Start AvialSync. Drag files onto the main window, or use the buttons in the left panel.

- Use **Open Videos** for camera recordings.
- Use **Open Sensor/Ephys Data** for tables, recordings, tracking files, or lab formats.

The program examines each file and chooses the appropriate built-in or lab plugin. Large recordings
are prepared in the background, so you can keep using the window while they load.

## Inspect one moment

The lower time bar is the shared experiment time.

1. Drag it to a moment of interest.
2. The video panes show the corresponding camera frames.
3. The trace plots show the corresponding samples and values.
4. **Data Streams** shows which files actually have data at that time.

When a camera does not cover the selected moment, its pane says **No Footage** rather than showing an
old frame.

## Align recordings

Begin with the visible event that is easiest to recognize. You can adjust a camera offset in the
left panel. For recordings with TTL pulses or frame triggers, use the synchronization wizard to
preview a proposed alignment before accepting it. Acceptance is always explicit, and your original
timestamps remain unchanged.

Continue with the [first-session tutorial](tutorials/first-session.md) for a complete example.
