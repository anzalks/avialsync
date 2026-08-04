# Troubleshooting

## A startup error naming numpy or quantities

A traceback ending in `AttributeError: type object 'numpy.ndarray' has no attribute 'ptp'`, raised
somewhere under `import neo`, means an outdated `quantities` is being imported alongside NumPy 2.
`quantities` before 0.16.3 reads a method NumPy 2 removed. AvialSync now requires a version that
does not, so a fresh install into a clean environment cannot hit this.

It survives on Windows for one reason: a conda environment still reads your **per-user**
site-packages, `%APPDATA%\Python\Python312\site-packages`, ahead of its own. An old copy left there
by an earlier `pip install --user` shadows whatever the environment resolved, and `pip` never
revisits it because it is not what pip was asked to install. Read the paths in your traceback — if
`neo` and `quantities` load from `AppData\Roaming\Python` while AvialSync loads from `.conda\envs`,
this is what happened.

```powershell
conda activate avialsync
setx PYTHONNOUSERSITE 1
python -m pip install --upgrade "quantities>=0.16.3" neo
```

Open a new terminal so `PYTHONNOUSERSITE` takes effect. Deleting `%APPDATA%\Python\Python312`
removes the shadowing copy for every environment on the machine. The command that verifies the
result is under [Windows installation](install.md#windows).

A broken loader no longer stops AvialSync from starting: the format it handles disappears and
**Help → Diagnostics** names the failure under *Plugins that failed to load*. An older release
crashed outright instead.

## A “Missing libmpv” dialog appears at startup

This is expected after `pip install avialsync` on a machine that has no libmpv. libmpv is a shared
library rather than a Python package: the `python-mpv` dependency is only a binding and loads a
libmpv that already exists on the system. The desktop installers bundle one, so the dialog appears
only for pip and source installs.

AvialSync deliberately keeps running. Time series, tracking, annotations, and sessions all work;
the video panes stay disabled until libmpv is present. Install it as described in
[Installation](install.md#what-pip-cannot-install) — `brew install mpv`,
`sudo apt install libmpv2`, `sudo dnf install mpv-libs`, or `sudo pacman -S mpv` — and restart.

On Windows, download an `mpv-dev-x86_64-*` archive from the
[mpv-player-windows libmpv files](https://sourceforge.net/projects/mpv-player-windows/files/libmpv/)
and set `AVIALSYNC_MEDIA_ROOT` to the folder that *directly* contains `libmpv-2.dll`; a parent
folder is not searched. Set it with `setx`, then open a new terminal so the variable is present.
The same missing-runtime rule applies to `ffmpeg` and `ffprobe`, which imports and exports need.

**Help → Diagnostics** confirms what was found after a restart.

## A video says “No Footage”

This is usually correct: the selected master time is outside that camera’s recording. Check its span
in **Data Streams** and its offset in the left panel. It is safer than displaying the last frame from
another time.

## Video viewer remains grey on Windows

AvialSync uses libmpv's Qt OpenGL render path on Windows and macOS, and native `wid` embedding on Linux.
If the viewer is grey, open **Help → Diagnostics** and confirm libmpv is available; then update your GPU driver
and restart. The demo's test-pattern videos should be visible before you add your own files. In a headless
environment, video output is intentionally disabled (`vo=null`), so use the time-series and metadata checks only.

## Videos and traces do not line up

First check that the relevant files overlap in **Data Streams**. Then adjust a visible event manually
or use TTL/event synchronization. Accept a proposed synchronization only after reviewing its match
quality.

## A file does not open

Check its **Properties** or import report for the detected format and error. For a lab-specific file,
install the matching plugin. For a video, make sure the installed AvialSync release or local media
software can open the codec.

## The plots look slow or too dense

AvialSync draws a compact representation of dense signals while you navigate. Zoom into the part
you need; it will show the available detail without trying to draw every sample at once.
