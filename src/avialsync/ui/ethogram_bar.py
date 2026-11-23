"""Configurable 1–9 ethogram hotkeys (point and bout coding) and marker navigation."""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.annotations import AnnotationStore, VideoFrame
from avialsync.ui.app_settings import app_settings
from avialsync.ui.design_tokens import ControlRole, apply_role, spacing
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = [
    "EthogramBar",
    "EthogramSlot",
    "jump_to_marker",
    "load_ethogram_slots",
    "mark_ab_range",
    "save_ethogram_slots",
    "trigger_ethogram_slot",
]

EthogramMode = Literal["point", "bout"]

_SETTINGS_KEY = "annotations/ethogram_json"

_DEFAULT_SLOTS: tuple[tuple[int, str, EthogramMode], ...] = (
    (1, "Grooming", "bout"),
    (2, "Rearing", "bout"),
    (3, "Locomotion", "bout"),
    (4, "Stimulus", "point"),
    (5, "Freeze", "bout"),
    (6, "", "bout"),
    (7, "", "bout"),
    (8, "", "point"),
    (9, "", "point"),
)


@dataclasses.dataclass(frozen=True)
class EthogramSlot:
    """One numeric hotkey binding (``1``–``9``) for rapid behavioral coding."""

    digit: int
    label: str
    mode: EthogramMode = "bout"


@dataclasses.dataclass
class _ActiveBout:
    digit: int
    label: str
    t_start: float
    video_frames: list[VideoFrame]


def load_ethogram_slots() -> list[EthogramSlot]:
    """Read configured ``1``–``9`` ethogram definitions from ``QSettings``."""
    raw = app_settings().value(_SETTINGS_KEY, "")
    by_digit: dict[int, EthogramSlot] = {
        digit: EthogramSlot(digit=digit, label=label, mode=mode)
        for digit, label, mode in _DEFAULT_SLOTS
    }
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = []
        if isinstance(parsed, list):
            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                try:
                    digit = int(entry.get("digit", 0))
                except (TypeError, ValueError):
                    continue
                if not 1 <= digit <= 9:
                    continue
                mode_raw = str(entry.get("mode", "bout"))
                mode: EthogramMode = "point" if mode_raw == "point" else "bout"
                label = str(entry.get("label", "")).strip()
                by_digit[digit] = EthogramSlot(digit=digit, label=label, mode=mode)
    return [by_digit[d] for d in range(1, 10)]


def save_ethogram_slots(slots: list[EthogramSlot]) -> None:
    """Persist ``1``–``9`` ethogram definitions to ``QSettings``."""
    payload = [
        {"digit": slot.digit, "label": slot.label.strip(), "mode": slot.mode}
        for slot in slots
        if 1 <= slot.digit <= 9
    ]
    app_settings().setValue(_SETTINGS_KEY, json.dumps(payload))


class _EthogramConfigDialog(QDialog):
    """Edit behavioral labels and Point/Bout modes for hotkeys 1–9."""

    def __init__(self, slots: list[EthogramSlot], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Configure Ethogram Hotkeys (1–9)"))
        self.setAccessibleName(tr("Configure Ethogram Hotkeys"))
        layout = QVBoxLayout(self)
        lead = QLabel(
            tr(
                "Assign behaviors to number keys 1–9. A Point adds an instant flag; "
                "a Bout starts on the first press and records a range on the second press."
            ),
            self,
        )
        lead.setWordWrap(True)
        layout.addWidget(lead)

        form = QFormLayout()
        self._edits: list[tuple[int, QLineEdit, QComboBox]] = []
        for slot in slots:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(spacing("xs"))
            edit = QLineEdit(slot.label, row)
            edit.setPlaceholderText(tr("(unused)"))
            edit.setAccessibleName(tr("Label for hotkey {digit}").format(digit=slot.digit))
            combo = QComboBox(row)
            combo.addItem(tr("Bout (start/stop)"), "bout")
            combo.addItem(tr("Point (instant)"), "point")
            combo.setCurrentIndex(1 if slot.mode == "point" else 0)
            combo.setAccessibleName(tr("Mode for hotkey {digit}").format(digit=slot.digit))
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(combo)
            form.addRow(tr("Key {digit}:").format(digit=slot.digit), row)
            self._edits.append((slot.digit, edit, combo))
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        for btn in buttons.buttons():
            apply_role(btn, ControlRole.SECONDARY)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_slots(self) -> list[EthogramSlot]:
        return [
            EthogramSlot(
                digit=digit,
                label=edit.text().strip(),
                mode="point" if combo.currentData() == "point" else "bout",
            )
            for digit, edit, combo in self._edits
        ]


class EthogramBar(QWidget):
    """Compact behavioral hotkey strip inside the Changes inspector page."""

    slot_activated = Signal(int)  # 1..9

    def __init__(self, annotations: AnnotationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._annotations = annotations
        self._slots: list[EthogramSlot] = load_ethogram_slots()
        self._active_bouts: dict[int, _ActiveBout] = {}
        self._buttons: dict[int, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(spacing("xs"))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(tr("Ethogram (1–9)"), self)
        self.configure_button = QPushButton(tr("Edit Keys…"), self)
        apply_role(self.configure_button, ControlRole.SECONDARY)
        self.configure_button.setAccessibleName(tr("Configure ethogram hotkeys"))
        self.configure_button.setToolTip(
            tr("Choose behavioral labels and point/bout modes for number keys 1–9")
        )
        self.configure_button.clicked.connect(self.open_config_dialog)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.configure_button)
        root.addLayout(header)

        self._button_host = QWidget(self)
        self._button_row = QGridLayout(self._button_host)
        self._button_row.setContentsMargins(0, 0, 0, 0)
        self._button_row.setHorizontalSpacing(spacing("xs"))
        self._button_row.setVerticalSpacing(spacing("xs"))
        root.addWidget(self._button_host)

        bout_row = QHBoxLayout()
        bout_row.setContentsMargins(0, 0, 0, 0)
        self.active_bout_label = QLabel("", self)
        self.active_bout_label.setWordWrap(True)
        self.cancel_bout_button = QPushButton(tr("Cancel Bout"), self)
        apply_role(self.cancel_bout_button, ControlRole.SECONDARY)
        self.cancel_bout_button.setAccessibleName(tr("Cancel active behavioral bout"))
        self.cancel_bout_button.setToolTip(tr("Discard the in-progress behavioral bout"))
        self.cancel_bout_button.clicked.connect(self.cancel_active_bouts)
        bout_row.addWidget(self.active_bout_label, 1)
        bout_row.addWidget(self.cancel_bout_button)
        self._bout_widget = QWidget(self)
        self._bout_widget.setLayout(bout_row)
        self._bout_widget.setVisible(False)
        root.addWidget(self._bout_widget)

        self._rebuild_buttons()

    @property
    def slots(self) -> list[EthogramSlot]:
        return list(self._slots)

    def set_slots(self, slots: list[EthogramSlot]) -> None:
        """Replace and persist configured ethogram slots."""
        self._slots = list(slots)
        save_ethogram_slots(self._slots)
        self._rebuild_buttons()

    def active_bout_digits(self) -> tuple[int, ...]:
        return tuple(sorted(self._active_bouts))

    def cancel_active_bouts(self) -> None:
        """Cancel any open state bouts without writing markers."""
        self._active_bouts.clear()
        self._sync_bout_ui()

    def open_config_dialog(self) -> None:
        dlg = _EthogramConfigDialog(self._slots, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_slots(dlg.result_slots())

    def trigger_slot(
        self,
        digit: int,
        t_master: float,
        video_frames: list[VideoFrame] | None = None,
    ) -> str:
        """Execute hotkey *digit* at *t_master*; returns status prose (empty if unused)."""
        slot = next((s for s in self._slots if s.digit == digit), None)
        if slot is None or not slot.label:
            return ""
        frames = list(video_frames or [])
        if slot.mode == "point":
            self._annotations.add_point(t_master, slot.label, video_frames=frames)
            return tr("Marked {label} at {time:.3f}s").format(label=slot.label, time=t_master)

        active = self._active_bouts.pop(digit, None)
        if active is None:
            self._active_bouts[digit] = _ActiveBout(
                digit=digit, label=slot.label, t_start=t_master, video_frames=frames
            )
            self._sync_bout_ui()
            return tr("Started {label} bout at {time:.3f}s (press {digit} to end)").format(
                label=slot.label, time=t_master, digit=digit
            )

        self._annotations.add_range(
            active.t_start, t_master, active.label, video_frames=active.video_frames
        )
        self._sync_bout_ui()
        t0, t1 = sorted((active.t_start, t_master))
        return tr("Recorded {label} ({start:.3f}–{end:.3f}s)").format(
            label=active.label, start=t0, end=t1
        )

    def _rebuild_buttons(self) -> None:
        while self._button_row.count():
            item = self._button_row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()
        visible_idx = 0
        for slot in self._slots:
            if not slot.label:
                continue
            tag = "↔" if slot.mode == "bout" else "•"
            btn = QPushButton(f"{slot.digit} {tag} {slot.label}", self._button_host)
            apply_role(btn, ControlRole.SECONDARY)
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            btn.setMinimumWidth(0)
            btn.setCheckable(slot.mode == "bout")
            btn.setAccessibleName(
                tr("Ethogram key {digit}: {label}").format(digit=slot.digit, label=slot.label)
            )
            mode_desc = (
                tr("start or finish a range bout")
                if slot.mode == "bout"
                else tr("place an instant point marker")
            )
            btn.setToolTip(
                tr("Press {digit} to {action} for {label}").format(
                    digit=slot.digit, action=mode_desc, label=slot.label
                )
            )
            btn.clicked.connect(lambda _c=False, d=slot.digit: self.slot_activated.emit(d))
            row_idx, col_idx = divmod(visible_idx, 2)
            self._button_row.addWidget(btn, row_idx, col_idx)
            self._buttons[slot.digit] = btn
            visible_idx += 1
        self._sync_bout_ui()

    def _sync_bout_ui(self) -> None:
        for digit, btn in self._buttons.items():
            if btn.isCheckable():
                blocked = btn.blockSignals(True)
                btn.setChecked(digit in self._active_bouts)
                btn.blockSignals(blocked)
        if not self._active_bouts:
            self._bout_widget.setVisible(False)
            self.active_bout_label.setText("")
            return
        parts = [f"[{b.digit}] {b.label} ({b.t_start:.2f}s…)" for b in self._active_bouts.values()]
        self.active_bout_label.setText(tr("Active: {bouts}").format(bouts=", ".join(parts)))
        self._bout_widget.setVisible(True)


def _frames_at(window: MainWindow, t_master: float) -> list[VideoFrame]:
    return [
        VideoFrame(
            path=str(r["path"]),
            frame_index=int(r["frame_index"]),
            media_timestamp=float(r["media_timestamp"]),
        )
        for r in window.video_grid.frame_records_at(t_master)
    ]


def mark_ab_range(window: MainWindow) -> None:
    """Create a range annotation from the active transport A–B loop."""
    span = window.transport.ab_range()
    if span is None:
        return
    t0, t1 = span
    window.annotation_store.add_range(t0, t1, video_frames=_frames_at(window, t0))
    window.statusBar().showMessage(
        tr("Marked range {start:.3f}–{end:.3f}s").format(start=t0, end=t1), 2000
    )


def jump_to_marker(window: MainWindow, direction: int) -> None:
    """Seek the master clock to the previous (``-1``) or next (``+1``) marker boundary."""
    times_set: set[float] = set()
    for marker in window.annotation_store.markers:
        times_set.add(float(marker.t_start))
        if marker.t_end is not None:
            times_set.add(float(marker.t_end))
    if not times_set:
        return
    ordered = sorted(times_set)
    now = window.clock.state.t
    eps = 1e-6
    if direction < 0:
        candidates = [t for t in ordered if t < now - eps]
        target = candidates[-1] if candidates else None
    else:
        candidates = [t for t in ordered if t > now + eps]
        target = candidates[0] if candidates else None
    if target is not None:
        bounds = window.clock.state.bounds
        if bounds[1] > bounds[0]:
            target = max(bounds[0], min(bounds[1], target))
        window.player.seek(target, exact=True)


def trigger_ethogram_slot(window: MainWindow, digit: int) -> None:
    """Fire ethogram hotkey *digit* unless focus is inside a text/number input."""
    app = QApplication.instance()
    focus = app.focusWidget() if isinstance(app, QApplication) else None
    if isinstance(focus, (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)):
        return
    t_master = window.clock.state.t
    msg = window.changes_panel.ethogram_bar.trigger_slot(
        digit, t_master, _frames_at(window, t_master)
    )
    if msg:
        window.statusBar().showMessage(msg, 2500)
