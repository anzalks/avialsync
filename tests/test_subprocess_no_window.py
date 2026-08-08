"""Child processes must not flash a console window on Windows (V-14).

A windowed Windows build has no console of its own, so every ``ffprobe`` or
``ffmpeg`` child is handed a brand new one. It appears, steals focus, and
vanishes. A four-camera session does that four times during load, and every
export or proxy build does it again — the single most visible "hiccup" on
Windows.

``runtime.no_window_kwargs()`` supplies ``CREATE_NO_WINDOW`` there and an empty
mapping everywhere else, so call sites can splat it unconditionally.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from avialsync.runtime import no_window_kwargs

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "avialsync"

#: Call sites that can never run on Windows because an enclosing
#: ``sys.platform`` check excludes it. Each entry needs that guard to be real.
PLATFORM_GUARDED = {
    # ui/theme.py reads the macOS accent colour inside `if sys.platform == "darwin"`.
    ("ui/theme.py", "defaults"),
}

SPAWNING_CALLS = {"run", "Popen", "check_output", "call", "check_call"}


def _subprocess_calls() -> list[tuple[Path, ast.Call]]:
    """Return every ``subprocess.<spawn>()`` call in production code."""
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in SPAWNING_CALLS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
            ):
                found.append((path, node))
    return found


def _suppresses_console(call: ast.Call) -> bool:
    """Whether the call splats ``no_window_kwargs()`` or sets creationflags."""
    for keyword in call.keywords:
        if keyword.arg == "creationflags":
            return True
        if keyword.arg is None:  # **kwargs splat
            value = keyword.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "no_window_kwargs"
            ):
                return True
    return False


def _is_platform_guarded(path: Path, call: ast.Call) -> bool:
    relative = path.relative_to(SRC_ROOT).as_posix()
    source = path.read_text(encoding="utf-8").splitlines()
    window = "\n".join(source[max(0, call.lineno - 12) : call.lineno + 4])
    return any(
        relative == guarded_file and marker in window for guarded_file, marker in PLATFORM_GUARDED
    )


def test_every_media_subprocess_suppresses_the_console_window() -> None:
    offenders = []
    for path, call in _subprocess_calls():
        if _suppresses_console(call) or _is_platform_guarded(path, call):
            continue
        offenders.append(f"{path.relative_to(SRC_ROOT.parent.parent)}:{call.lineno}")

    assert not offenders, (
        "These subprocess calls will flash a console window on Windows. "
        "Splat `**no_window_kwargs()` from avialsync.runtime: " + ", ".join(offenders)
    )


def test_at_least_one_call_site_is_actually_checked() -> None:
    """Guard the guard: an empty scan would make the test above vacuous.

    The floor tracks how many call sites actually exist and is expected to fall
    as they go. Every media subprocess is gone with D-075 — probing, decoding,
    proxy generation, clip export, and the demo generator all run in-process
    against PyAV now — so what remains is unrelated to video.
    """
    assert len(_subprocess_calls()) >= 1


@pytest.mark.skipif(sys.platform == "win32", reason="asserts the non-Windows branch")
def test_no_window_kwargs_is_empty_off_windows() -> None:
    assert no_window_kwargs() == {}


def test_no_window_kwargs_sets_create_no_window_on_windows(monkeypatch) -> None:
    """The Windows branch must supply the flag even when tests run elsewhere."""
    import avialsync.runtime as runtime

    monkeypatch.setattr(runtime.sys, "platform", "win32")

    kwargs = runtime.no_window_kwargs()

    assert kwargs == {"creationflags": 0x08000000}
