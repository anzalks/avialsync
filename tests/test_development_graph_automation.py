"""Regression checks for the token-free development graph automation."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_graph_updater_stays_structural_and_offline() -> None:
    """The committed updater must not grow API-backed graph features."""
    source = (REPOSITORY_ROOT / "tools" / "update_graph.py").read_text(encoding="utf-8")

    assert "from graphify.extract import collect_files, extract" in source
    assert "graphify.llm" not in source
    assert "graphify.ingest" not in source
    assert "graphify.transcribe" not in source
    assert '"input": 0, "output": 0' in source
    assert "https://" not in source
    assert "_write_offline_html" in source
    assert "_remove_volatile_commit_id" in source
    assert "_deterministic_communities" in source
    assert "from graphify.cluster import cluster" not in source


def test_hook_leaves_graph_updates_for_manual_review() -> None:
    """The local hook refreshes only; it never changes Git history or staging."""
    hook = (REPOSITORY_ROOT / ".githooks" / "post-commit").read_text(encoding="utf-8")

    assert "python tools/update_graph.py" in hook
    assert "git add" not in hook
    assert "git commit" not in hook


def test_graph_tool_is_outside_the_shared_ci_dependency_set() -> None:
    """Application CI installs ``dev`` and must not install Graphify."""
    pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    dev_section = pyproject.split("graph = [", maxsplit=1)[0]
    assert '"graphifyy' not in dev_section
    assert "graph = [" in pyproject
