"""Behaviour extracted from :class:`~avialsync.ui.main_window.MainWindow`.

Each module here owns one of the window's responsibilities as plain functions
whose first argument is the window.  ``MainWindow`` keeps a thin method per
function so every existing Qt connection, override, and test monkeypatch still
resolves against the window itself; the bodies simply live next door.

Moved code addresses the window as ``window`` where it previously said
``self``, and keeps calling *its* methods rather than the sibling functions
directly.  That is what preserves patched instance attributes: a test that
replaces ``window._start_drop_scan`` must still intercept the call.
"""
