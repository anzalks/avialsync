# Quickstart

AvialSync helps you look at an experiment in time. It does not change your original files.

## Before you start

Have one or more video files, plus any sensor, tracking, or recording files you want to inspect.
AvialSync decodes video itself, so nothing needs to be installed alongside it and it opens whatever
its bundled FFmpeg supports — see [Formats](formats.md). Your lab may also provide a plugin for its
own recording format.

## After installing

`pip install avialsync` is the whole install: video decoding, proxy generation, and clip export all
run inside the Python packages, so there is no separate media runtime to add. On Linux, Qt still
needs the usual desktop graphics libraries — see [that note](install.md#one-note-about-linux).
**Help → Diagnostics** shows what this machine reported.

Running from a Git checkout instead of an installer or PyPI? See
[development setup](technical/development.md).

## Try it without your own data

```bash
avialsync demo
```

This creates and opens a complete synchronized example: three 30 fps CFR cameras, one VFR camera,
sensor and dense ephys/TTL traces, and frame-indexed tracking. It works from the installer, a pip
installation, or a source checkout, and needs nothing else installed. The first run shows generation
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

Begin with the visible event that is easiest to recognize, and adjust that camera's offset in the
left panel. For recordings with TTL pulses or frame triggers, **Align → Synchronize TTL / events…**
fits the mapping from that evidence and shows you the proposed match count, the residual error, and
a plot of the residuals themselves before you accept it. Acceptance is always explicit, and your
original timestamps are never changed.

[Tutorial: align recordings](tutorials/synchronization.md) covers every field in that wizard.

## Where to go next

| If you want to | Read |
|---|---|
| Work through a complete example | [Inspect a first session](tutorials/first-session.md) |
| Import a table correctly the first time | [Import sensor and recording data](tutorials/importing-data.md) |
| Align cameras to TTL or frame triggers | [Align recordings](tutorials/synchronization.md) |
| Mark frames and get data out | [Flag frames and export](tutorials/annotating-and-exporting.md) |
| Fix a pose estimate that landed in the wrong place | [Correcting a tracked point](user-guide/index.md#correcting-a-tracked-point) |
| Rebind a shortcut, save a layout, or change a setting | [Sessions, proxies, and the 3D view](user-guide/sessions-and-media.md) |
| Know every control in the window | [User Guide](user-guide/index.md) |
