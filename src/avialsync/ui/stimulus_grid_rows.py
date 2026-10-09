"""Which rows a stimulus grid movie carries, chosen in its dialog (D-210).

Only what the session has is listed: each camera and each imaging stack as a
picture row, each sensor group (one data source) as a band with its streams
under it. Pictures are columns per event; a band runs under all of them with
every event overlaid. Defaults: the cameras on screen, the imaging stack shown
in the viewer, and the trigger channel's group with every stream. A live
readout says how large each row will be before anything is encoded.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.errors import ExportError
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_bands import GridBand, GridStream
from avialsync.engine.stimulus_grid_layout import GridRow, plan_grid
from avialsync.ui.i18n import tr

#: A row smaller than this, in output pixels, is too small to read.
_LEGIBLE_ROW = 48
_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class PictureRowOption:
    """A camera or imaging stack the grid can show, with its default."""

    key: str
    label: str
    row: GridRow
    aspect_ratio: float
    checked: bool = True
    kind: str = "camera"


@dataclass(frozen=True)
class StreamOption:
    """One stream of a sensor group."""

    label: str
    reference: ReaderReference
    color: tuple[int, int, int]
    unit: str = ""


@dataclass(frozen=True)
class SensorGroupOption:
    """One data source's streams, drawn as one band."""

    key: str
    label: str
    streams: tuple[StreamOption, ...]
    checked: bool = False


@dataclass
class RowChoices:
    """What the user chose last, so a second export starts from it."""

    order: list[str] = field(default_factory=list)
    checked: set[str] = field(default_factory=set)
    streams: dict[str, set[str]] = field(default_factory=dict)
    layouts: dict[str, str] = field(default_factory=dict)


def _layout_box(parent: QWidget, group: str, value: str) -> QComboBox:
    """How a band draws its streams: overlaid up to four, stacked above, or as chosen."""
    box = QComboBox(parent)
    for data, name in (
        ("auto", tr("Auto")),
        ("overlay", tr("Overlay")),
        ("stacked", tr("Stacked")),
    ):
        box.addItem(name, data)
    box.setAccessibleName(tr("How {group}'s streams are drawn").format(group=group))
    box.setToolTip(tr("Auto overlays up to 4 streams and stacks more in lanes"))
    box.setCurrentIndex(max(0, box.findData(value)))
    return box


class GridRowsPanel(QWidget):
    """A tickable, reorderable list of picture rows and sensor bands."""

    changed = Signal()

    def __init__(
        self,
        pictures: Sequence[PictureRowOption],
        groups: Sequence[SensorGroupOption],
        choices: RowChoices | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pictures = {option.key: option for option in pictures}
        self._groups = {option.key: option for option in groups}
        self._layout_boxes: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(tr("Rows")))
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("Row"), tr("Streams")])
        self.tree.setAccessibleName(tr("Rows in the exported grid"))
        self.tree.setAccessibleDescription(
            tr("Tick the cameras, imaging and sensor groups to export, and the streams of each")
        )
        layout.addWidget(self.tree, 1)
        moves = QHBoxLayout()
        self.up_button = QPushButton(tr("Move up"), self)
        self.down_button = QPushButton(tr("Move down"), self)
        for button, step in ((self.up_button, -1), (self.down_button, 1)):
            button.setAccessibleName(button.text())
            button.clicked.connect(lambda _checked=False, s=step: self._move(s))
            moves.addWidget(button)
        layout.addLayout(moves)
        self.estimate = QLabel("", self)
        self.estimate.setWordWrap(True)
        self.estimate.setAccessibleName(tr("Exported row sizes"))
        layout.addWidget(self.estimate)
        self._build(choices)
        self.tree.itemChanged.connect(self._item_changed)

    # ── building ─────────────────────────────────────────────────────

    def _build(self, choices: RowChoices | None) -> None:
        keys = [*self._pictures, *self._groups]
        if choices is not None:
            known = [key for key in choices.order if key in keys]
            keys = known + [key for key in keys if key not in known]
        # Pictures first, then bands: a band always runs under every picture row.
        keys = [k for k in keys if k in self._pictures] + [k for k in keys if k in self._groups]
        self.tree.blockSignals(True)
        for key in keys:
            if key in self._pictures:
                self._add_picture(self._pictures[key], choices)
            else:
                self._add_group(self._groups[key], choices)
        self.tree.blockSignals(False)
        self.tree.resizeColumnToContents(0)

    def _checked(self, key: str, default: bool, choices: RowChoices | None) -> Qt.CheckState:
        on = default if choices is None else key in choices.checked
        return Qt.CheckState.Checked if on else Qt.CheckState.Unchecked

    def _add_picture(self, option: PictureRowOption, choices: RowChoices | None) -> None:
        kind = tr("imaging") if option.kind == "imaging" else tr("camera")
        item = QTreeWidgetItem(self.tree, [option.label, kind])
        item.setData(0, _ROLE, option.key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, self._checked(option.key, option.checked, choices))

    def _add_group(self, option: SensorGroupOption, choices: RowChoices | None) -> None:
        item = QTreeWidgetItem(self.tree, [option.label, ""])
        item.setData(0, _ROLE, option.key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, self._checked(option.key, option.checked, choices))
        chosen = None if choices is None else choices.streams.get(option.key)
        for stream in option.streams:
            child = QTreeWidgetItem(item, [stream.label, ""])
            child.setData(0, _ROLE, stream.label)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on = chosen is None or stream.label in chosen
            child.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        stored = "auto" if choices is None else choices.layouts.get(option.key, "auto")
        box = _layout_box(self.tree, option.label, stored)
        box.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self.tree.setItemWidget(item, 1, box)
        self._layout_boxes[option.key] = box

    # ── the user's choices ───────────────────────────────────────────

    def _top_items(self) -> list[QTreeWidgetItem]:
        items = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [item for item in items if item is not None]

    @staticmethod
    def _ticked_children(item: QTreeWidgetItem) -> set[str]:
        children = (item.child(i) for i in range(item.childCount()))
        return {
            str(child.data(0, _ROLE))
            for child in children
            if child is not None and child.checkState(0) == Qt.CheckState.Checked
        }

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self.changed.emit()

    def _move(self, step: int) -> None:
        """Move the selected row within its kind: pictures stay above bands."""
        item = self.tree.currentItem()
        if item is None or item.parent() is not None:
            return
        items = self._top_items()
        index = items.index(item)
        target = index + step
        if not 0 <= target < len(items):
            return
        if (str(item.data(0, _ROLE)) in self._pictures) != (
            str(items[target].data(0, _ROLE)) in self._pictures
        ):
            return
        key = str(item.data(0, _ROLE))
        box = self._layout_boxes.get(key)
        layout_value = box.currentData() if box is not None else None
        self.tree.blockSignals(True)
        taken = self.tree.takeTopLevelItem(index)
        if taken is None:
            self.tree.blockSignals(False)
            return
        self.tree.insertTopLevelItem(target, taken)
        if key in self._groups:
            # A widget does not travel with its item; give the moved row a new one.
            self._layout_boxes.pop(key, None)
            replacement = _layout_box(self.tree, self._groups[key].label, str(layout_value))
            replacement.currentIndexChanged.connect(lambda _index: self.changed.emit())
            self.tree.setItemWidget(taken, 1, replacement)
            self._layout_boxes[key] = replacement
        self.tree.blockSignals(False)
        self.tree.setCurrentItem(taken)
        self.changed.emit()

    def check_group(self, key: str) -> None:
        """Tick a sensor group, as choosing it as the trigger channel does."""
        for item in self._top_items():
            if item.data(0, _ROLE) == key:
                item.setCheckState(0, Qt.CheckState.Checked)

    def picture_rows(self) -> list[GridRow]:
        """The ticked picture rows, in order."""
        return [
            self._pictures[str(item.data(0, _ROLE))].row
            for item in self._top_items()
            if str(item.data(0, _ROLE)) in self._pictures
            and item.checkState(0) == Qt.CheckState.Checked
        ]

    def bands(
        self, trigger: ReaderReference | None = None, threshold: float | None = None
    ) -> list[GridBand]:
        """The ticked groups as bands, with only their ticked streams.

        The trigger channel's stream, when present, carries the detection
        threshold so the band shows the level that found the events.
        """
        bands: list[GridBand] = []
        for item in self._top_items():
            key = str(item.data(0, _ROLE))
            option = self._groups.get(key)
            if option is None or item.checkState(0) != Qt.CheckState.Checked:
                continue
            ticked = self._ticked_children(item)
            streams = tuple(
                GridStream(s.reference, s.label, s.color, s.unit)
                for s in option.streams
                if s.label in ticked
            )
            if not streams:
                continue
            trigger_index = next(
                (
                    i
                    for i, s in enumerate(streams)
                    if trigger is not None
                    and (s.reference.cache_dir, s.reference.channel_id)
                    == (trigger.cache_dir, trigger.channel_id)
                ),
                None,
            )
            box = self._layout_boxes.get(key)
            bands.append(
                GridBand(
                    option.label,
                    streams,
                    threshold=threshold if trigger_index is not None else None,
                    threshold_stream=trigger_index or 0,
                    layout=str(box.currentData()) if box is not None else "auto",
                )
            )
        return bands

    def choices(self) -> RowChoices:
        """What is ticked and in what order, to start the next export from."""
        result = RowChoices()
        for item in self._top_items():
            key = str(item.data(0, _ROLE))
            result.order.append(key)
            if item.checkState(0) == Qt.CheckState.Checked:
                result.checked.add(key)
            if key in self._groups:
                result.streams[key] = self._ticked_children(item)
                box = self._layout_boxes.get(key)
                if box is not None:
                    result.layouts[key] = str(box.currentData())
        return result

    # ── how big the movie's rows will be ─────────────────────────────

    def update_estimate(self, event_count: int, high_detail: bool) -> bool:
        """Say how large each row will come out; return whether the grid fits at all."""
        rows = [
            self._pictures[str(item.data(0, _ROLE))]
            for item in self._top_items()
            if str(item.data(0, _ROLE)) in self._pictures
            and item.checkState(0) == Qt.CheckState.Checked
        ]
        if not rows:
            self.estimate.setText(tr("Tick at least one camera or imaging row."))
            return False
        try:
            layout = plan_grid(
                len(rows),
                max(1, event_count),
                1.0,
                1.0,
                high_detail=high_detail,
                cell_aspect_ratios=[row.aspect_ratio for row in rows],
                bands=self.bands(),
            )
        except ExportError as error:
            self.estimate.setText(tr("Does not fit: {reason}").format(reason=str(error)))
            return False
        parts = [
            tr("{name}: {width}×{height} px").format(
                name=row.label, width=layout.cell_width, height=height
            )
            for row, height in zip(rows, layout.cell_heights, strict=True)
        ]
        heights = zip(rows, layout.cell_heights, strict=True)
        small = [row.label for row, height in heights if height < _LEGIBLE_ROW]
        text = tr("Each event cell — ") + "; ".join(parts)
        if small:
            text += "\n" + tr("Too small to read: {rows}. Choose fewer events or rows.").format(
                rows=", ".join(small)
            )
        self.estimate.setText(text)
        return True
