# Installation

AvialSync installs in one of two ways. The desktop installer is self-contained. A `pip` install is
smaller and scriptable, but it cannot supply two native components that video playback and export
depend on — see [What pip cannot install](#what-pip-cannot-install).

## Desktop installers (recommended)

Download the artifact for your platform from the
[GitHub Releases page](https://github.com/anzalks/avialsync/releases):

| Platform | File | Install |
|---|---|---|
| Windows | `AvialSync-Setup.exe` | Run the installer |
| macOS | `AvialSync.dmg` | Open it and drag **AvialSync** to Applications |
| Linux | `AvialSync.AppImage` | `chmod +x AvialSync.AppImage`, then run it |

Each bundles libmpv and FFmpeg, so nothing else is required. The AppImage is portable and needs no
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

### What pip cannot install

`pip install avialsync` supplies every Python dependency, but two runtime components are native
libraries rather than Python packages, so `pip` cannot deliver them:

- **libmpv** plays video. The `python-mpv` dependency is only a binding — it loads a libmpv that
  already exists on the machine and ships no copy of its own.
- **FFmpeg** (`ffmpeg` and `ffprobe`) probes files and writes exports.

AvialSync still opens without them, and its time-series, tracking, annotation, and session features
all work. Video stays disabled and a `Missing libmpv` dialog names the step for your platform.
**Help → Diagnostics** reports what was found.

Install both once:

| Platform | Command |
|---|---|
| macOS | `brew install ffmpeg mpv` |
| Debian / Ubuntu | `sudo apt install ffmpeg libmpv2` (`libmpv1` on releases before that package) |
| Fedora | `sudo dnf install ffmpeg mpv-libs` |
| Arch | `sudo pacman -S ffmpeg mpv` |

### Windows

Windows needs the same two native components, plus one Windows-only precaution about where `pip`
puts things. None of the steps below need administrator rights.

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

#### 3. Supply libmpv and FFmpeg

No Windows package manager ships `libmpv-2.dll`, so fetch it directly: download an
`mpv-dev-x86_64-*` archive from the
[mpv-player-windows libmpv files](https://sourceforge.net/projects/mpv-player-windows/files/libmpv/),
extract it, and point AvialSync at the folder that holds the DLL.

```powershell
winget install --id Gyan.FFmpeg.Shared -e
setx AVIALSYNC_MEDIA_ROOT "C:\path\to\mpv-dev"
```

`AVIALSYNC_MEDIA_ROOT` must name the directory that *directly* contains `libmpv-2.dll`; a parent
folder is not searched. AvialSync looks there before the conda environment and `PATH`, and the same
folder may hold `ffmpeg.exe` and `ffprobe.exe`. Open a new terminal after `setx` so the variable is
set, then run `avialsync`.

## Check the installation

```bash
avialsync demo
```

This generates and opens a complete sample session, so you can confirm video, plots, and
synchronization work before adding your own recordings. **Help → Diagnostics** shows whether libmpv
and hardware decoding were found.

Running from a Git checkout instead? See
[development setup](technical/development.md).
