# Quickstart

AvialSync helps you look at an experiment in time. It does not change your original files.

## Before you start

Have one or more video files, plus any sensor, tracking, or recording files you want to inspect.
Standard videos that your local mpv/ffmpeg installation can open are supported. Your lab may also
provide a plugin for its own recording format.

## If you installed with pip

`pip install avialsync` supplies every Python dependency, but not the two native components the
program needs for video: **libmpv** and **FFmpeg** (`ffmpeg` and `ffprobe`). Those are shared
libraries and programs rather than Python packages, so `pip` cannot deliver them. The desktop
installers bundle both; a pip install needs them installed once:

- macOS: `brew install ffmpeg mpv`
- Debian/Ubuntu: `sudo apt install ffmpeg libmpv2`
- Fedora: `sudo dnf install ffmpeg mpv-libs`
- Arch: `sudo pacman -S ffmpeg mpv`

On Windows, install FFmpeg with `winget install --id Gyan.FFmpeg.Shared -e`. No Windows package
manager ships `libmpv-2.dll`, so download an `mpv-dev-x86_64-*` archive from the
[mpv-player-windows libmpv files](https://sourceforge.net/projects/mpv-player-windows/files/libmpv/),
extract it, and set `AVIALSYNC_MEDIA_ROOT` to the folder that directly contains the DLL. AvialSync
searches that folder before the conda environment and `PATH`, and it may hold `ffmpeg.exe` and
`ffprobe.exe` too.

AvialSync opens either way. Without libmpv the video panes stay disabled and a `Missing libmpv`
dialog names the step for your platform; **Help → Diagnostics** reports what was found.

## Windows: running from a source checkout

This section is for developers running the repository, not for people who used
`AvialSync-Setup.exe` or `pip install avialsync`.
Install Python 3.11 or 3.12, a standalone shared FFmpeg build, and a compatible libmpv build. Put
`libmpv-2.dll` in the active conda environment's `Library\\bin` directory,
or otherwise make it available on `PATH`.

```powershell
conda create -n avialsync python=3.12 -y
conda run -n avialsync python -m pip install -e ".[dev]"
conda run -n avialsync avialsync
```

`winget install --id Gyan.FFmpeg.Shared -e` is a suitable FFmpeg installation route. AvialSync finds
that standard WinGet location even when activation changes `PATH`. Do not use the
conda FFmpeg package for this checkout because it can conflict with Qt DLLs. Windows uses libmpv's
Qt OpenGL video renderer, so keep your GPU driver current.

The Python `.[dev]` install supplies every Python dependency. FFmpeg and libmpv are native programs,
not Python packages, so a source checkout needs the separate setup above. The desktop installer bundles
and validates those runtime files; a normal user only installs `AvialSync-Setup.exe`.

Run `avialsync demo` to create and open the complete synchronized example: three 30 fps CFR cameras,
one VFR camera, sensor and dense ephys/TTL traces, and frame-indexed tracking. It works from the
installer, a pip installation with its native prerequisites, or an editable source checkout. A first
run displays generation progress; subsequent runs validate and reuse the application-data cache.

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
