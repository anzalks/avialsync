# Installing and testing

## A drop-in: the installed application, no pip

Put the plugin in the plugins folder: **File → Plugins → Open Plugins Folder** opens it
(`~/.avialsync/plugins/`, on Windows `%USERPROFILE%\.avialsync\plugins\`). Then pick **File → Plugins →
Reload Plugins**, or restart.

- A single file, `my_rig.py`, or a package folder, `my_rig/` with an `__init__.py`. A package may
  split itself into modules and import them relatively (`from .reader import Reader`).
- A drop-in runs inside the installed application, so it can import what AvialSync ships: NumPy,
  polars, h5py, tifffile, PyAV, PySide6, and AvialSync itself. A pure-Python library that is not
  shipped goes in `lib/` beside your plugin:

  ```bash
  pip install --target ~/.avialsync/plugins/lib some-package
  ```

  A library with compiled code must match the application's Python (3.11) and platform.
- Files and folders starting with `_` are skipped.

## A package: pip users

Publish `avialsync-plugin-<name>` with entry points:

```toml
[project.entry-points."avialsync.loaders"]
my_format = "my_plugin:MySource"

[project.entry-points."avialsync.sessions"]
my_rig = "my_plugin:MyRigSession"
```

## Which plugin reads what

**File → Plugins** lists every plugin with where it came from, each with a switch. Two plugins equally
sure of one file are not decided by load order: the import review leaves that file unchosen and asks
the user to pick. Two session scanners equally sure of one folder are named in a warning, and the
user switches one off. **Help → Diagnostics** lists every plugin that could not be used, and why.

## Testing: `avialsync plugin-check`

```bash
avialsync plugin-check                       # list plugins and load failures
avialsync plugin-check my_recording          # lay it out as a drop would, and check it
avialsync plugin-check my_recording --output report.txt
```

Without a window it does what a drop does, then checks the result:

- `source_epoch` is an absolute UTC instant, not a session-relative number;
- trials end after they start and do not overlap;
- every item opens, and its chunks are 1-D arrays of one length, never going backwards;
- trigger kinds are ones that exist;
- no two plugins tie for the path.

It exits non-zero when something is wrong, so it also works in a plugin's own test suite:

```python
from avialsync.core.plugin_check import check_path
from avialsync.core.registry import LoaderRegistry


def test_my_rig_lays_out(tmp_path):
    registry = LoaderRegistry(plugin_dirs=[Path("src/my_plugin")])
    report = check_path(registry, make_example_recording(tmp_path))
    assert report.ok, report.text()
```
