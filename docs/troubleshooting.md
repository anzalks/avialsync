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

## Video does not play after `pip install`

This should no longer happen. Video decoding ships inside the Python packages, so `pip install
avialsync` brings its own decoder and there is nothing further to install — the `Missing libmpv`
dialog that earlier versions showed is gone along with the library it asked for.

If video still does not appear, open **Help → Diagnostics**: it names the decoder in use. A failure
there means the install itself is broken rather than incomplete, so reinstall with
`python -m pip install --force-reinstall avialsync`.

`ffmpeg` and `ffprobe` are a separate matter and are still external programs. They are not used for
playback, only for proxy generation, clip export, and the `avialsync demo` sample generator. If one
of those reports a missing runtime, install FFmpeg (`brew install ffmpeg`, `sudo apt install
ffmpeg`, `sudo dnf install ffmpeg`, or `sudo pacman -S ffmpeg`) and make sure it is on your `PATH`.

## A video says “No Footage”

This is usually correct: the selected master time is outside that camera’s recording. Check its span
in **Data Streams** and its offset in the left panel. It is safer than displaying the last frame from
another time.

## The video pane stays blank

The pane draws decoded frames directly, and it does the same thing on Windows, macOS, and Linux —
there is no per-platform render path left to go wrong, and no GPU driver involved in getting a frame
on screen.

A blank pane with a name in the corner usually means the file failed to open; the pane says so in
place of the picture. Check that the file plays elsewhere and that its codec is one FFmpeg supports.
The demo's test-pattern videos (`avialsync demo`) should be visible before you add your own files.

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
