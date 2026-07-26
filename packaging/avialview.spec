# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# PyInstaller supplies SPECPATH as the directory containing this spec.
project_root = Path(SPECPATH).parent
media_root = Path(os.environ.get("AVIALVIEW_MEDIA_ROOT", ""))
media_binaries = []
if media_root.is_dir():
    media_binaries = [(str(path), ".") for path in media_root.iterdir() if path.is_file()]

hidden_imports = []
hidden_imports += collect_submodules('avialview')
hidden_imports += ['PySide6', 'pyqtgraph', 'mpv', 'polars', 'numpy']

a = Analysis(
    [str(project_root / 'src' / 'avialview' / '__main__.py')],
    pathex=[str(project_root / 'src')],
    binaries=media_binaries,
    datas=[],
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
    name='avialview',
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
    name='avialview',
)
