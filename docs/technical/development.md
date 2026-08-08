# Development and release

For people running AvialSync from a Git checkout, building the documentation, or cutting a release.
People who installed a release artifact or `pip install avialsync` do not need any of this; see
[Installation](../install.md).

[CONTRIBUTING.md](https://github.com/anzalks/avialsync/blob/main/CONTRIBUTING.md) holds the
contribution rules and the four-command gate every change must pass; `AGENTS.md` is the canonical
source for architecture rules.

## Source checkout

```bash
conda create -n avialsync python=3.12 -y
conda run -n avialsync pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest -x -q
```

The `.[dev]` install supplies everything needed to run and test the application. Nothing the
*application* does needs a media runtime on the machine.

`tools/make_fixtures.py` is the one exception, and it is a build-time tool rather than part of the
app: it shells out to `ffmpeg` to encode the test videos, so a checkout that wants to regenerate
fixtures needs FFmpeg on `PATH`. CI installs it for that reason alone.

### Windows checkout

Install Python 3.11 or 3.12. There is nothing else to place by hand: the application's decoding,
proxy generation, and clip export all come with the Python packages.

To regenerate test fixtures you also need FFmpeg; `winget install --id Gyan.FFmpeg.Shared -e` is a
suitable route. Do not use conda's FFmpeg package for a checkout — it can conflict with the Qt
DLLs.

```powershell
conda run -n avialsync avialsync
conda run -n avialsync python tools/launch_demo.py
conda run -n avialsync avialsync demo
```

After `conda activate avialsync`, the equivalent commands are `avialsync` and
`python C:\path\to\avialsync\tools\launch_demo.py`. The `python` prefix is required for the demo
script: running a `.py` file directly can use Windows' unrelated file association. The launcher
delegates to `avialsync demo`, so both paths behave identically.

## The demo session

`avialsync demo` creates three 30 fps CFR cameras, one VFR camera, a four-channel sensor trace, a
dense ephys/TTL trace with gaps, and DLC-style tracking in your platform application-data folder.
Camera 2 has a known +1.234 s mapping and camera 3 a known 1000 ppm drift mapping, so alignment
tools have a verifiable answer. First-run generation is shown in the progress-and-log dialog; later
runs validate and reuse the cached files.

The documentation screenshots come from the same session:

```bash
conda run -n avialsync python tools/generate_demo_screenshots.py
```

## Building the documentation

The site is built with Read the Docs from `.readthedocs.yaml`. Local preview:

```bash
python -m pip install -e ".[docs]"
sphinx-build -W --keep-going -b html docs docs/_build/html
```

`-W` matches CI, where a Sphinx warning fails the build.

### Connecting the Read the Docs project

The repository is already configured — `.readthedocs.yaml` pins Ubuntu 22.04, Python 3.11, and the
`docs` extra, with `fail_on_warning: true`. What remains is connecting the project once:

1. Sign in at [readthedocs.org](https://readthedocs.org/) with the GitHub account that owns the
   repository, and grant it access to `anzalks/avialsync`.
2. **Import a Project → Import Manually** (or pick the repository from the list). Set the name to
   `avialsync` so the site lands on `https://avialsync.readthedocs.io/`, the address the README
   badge and links already use. A different name means editing both.
3. Leave the default branch as `main`. Read the Docs finds `.readthedocs.yaml` itself; do not set a
   configuration path.
4. **Admin → Automation Rules** is worth one rule: activate and set as default any tag matching
   `.*`, so a released version's docs are published and `/en/stable/` tracks the newest release
   rather than the tip of `main`.
5. Trigger the first build from **Builds → Build version**. It takes about a minute.

The webhook is installed by the GitHub connection, so later pushes and tags build automatically.
Until step 2 is done the documentation badge stays grey and `https://avialsync.readthedocs.io/`
returns 404.

## Releases

GitHub Actions is the sole publisher for release artifacts and PyPI distributions. Do not upload
packages from a developer workstation. A release tag runs cross-platform validation, builds the
wheel and source distribution, and smoke-tests the wheel in a clean environment before building the
platform installers. PyPI publishing starts only after every installer succeeds, and GitHub creates
the release last. The workflow pins and verifies the AppImage build tool before creating the Linux
AppImage; no package-upload token or repository variable is needed.

Two things must exist before a tag can complete, and neither lives in this repository. Both fail
late — after every installer has already been built — so confirm them before tagging:

1. **PyPI trusted publishing** for the `avialsync` project, naming this repository, the `Release`
   workflow, and the `pypi` environment. If the `pypi` GitHub environment has required reviewers,
   the release waits for an approval rather than failing.
2. **A tag reachable from `main`.** The workflow refuses to publish a side branch, and it requires
   the tag, `pyproject.toml`, and `src/avialsync/__init__.py` to name one identical version — which
   is what `tools/prepare_release.py` guarantees.

Prepare a tag from a clean `main` checkout with the guarded helper rather than editing versions or
creating tags by hand:

```bash
conda run -n avialsync python tools/prepare_release.py 0.1.0b1 --dry-run
conda run -n avialsync python tools/prepare_release.py 0.1.0b1
```

It validates the version, updates both package-version authorities, builds and checks the
wheel/sdist, commits the change, creates annotated `v0.1.0b1`, and pushes it. The helper permits
only the offline `graphify-out/graph.json` as a pre-existing dirty file; commit or resolve every
other change first.

### Signing

Release artifacts are not yet code-signed or notarized. `packaging/windows/sign.ps1` and
`packaging/macos/sign_notarize.sh` are placeholders, and nothing in CI invokes them; signing needs
an Apple Developer account and a Windows code-signing certificate. Until then, every download
carries the [first-launch warnings](../install.md#first-launch-security-warnings).
