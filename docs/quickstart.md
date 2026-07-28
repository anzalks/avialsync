# Quickstart

AvialView helps you look at an experiment in time. It does not change your original files.

## Before you start

Have one or more video files, plus any sensor, tracking, or recording files you want to inspect.
Standard videos that your local mpv/ffmpeg installation can open are supported. Your lab may also
provide a plugin for its own recording format.

## Windows: running from a source checkout

This section is only for developers running the repository, not people using `AvialView-Setup.exe`.
Install Python 3.11 or 3.12, a standalone shared FFmpeg build (so `ffprobe.exe` is on `PATH`), and a
compatible libmpv build. Put `libmpv-2.dll` in the active conda environment's `Library\\bin` directory,
or otherwise make it available on `PATH`.

```powershell
conda create -n avialview python=3.12 -y
conda run -n avialview python -m pip install -e ".[dev]"
conda run -n avialview avialview
```

`winget install --id Gyan.FFmpeg.Shared -e` is a suitable FFmpeg installation route. Do not use the
conda FFmpeg package for this checkout because it can conflict with Qt DLLs. Windows uses libmpv's
Qt OpenGL video renderer, so keep your GPU driver current.

The Python `.[dev]` install supplies every Python dependency. FFmpeg and libmpv are native programs,
not Python packages, so a source checkout needs the separate setup above. The desktop installer bundles
and validates those runtime files; a normal user only installs `AvialView-Setup.exe`.

Run `avialview demo` to create and open a small generated video and sensor-data session. It stores
the generated inputs in the platform application-data directory and works from the installer, a pip
installation with its native prerequisites, or an editable source checkout. A first run displays a
progress-and-log dialog while the video is generated; subsequent runs reuse the files.

## Open files

Start AvialView. Drag files onto the main window, or use the buttons in the left panel.

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
