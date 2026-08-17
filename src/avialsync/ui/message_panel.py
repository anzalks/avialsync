"""Recorded messages: the store that maps them, and the panel that lists them.

A message is prose the *rig* wrote — an acquisition system's annotation stream,
a commented file header.  It is deliberately not an
:class:`~avialsync.ui.annotations.Marker`: a marker is authored by the user,
editable in place, and exported as their own work, while a message is evidence
belonging to the source file.  Sharing one store would make a data record
silently editable and would mix the two provenances in the annotation export,
so they stay apart and merely sit in neighbouring tabs.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.messages import Message
from avialsync.core.timeline import TimeMap
from avialsync.ui.time_format import TimeDisplayMode, format_time


@dataclasses.dataclass(frozen=True)
class MappedMessage:
    """One message placed on the master clock, with the file it came from."""

    text: str
    #: Master-time seconds, or ``None`` for a record the file never timestamped.
    time: float | None
    source_id: str
    channel: str


class MessageStore(QObject):
    """Messages from every loaded source, on the master clock.

    Raw source times are kept, never mapped-and-forgotten: an offset correction
    has to move a note with the samples it describes, and that is only possible
    while the source-time original still exists.  This mirrors how channel data
    is remapped without being re-imported.
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._by_source: dict[str, tuple[Message, ...]] = {}
        self._maps: dict[str, TimeMap] = {}

    def set_source_messages(self, source_id: str, messages: tuple[Message, ...]) -> None:
        """Replace the messages attributed to *source_id*."""
        if not messages:
            if self._by_source.pop(source_id, None) is not None:
                self.changed.emit()
            return
        self._by_source[source_id] = tuple(messages)
        self.changed.emit()

    def set_source_mapping(self, source_id: str, offset: float, drift_ppm: float) -> None:
        """Re-place one source's messages after its alignment changed."""
        if source_id not in self._by_source and offset == 0.0 and drift_ppm == 0.0:
            self._maps.pop(source_id, None)
            return
        self._maps[source_id] = TimeMap(offset=offset, drift_ppm=drift_ppm)
        if source_id in self._by_source:
            self.changed.emit()

    def remove_source(self, source_id: str) -> None:
        self._maps.pop(source_id, None)
        if self._by_source.pop(source_id, None) is not None:
            self.changed.emit()

    def clear(self) -> None:
        had_any = bool(self._by_source)
        self._by_source.clear()
        self._maps.clear()
        if had_any:
            self.changed.emit()

    def messages(self) -> list[MappedMessage]:
        """Return every message on the master clock, untimed notes first.

        A recording that a session fans out into several streams hands the same
        annotation stream to each import, so the identical note arrives once per
        stream.  Collapsing them here rather than in the loader keeps the plugin
        contract honest — a source reports what it contains — and puts the fix
        where the duplication is actually observable.
        """
        seen: set[tuple[str, str]] = set()
        untimed: list[MappedMessage] = []
        timed: list[MappedMessage] = []
        for source_id, messages in self._by_source.items():
            time_map = self._maps.get(source_id)
            for message in messages:
                master = (
                    None
                    if message.time is None
                    else (message.time if time_map is None else time_map.to_master(message.time))
                )
                # Two streams of one recording repeat a note verbatim at the
                # same instant; two genuinely distinct notes that collide on
                # both text and microsecond are indistinguishable evidence
                # anyway, so showing one of them loses nothing a user could act
                # on.
                key = ("" if master is None else f"{master:.6f}", message.text)
                if key in seen:
                    continue
                seen.add(key)
                mapped = MappedMessage(
                    text=message.text,
                    time=master,
                    source_id=source_id,
                    channel=message.channel,
                )
                (untimed if master is None else timed).append(mapped)
        timed.sort(key=lambda m: float(m.time or 0.0))
        return untimed + timed


class MessagePanel(QGroupBox):
    """Chronological list of recorded messages; a row seeks the timeline.

    Read-only by construction.  The table never accepts an edit trigger, because
    the text belongs to the source file and an editable cell would invite a user
    to change a record they cannot save back.
    """

    seek_requested = Signal(float)

    _TIME_COLUMN = 0
    _SOURCE_COLUMN = 1
    _TEXT_COLUMN = 2

    def __init__(self, store: MessageStore, parent: QWidget | None = None) -> None:
        super().__init__("Recorded Messages", parent)
        self._store = store
        self._store.changed.connect(self._refresh)
        self._filter = ""
        self._rows: list[MappedMessage] = []
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Filter messages…")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Filter recorded messages")
        self._search.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search)

        # Untimed records are a separate block above the table, not rows in it.
        # The file gave them no time, and a "—" in a sorted time column reads as
        # a missing measurement rather than as a property of the record.
        self._notes = QLabel(self)
        self._notes.setWordWrap(True)
        self._notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._notes.setAccessibleName("Untimed source notes")
        self._notes.setVisible(False)
        layout.addWidget(self._notes)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Time", "Source", "Message"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self._TIME_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._SOURCE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._TEXT_COLUMN, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAccessibleName("Recorded messages")
        self._table.itemSelectionChanged.connect(self._on_row_activated)
        layout.addWidget(self._table)

        self._empty = QLabel("No messages in the loaded sources.", self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

        self._refresh()

    # ── Public API ────────────────────────────────────────────────────

    def set_time_mode(self, mode: TimeDisplayMode, t_epoch: float = 0.0) -> None:
        """Adopt the window's time display mode, like every other timed widget."""
        self._time_mode = mode
        self._t_epoch = t_epoch
        self._refresh()

    # ── Internal ──────────────────────────────────────────────────────

    def _on_filter_changed(self, text: str) -> None:
        self._filter = text.strip().casefold()
        self._refresh()

    def _matches(self, message: MappedMessage) -> bool:
        if not self._filter:
            return True
        haystack = f"{message.text} {_source_name(message.source_id)} {message.channel}"
        return self._filter in haystack.casefold()

    def _refresh(self) -> None:
        messages = self._store.messages()
        visible = [message for message in messages if self._matches(message)]

        notes = [message for message in visible if message.time is None]
        self._notes.setVisible(bool(notes))
        if notes:
            self._notes.setText(
                "\n".join(f"{_source_name(note.source_id)}: {note.text}" for note in notes)
            )

        self._rows = [message for message in visible if message.time is not None]
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._rows))
        for row, message in enumerate(self._rows):
            time_item = QTableWidgetItem(
                format_time(float(message.time or 0.0), self._time_mode, self._t_epoch)
            )
            source_label = _source_name(message.source_id)
            if message.channel:
                source_label = f"{source_label} · {message.channel}"
            source_item = QTableWidgetItem(source_label)
            text_item = QTableWidgetItem(message.text)
            # The full text is the tooltip because a long note is elided in the
            # cell, and this panel exists to let it be read.
            text_item.setToolTip(message.text)
            self._table.setItem(row, self._TIME_COLUMN, time_item)
            self._table.setItem(row, self._SOURCE_COLUMN, source_item)
            self._table.setItem(row, self._TEXT_COLUMN, text_item)
        self._table.blockSignals(False)

        has_any = bool(notes or self._rows)
        self._table.setVisible(bool(self._rows))
        self._empty.setVisible(not has_any)
        self._empty.setText(
            "No message matches this filter."
            if messages and not has_any
            else "No messages in the loaded sources."
        )

    def _on_row_activated(self) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if len(rows) != 1:
            return
        row = rows.pop()
        if 0 <= row < len(self._rows):
            time = self._rows[row].time
            if time is not None:
                self.seek_requested.emit(float(time))


def _source_name(source_id: str) -> str:
    """Return the file name of *source_id*, falling back to the id itself."""
    return Path(source_id).name or source_id
