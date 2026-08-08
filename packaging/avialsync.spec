# -*- mode: python ; coding: utf-8 -*-
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# PyInstaller supplies SPECPATH as the directory containing this spec.
project_root = Path(SPECPATH).parent
icon_extension = ".ico" if sys.platform == "win32" else ".icns" if sys.platform == "darwin" else ".png"
application_icon = project_root / "packaging" / {
    ".ico": "windows",
    ".icns": "macos",
    ".png": "linux",
}[icon_extension] / f"avialsync{icon_extension}"

hidden_imports = []
hidden_imports += collect_submodules('avialsync')
hidden_imports += ['PySide6', 'pyqtgraph', 'av', 'polars', 'numpy']

a = Analysis(
    [str(project_root / 'src' / 'avialsync' / '__main__.py')],
    pathex=[str(project_root / 'src')],
    binaries=[],
    datas=[(str(project_root / "src" / "avialsync" / "resources" / "avialsync.png"), "avialsync/resources")],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='avialsync',
    icon=str(application_icon),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='avialsync',
)

if sys.platform == "darwin":
    # A one-directory tree is not a launchable macOS application: double-clicking
    # its plain executable in Finder opens Terminal instead of the app. The disk
    # image ships this .app; COLLECT stays for the smoke test and other platforms.
    version_source = (project_root / "src" / "avialsync" / "__init__.py").read_text(encoding="utf-8")
    version_match = re.search(r'^__version__ = "([^"]+)"', version_source, re.MULTILINE)
    if version_match is None:
        raise RuntimeError("src/avialsync/__init__.py declares no __version__")
    full_version = version_match.group(1)
    # CFBundleShortVersionString takes the numeric release only; a PEP 440
    # pre-release suffix such as "0.1.0b4" is not a valid value for it.
    release_version = re.match(r"\d+(?:\.\d+)*", full_version).group(0)
    app = BUNDLE(
        coll,
        name='AvialSync.app',
        icon=str(application_icon),
        bundle_identifier='io.github.anzalks.avialsync',
        version=full_version,
        info_plist={
            'CFBundleName': 'AvialSync',
            'CFBundleDisplayName': 'AvialSync',
            'CFBundleShortVersionString': release_version,
            'CFBundleVersion': full_version,
            'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.education',
        },
    )
