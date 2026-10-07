"""Help reaches the shipped documentation (DS-13, F-33)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui import help_controller
from avialsync.ui.about import docs_url, project_urls
from avialsync.ui.main_window import MainWindow
from avialsync.ui.menus.help import FIRST_SESSION_PAGE

DOCS = Path("docs")


def _source_of(page: str) -> Path:
    """The Markdown file an ``.html`` guide page is built from."""
    return DOCS / page.split("#", 1)[0].replace(".html", ".md")


@pytest.fixture
def window(qapp: QApplication, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def test_first_session_tutorial_opens_its_shipped_page(window: MainWindow, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        help_controller.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    assert window._act_first_session in window._all_actions
    window._act_first_session.trigger()
    assert opened == [docs_url(FIRST_SESSION_PAGE)]
    assert opened[0].startswith(project_urls()["Documentation"].rstrip("/"))
    assert _source_of(FIRST_SESSION_PAGE).is_file()


def test_every_learn_more_link_names_a_shipped_page() -> None:
    """Step panels link into the guide; each link must be a page the docs build."""
    pages = set()
    for module in Path("src/avialsync/ui").rglob("*.py"):
        pages.update(re.findall(r'docs_url\("([^"]+)"\)', module.read_text(encoding="utf-8")))
    assert pages, "step panels link to the guide"
    for page in pages:
        source = _source_of(page)
        assert source.is_file(), f"{page} has no source in docs/"
        if "#" in page:
            anchor = page.split("#", 1)[1]
            headings = re.findall(r"^#+ (.+)$", source.read_text(encoding="utf-8"), re.M)
            slugs = {
                re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-") for h in headings
            }
            assert anchor in slugs, f"{page}: no heading makes #{anchor}"
