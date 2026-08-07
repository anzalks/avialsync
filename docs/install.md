# Installation

AvialSync installs in one of two ways, and both are self-contained. The desktop installer is a
single download. A `pip` install is smaller and scriptable, and it now brings its own video
decoder and FFmpeg, so there is nothing to install afterwards — on any platform. Linux users
should read [one note about Linux](#one-note-about-linux).

## Desktop installers (recommended)

Download the artifact for your platform from the
[GitHub Releases page](https://github.com/anzalks/avialsync/releases):

| Platform | File | Install |
|---|---|---|
| Windows | `AvialSync-Setup.exe` | Run the installer |
| macOS | `AvialSync.dmg` | Open it and drag **AvialSync** to Applications |
| Linux | `AvialSync.AppImage` | `chmod +x AvialSync.AppImage`, then run it |

Each bundles its video decoder and FFmpeg, so nothing else is required. The AppImage is portable and needs no
system-wide installation. Then open **AvialSync** like any other desktop application.

### None of them need administrator rights

On a managed lab or institute machine you often cannot supply an administrator password. No
installer requires one:

- **Windows:** `AvialSync-Setup.exe` asks whether to install for you only or for all users, and
  defaults to *for you only*. That choice installs under
  `%LOCALAPPDATA%\Programs\AvialSync` with a Start Menu entry for your account and never prompts
  for elevation. Choose *for all users* only if you have the password and want it shared.
- **macOS:** dragging **AvialSync** to `~/Applications` instead of `/Applications` works the same
  way.
- **Linux:** the AppImage is already a plain file you run from anywhere you can write.

The `pip` install below is also entirely per-user.

### First-launch security warnings

The artifacts are not yet code-signed or notarized, so the operating system reports an unidentified
developer the first time you open one.

- **macOS:** right-click **AvialSync** and choose **Open** once, or run
  `xattr -dr com.apple.quarantine /Applications/AvialSync.app`.
- **Windows:** choose **More info → Run anyway** in the SmartScreen prompt.

### Support boundaries

Two installers have a deliberate boundary. Use the pip install below if you fall outside one:

| Installer | Requires | Otherwise |
|---|---|---|
| `AvialSync.dmg` | Apple silicon | Intel Macs: `pip install avialsync` |
| `AvialSync.AppImage` | glibc 2.39 or newer (Ubuntu 24.04+, Fedora 40+) | Debian 12, Ubuntu 22.04: `pip install avialsync` |

The AppImage also needs FUSE 2 to mount itself. Without it, run
`./AvialSync.AppImage --appimage-extract-and-run`.

## Install from PyPI

AvialSync supports Python 3.11 and 3.12. Install it into an environment of its own — a conda env or
a virtualenv — rather than into a shared system Python:

```bash
conda create -n avialsync python=3.12 -y
conda activate avialsync
python -m pip install avialsync
avialsync
```

Use `python -m pip`, not a bare `pip`. A bare `pip` can be a different environment's copy that is
still first on `PATH`, which installs the package somewhere the `python` you are about to run will
not look.

That is the whole installation. Video decoding and FFmpeg arrive inside the Python packages `pip`
installs, so there is no second step and no system package manager involved. **Help → Diagnostics**
reports what was found if you want to confirm.

### One note about Linux

Linux only, and it is not about video. AvialSync's user interface is built on Qt, which needs a few
graphics libraries from the system — `libgl1`, `libxkbcommon`, and the usual X11/xcb set.

**Every ordinary Linux desktop already has these**, because anything with a graphical session does.
You will only hit this on a minimal install: a bare Docker image, a headless server, or a stripped
CI container. The symptom is a Qt error at launch mentioning `libGL.so.1` or an `xcb` plugin, not a
video problem.

On Debian or Ubuntu:

```bash
sudo apt install libgl1 libxkbcommon-x11-0
```

This is a requirement of Qt itself and applies to every Python GUI application built on it. No
packaging choice on our side can remove it. Windows and macOS have no equivalent — there, `pip
install avialsync` really is the only step.

### Windows

Windows needs nothing beyond `pip`, but there is one Windows-only precaution about where `pip` puts
things. Neither step needs administrator rights.

#### 1. Create the environment

```powershell
conda create -n avialsync python=3.12 -y
conda activate avialsync
python -m pip install avialsync
```

#### 2. Keep per-user packages out of the environment

This step is not optional on Windows, and skipping it produces a crash that looks like a bug in
AvialSync. A conda environment is not a virtualenv: it still reads your **per-user** site-packages
directory, `%APPDATA%\Python\Python312\site-packages`, and it reads it *before* the environment's
own packages. Anything an earlier `pip install --user` left there wins over what you just
installed. The usual casualty is a `quantities` too old for the environment's NumPy, which makes
`import neo` fail and takes AvialSync's ephys support with it — see
[a startup error naming numpy or quantities](troubleshooting.md#a-startup-error-naming-numpy-or-quantities).

Set this once, then open a new terminal:

```powershell
setx PYTHONNOUSERSITE 1
```

To confirm the environment is clean, check that nothing AvialSync imports resolves outside it:

```powershell
python -c "import neo, quantities, numpy; print(neo.__file__); print(quantities.__file__)"
```

Both paths must sit under `...\.conda\envs\avialsync\`. If either names `AppData\Roaming\Python`,
the per-user directory is still shadowing the environment; `PYTHONNOUSERSITE` fixes the current
environment, and deleting `%APPDATA%\Python\Python312` fixes it everywhere.

#### 3. Run it

```powershell
avialsync
```

There is no third install step. Earlier versions required a `libmpv-2.dll` downloaded by hand from
SourceForge plus a separate FFmpeg and an `AVIALSYNC_MEDIA_ROOT` environment variable; none of that
is needed any more, and you can delete `AVIALSYNC_MEDIA_ROOT` if you set it previously.

## Check the installation

```bash
avialsync demo
```

This generates and opens a complete sample session, so you can confirm video, plots, and
synchronization work before adding your own recordings. **Help → Diagnostics** shows what the
decoder reported.

Running from a Git checkout instead? See
[development setup](technical/development.md).
