"""New file writers must use the artifact publication boundary (D-197)."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "avialsync"

# Disposable cache and its builders have their own ownership/commit protocol.
_CACHE_MODULES = {
    "core/cache.py",
    "core/cache_store.py",
    "core/edit_cache.py",
    "core/pyramid.py",
    "engine/importer.py",
    "engine/pyav_reader.py",  # disposable PTS/keyframe index through CacheManager.commit_cache
    "engine/imaging_proxy.py",
    "engine/nwb_cache.py",
    "loaders/video_standard.py",
}

# A producer may write *only to the temporary path publish supplied*. The
# exceptions below are reviewed producer functions, or existing non-artifact
# stores with separate lifecycle rules. New functions need a stated reason.
_KNOWN_WRITERS: dict[str, str] = {
    "core/artifact_provenance.py:write_companion": "Writes publish's temporary JSON path.",
    "core/toml_format.py:write_atomic": "Writes publish's temporary TOML path.",
    "core/point_edit_sidecar.py:write": "Writes publish's temporary CSV path.",
    "core/identity_sidecar.py:write": "Writes publish's temporary CSV path.",
    "core/custom_markers.py:_atomic_write": "Writes publish's temporary CSV path.",
    "core/calibration_ref.py:write_ref": "Writes publish's temporary text path.",
    "core/pose_export.py:_stream": "Streams into publish's temporary CSV path.",
    "core/dlc_export.py:write_labeled_data": "Writes publish's temporary CSV path.",
    "core/session.py:save": "Writes publish's temporary JSON and NPZ paths.",
    "engine/export.py:export_data_slice_csv": "Writes publish's temporary CSV path.",
    "engine/export.py:export_data_slice_parquet": "Writes publish's temporary Parquet path.",
    "ui/annotations.py:write_marker_rows": "Writes publish's temporary CSV path.",
    "engine/snapshot.py:save_figure": "Saves publish's temporary PNG path.",
    "engine/changes_export_worker.py:_save_png": "Saves publish's temporary frame PNG path.",
    "engine/transcode.py:remux_clip": "Writes publish's temporary clip container.",
    "engine/transcode.py:encode_video": "Generic encoder; callers own staging.",
    "engine/transcode.py:encode_proxy": "Disposable proxy encoder has cache ownership.",
    "ui/recovery.py:write_recovery": "Crash recovery has its own startup lifecycle.",
    "ui/recovery.py:dismiss_recovery": "Crash recovery dismissal marker.",
    "loaders/nwb_storage.py:create_remote_link": "App-data link to a remote NWB source.",
    "demo.py:_write_sensors": "Standalone demo data generator, not a user export.",
    "demo.py:_write_ephys": "Standalone demo data generator, not a user export.",
    "demo.py:_write_tracking": "Standalone demo data generator, not a user export.",
}


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return ""


def _write_call(node: ast.Call) -> str | None:
    name = _name(node.func)
    if name in {"os.replace", "os.rename", "pq.write_table"}:
        return name
    if name.startswith("np.save"):
        return name
    if name.endswith((".write_text", ".write_bytes")):
        return name
    if name == "open" or name.endswith(".open"):
        mode = next((kw.value for kw in node.keywords if kw.arg == "mode"), None)
        if mode is None:
            index = 1 if name == "open" else 0
            mode = node.args[index] if len(node.args) > index else None
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            if any(char in mode.value for char in "wax"):
                return f"{name}({mode.value})"
    if name.endswith(".save") and not name.startswith("painter."):
        if any(isinstance(arg, ast.Constant) and arg.value in ("PNG", b"PNG") for arg in node.args):
            return name
    return None


class _WriterCalls(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        self.offenders: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        operation = _write_call(node)
        if operation is not None:
            owner = self.scope[0] if self.scope else "<module>"
            key = f"{self.module}:{owner}"
            if key not in _KNOWN_WRITERS:
                self.offenders.append(f"{key}:{node.lineno} ({operation})")
        self.generic_visit(node)


def test_no_unregistered_file_writer() -> None:
    """Catch any new direct writer in src, with reviewed exceptions above."""
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        module = path.relative_to(SRC).as_posix()
        if module == "core/artifact_io.py" or module in _CACHE_MODULES:
            continue
        visitor = _WriterCalls(module)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        offenders.extend(visitor.offenders)
    assert not offenders, "Route these writes through artifact_io: " + ", ".join(offenders)
