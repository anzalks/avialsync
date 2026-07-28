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
    assert capsys.readouterr().out == "AvialView bundle smoke test passed\n"


def test_quality_workflows_smoke_test_bundles() -> None:
    command = "python packaging/smoke_test.py dist/avialview"
    release_command = f"{command} --demo --timeout 120"

    assert command in Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert release_command in Path(".github/workflows/release.yml").read_text(encoding="utf-8")
