"""Regression tests for built-bundle startup verification."""

import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_smoke_module() -> ModuleType:
    path = Path("packaging/smoke_test.py")
    spec = importlib.util.spec_from_file_location("avialview_bundle_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_executable_uses_platform_name(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    windows_executable = tmp_path / "avialview.exe"
    windows_executable.touch()

    assert smoke.bundle_executable(tmp_path, "win32") == windows_executable


def test_bundle_smoke_is_headless_bounded_and_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = _load_smoke_module()
    executable = tmp_path / ("avialview.exe" if smoke.sys.platform == "win32" else "avialview")
    executable.touch()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    smoke.smoke_bundle(tmp_path, timeout=7.0)

    command, kwargs = calls[0]
    assert command == [str(executable), "--smoke-test"]
    assert kwargs["timeout"] == 7.0
    assert kwargs["check"] is True
    assert kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"


def test_demo_bundle_smoke_uses_fresh_data_and_waits_for_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = _load_smoke_module()
    executable = tmp_path / ("avialview.exe" if smoke.sys.platform == "win32" else "avialview")
    executable.touch()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    smoke.smoke_bundle(tmp_path, timeout=120.0, demo=True)

    command, kwargs = calls[0]
    assert command == [str(executable), "demo", "--smoke-test"]
    demo_dir = Path(str(kwargs["env"]["AVIALVIEW_DEMO_DIR"]))
    assert demo_dir.parent == tmp_path.parent
    # The application must give up before the harness kills it, so the failure
    # names what it was waiting for instead of only how long it took.
    assert float(str(kwargs["env"]["AVIALVIEW_SMOKE_DEADLINE_S"])) < 120.0


def test_script_entrypoint_runs_bundle_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    executable = tmp_path / ("avialview.exe" if sys.platform == "win32" else "avialview")
    executable.touch()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> None:
        calls.append(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["smoke_test.py", str(tmp_path)])

    runpy.run_path("packaging/smoke_test.py", run_name="__main__")

    assert calls == [[str(executable), "--smoke-test"]]
    assert capsys.readouterr().out == "AvialView bundle smoke test passed (offscreen)\n"


def test_bundle_smoke_can_require_a_real_platform_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shipped bundle must be checkable against the plugin a desktop loads.

    "offscreen" proves nothing about xcb: a bundle can start headlessly and
    still fail to open a window on a real display.
    """
    smoke = _load_smoke_module()
    executable = tmp_path / ("avialview.exe" if smoke.sys.platform == "win32" else "avialview")
    executable.touch()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    smoke.smoke_bundle(tmp_path, timeout=7.0, qt_platform="xcb")

    assert calls[0][1]["env"]["QT_QPA_PLATFORM"] == "xcb"


def test_release_workflow_smoke_tests_the_staged_bundle() -> None:
    """Freezing a bundle is release-tag work, and it must be gated on startup."""
    command = "python packaging/smoke_test.py dist/avialview"
    release_command = f"{command} --demo --timeout 300"

    assert release_command in Path(".github/workflows/release.yml").read_text(encoding="utf-8")


def test_ci_does_not_build_installers() -> None:
    """CI proves correctness on every push; only a tag builds and ships.

    Bundling on every push of every branch cost three PyInstaller runs per
    push for work that only a release consumes.
    """
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pyinstaller" not in ci_workflow.lower()
    assert "build_bundle.py" not in ci_workflow
    assert "smoke_test.py" not in ci_workflow
    # The matrix that does run must still cover every supported platform.
    assert "os: [ubuntu-24.04, macos-15, windows-2022]" in ci_workflow


def test_linux_release_proves_the_bundle_opens_on_a_real_display() -> None:
    """A Linux bundle that only ever ran offscreen is an untested installer."""
    release_workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "--qt-platform xcb" in release_workflow
    assert "xvfb-run" in release_workflow
    # Qt 6 loads these through the xcb plugin; a desktop has them, so the check
    # is of the bundle's own plugin set rather than of the runner image.
    assert "libxcb-cursor0" in release_workflow
