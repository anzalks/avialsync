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

AvialSync supports Python 3.11 and 3.12.

```bash
python -m pip install avialsync
avialsync
```

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
