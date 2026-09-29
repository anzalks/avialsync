"""Fix Identities: the braid, its two selectors, and the drag that changes one.

The plot answers "who is who, and where did that change"; this widget is what
makes it a tool rather than a picture.  Three decisions are worth stating where
the code is.

**One group and one part at a time.**  A multi-animal file with ten body parts
has sixty trajectories, and a braid of sixty lines answers nothing.  The group
selector picks what is confusable -- two animals, or a left against a right --
and the part selector picks which of their points to judge it on, with "All
parts" reading each lane's centroid because a whole-animal flip moves every
part at once.  The counts beside each part are what keep the choice from being
blind: a part with no candidates says so in the menu rather than after a click.

**The gesture is the edit.**  Dragging a lane's line onto another lane's row
says "from here on, this one is that one", which is exactly what an accepted
:class:`~avialsync.core.identity_swaps.SwapEvent` means, and it snaps to the
nearest node so the frame is the evidence's rather than the pointer's.
Dragging a line back off an accepted crossing undoes that flip instead of
stacking a second one on top of it.

**It asks; it never writes.**  Every gesture leaves on a signal and the window
puts it through the command bus, so a flip is undoable like every other
user-visible mutation (architecture rule 14).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pyqtgraph as pg
from pyqtgraph.GraphicsScene.mouseEvents import MouseClickEvent, MouseDragEvent
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.identity_groups import ANIMALS, CUSTOM, SIDES, split_group_id
from avialsync.core.identity_swaps import ALL_PARTS, SwapEvent, SwapGroup
from avialsync.ui.axis_nav import NavigableViewBox
from avialsync.ui.i18n import tr
from avialsync.ui.identity_braid import BraidModel, BraidNode, draw_braid, draw_separation
from avialsync.ui.plot_theme import apply_canvas_palette

__all__ = ["IdentityPanel", "IdentityWindow", "group_label", "ALL_PARTS_ITEM"]

#: The part selector's first entry: every part of the group at once.
ALL_PARTS_ITEM = ""

#: How near a drag has to finish to a node before it snaps to it, as a share of
#: the visible span.  Generous: the node is where the evidence is, and a frame
#: chosen by the pointer is a frame chosen by the pointer.
_SNAP_SECONDS = 0.2
_REVIEW_SECONDS = 2.0
_ROW_TOLERANCE = 0.3

#: Height the braid claims against the separation trace under it.
_BRAID_STRETCH = 3


def group_label(group_id: str) -> str:
    """The name a group is shown under.

    The id is a persisted identifier written into the sidecar beside the pose
    file, so it stays ascii and untranslated; this is the only place it becomes
    words (D-141).
    """
    kind, qualifier = split_group_id(group_id)
    if kind == ANIMALS:
        return tr("Animals")
    if kind == SIDES:
        if qualifier:
            return tr("Left / Right — {individual}").format(individual=qualifier)
        return tr("Left / Right")
    if kind == CUSTOM:
        return qualifier
    return group_id


class _BraidViewBox(NavigableViewBox):
    """The braid's view box: a drag across rows is an edit, not a pan."""

    #: ``(start x, start y, end x, end y)`` in view coordinates.
    dragged = Signal(float, float, float, float)
    dragging = Signal(float, float, float, float)
    clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self._start: tuple[float, float] | None = None

    def mouseDragEvent(self, event: MouseDragEvent, axis: int | None = None) -> None:
        """Turn a drag into a request, and never into a pan of the rows."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDragEvent(event, axis)
            return
        event.accept()
        start = self.mapSceneToView(event.buttonDownScenePos())
        here = self.mapSceneToView(event.scenePos())
        if event.isFinish() and self._start is not None:
            self.dragged.emit(start.x(), start.y(), here.x(), here.y())
            self._start = None
            return
        self._start = (start.x(), start.y())
        self.dragging.emit(start.x(), start.y(), here.x(), here.y())

    def mouseClickEvent(self, event: MouseClickEvent) -> None:
        """A click on the braid seeks there, like every other evidence plot."""
        position = self.mapSceneToView(event.scenePos())
        self.clicked.emit(position.x(), position.y())
        event.accept()


class IdentityPanel(QWidget):
    """Where a tracker's lost identities are found and put back."""

    #: A flip the user is asking to accept.
    swap_requested = Signal(object)
    #: An accepted flip the user is asking to undo, by dragging it back.
    undo_requested = Signal(object)
    #: Master time to go to, from a click on the braid.
    seek_requested = Signal(float)
    #: ``(group id, part)`` -- what to scan, when the user asks.
    detect_requested = Signal(str, str)
    new_group_requested = Signal()
    #: The selected crossing's short review span on the master timeline.
    play_region_requested = Signal(float, float)
    #: ``(group id, part)`` -- what the selectors now show.
    selection_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups: tuple[SwapGroup, ...] = ()
        self._model: BraidModel | None = None
        self._source_id = ""
        self._selected_index: int | None = None
        self._restore_selection: tuple[int, tuple[str, str]] | None = None
        self._selection_line: pg.InfiniteLine | None = None
        self._drag_ghost: pg.PlotDataItem | None = None
        self._video_available = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(self._build_controls())
        instruction = QLabel(
            tr("Choose a crossing below, or drag a lane line onto another row at its time."), self
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        self._braid = pg.PlotWidget(viewBox=_BraidViewBox())
        self._braid.setMenuEnabled(False)
        self._braid.getPlotItem().hideButtons()
        self._braid.setAccessibleName(tr("Identity braid"))
        self._braid.setLabel("left", tr("Identity"))
        layout.addWidget(self._braid, _BRAID_STRETCH)

        self._separation = pg.PlotWidget()
        self._separation.setMenuEnabled(False)
        self._separation.getPlotItem().hideButtons()
        self._separation.setAccessibleName(tr("Separation between the two lanes"))
        self._separation.setLabel("left", tr("Apart (px)"))
        self._separation.setLabel("bottom", tr("Master time (s)"))
        self._separation.setXLink(self._braid)
        layout.addWidget(self._separation, 1)

        layout.addLayout(self._build_review_controls())

        self._evidence = QLabel(self)
        self._evidence.setWordWrap(True)
        layout.addWidget(self._evidence)

        box = self._braid.getPlotItem().getViewBox()
        box.dragged.connect(self._on_dragged)
        box.dragging.connect(self._on_dragging)
        box.clicked.connect(self._on_clicked)
        self._apply_palette()
        self._set_empty(tr("Import a tracking file with more than one identity."))

    # ── the controls ─────────────────────────────────────────────────

    def _build_controls(self) -> QVBoxLayout:
        controls = QVBoxLayout()
        self._group_box = QComboBox(self)
        self._group_box.setAccessibleName(tr("Identity group"))
        self._group_box.setAccessibleDescription(tr("Choose labels that may have exchanged"))
        self._group_box.setToolTip(tr("Which labels this tracker could confuse"))
        self._group_box.currentIndexChanged.connect(self._on_group_changed)
        self._new_group = QPushButton(tr("New group…"), self)
        self._new_group.setAccessibleName(tr("Create an identity group"))
        self._new_group.setAccessibleDescription(tr("Map other pose columns into two lanes"))
        self._new_group.setToolTip(tr("Pair other pose point labels as two identity lanes"))
        self._new_group.clicked.connect(self.new_group_requested)

        self._part_box = QComboBox(self)
        self._part_box.setAccessibleName(tr("Body part"))
        self._part_box.setAccessibleDescription(tr("Choose one part or the whole group"))
        self._part_box.setToolTip(tr("Which point to judge the identities on"))
        self._part_box.currentIndexChanged.connect(self._on_part_changed)

        self._detect = QPushButton(tr("Find swaps"), self)
        self._detect.setAccessibleName(tr("Find identity swaps"))
        self._detect.setToolTip(
            tr("Propose frames where the tracker may have exchanged these labels")
        )
        self._detect.clicked.connect(
            lambda: self.detect_requested.emit(self.group_id(), self.part())
        )

        for box in (self._group_box, self._part_box):
            box.setMinimumContentsLength(12)
            box.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        group_row = QHBoxLayout()
        group_row.addWidget(QLabel(tr("Group"), self))
        group_row.addWidget(self._group_box, 1)
        group_row.addWidget(self._new_group)
        controls.addLayout(group_row)
        part_row = QHBoxLayout()
        part_row.addWidget(QLabel(tr("Part"), self))
        part_row.addWidget(self._part_box, 1)
        part_row.addWidget(self._detect)
        controls.addLayout(part_row)
        return controls

    def _build_review_controls(self) -> QVBoxLayout:
        controls = QVBoxLayout()
        crossing_row = QHBoxLayout()
        crossing_row.addWidget(QLabel(tr("Crossing"), self))
        self._node_box = QComboBox(self)
        self._node_box.setAccessibleName(tr("Crossing to review"))
        self._node_box.setAccessibleDescription(
            tr("Choose a candidate or accepted swap; choosing seeks the main video")
        )
        self._node_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._node_box.currentIndexChanged.connect(self._on_node_changed)
        crossing_row.addWidget(self._node_box, 1)
        self._fit = QPushButton(tr("Show all"), self)
        self._fit.setAccessibleName(tr("Show the whole identity recording"))
        self._fit.setAccessibleDescription(tr("Reset the braid time range to the full recording"))
        self._fit.clicked.connect(self._fit_all)
        crossing_row.addWidget(self._fit)
        controls.addLayout(crossing_row)

        review = QHBoxLayout()
        self._back = QPushButton(tr("−1 frame"), self)
        self._back.setAccessibleName(tr("Move proposed swap one frame earlier"))
        self._back.setAccessibleDescription(
            tr("Change the proposed swap frame without applying it")
        )
        self._back.clicked.connect(lambda: self._nudge(-1))
        self._forward = QPushButton(tr("+1 frame"), self)
        self._forward.setAccessibleName(tr("Move proposed swap one frame later"))
        self._forward.setAccessibleDescription(
            tr("Change the proposed swap frame without applying it")
        )
        self._forward.clicked.connect(lambda: self._nudge(1))
        self._play = QPushButton(tr("Play ±2 s"), self)
        self._play.setAccessibleName(tr("Play two seconds around the selected crossing"))
        self._play.setAccessibleDescription(
            tr("Loop the shared video and master clock around this crossing")
        )
        self._play.clicked.connect(self._play_selection)
        self._apply = QPushButton(tr("Apply swap"), self)
        self._apply.setAccessibleName(tr("Accept the selected identity swap"))
        self._apply.setAccessibleDescription(
            tr("Route the two selected identities from this frame onward")
        )
        self._apply.clicked.connect(self._apply_selection)
        self._remove = QPushButton(tr("Remove swap"), self)
        self._remove.setAccessibleName(tr("Remove the selected accepted identity swap"))
        self._remove.setAccessibleDescription(tr("Restore the routing before this accepted event"))
        self._remove.clicked.connect(self._remove_selection)
        for button in (self._back, self._forward, self._play):
            review.addWidget(button)
        controls.addLayout(review)
        edits = QHBoxLayout()
        edits.addWidget(self._apply)
        edits.addWidget(self._remove)
        controls.addLayout(edits)
        self._update_actions()
        return controls

    def set_groups(
        self,
        source_id: str,
        groups: Sequence[SwapGroup],
        counts: Mapping[tuple[str, str], tuple[int, int]] | None = None,
    ) -> None:
        """Offer *groups* for *source_id*, with per-part candidate counts.

        *counts* maps ``(group id, part)`` to ``(candidates, accepted)``, which
        the part menu shows beside each name so choosing one is not blind.
        """
        self._source_id = source_id
        self._groups = tuple(groups)
        self._counts = dict(counts or {})
        with _quiet(self._group_box):
            self._group_box.clear()
            for group in self._groups:
                self._group_box.addItem(group_label(group.name), group.name)
        self._refresh_parts()
        if not self._groups:
            # Not a dead end: this is the recording that needs New group most.
            # Nothing in its names says which two points a tracker confuses, so
            # the person who knows says it.
            self._set_empty(
                tr(
                    "Nothing in this recording's point names says which two a tracker "
                    "could confuse. Use New group… to pair the two yourself."
                )
            )

    def set_counts(self, counts: Mapping[tuple[str, str], tuple[int, int]]) -> None:
        """Update candidate counts without losing the selected group or part."""
        selected = self.part()
        self._counts = dict(counts)
        self._refresh_parts()
        index = self._part_box.findData(selected)
        with _quiet(self._part_box):
            self._part_box.setCurrentIndex(max(0, index))

    def _refresh_parts(self) -> None:
        group = self.group()
        with _quiet(self._part_box):
            self._part_box.clear()
            if group is None:
                return
            self._part_box.addItem(self._part_text(group.name, ALL_PARTS_ITEM), ALL_PARTS_ITEM)
            for part in group.parts:
                self._part_box.addItem(self._part_text(group.name, part), part)
            for index in range(self._part_box.count()):
                self._part_box.setItemData(
                    index, self._part_box.itemText(index), Qt.ItemDataRole.ToolTipRole
                )

    def _part_text(self, group_id: str, part: str) -> str:
        name = tr("All parts") if part == ALL_PARTS_ITEM else part
        candidates, accepted = self._counts.get((group_id, part), (0, 0))
        if not candidates and not accepted:
            return name
        return tr("{name} — {candidates} candidate(s), {accepted} accepted").format(
            name=name, candidates=candidates, accepted=accepted
        )

    # ── what is selected ─────────────────────────────────────────────

    def source_id(self) -> str:
        return self._source_id

    def group_id(self) -> str:
        data = self._group_box.currentData()
        return str(data) if data is not None else ""

    def group(self) -> SwapGroup | None:
        return next((g for g in self._groups if g.name == self.group_id()), None)

    def group_ids(self) -> tuple[str, ...]:
        """The declarations currently offered in the selector."""
        return tuple(group.name for group in self._groups)

    def select_group(self, name: str) -> None:
        """Select a newly declared group by its persisted identifier."""
        index = self._group_box.findData(name)
        if index >= 0:
            self._group_box.setCurrentIndex(index)

    def part(self) -> str:
        data = self._part_box.currentData()
        return str(data) if data is not None else ALL_PARTS_ITEM

    def _on_group_changed(self, _index: int) -> None:
        self._refresh_parts()
        self.selection_changed.emit(self.group_id(), self.part())

    def _on_part_changed(self, _index: int) -> None:
        self.selection_changed.emit(self.group_id(), self.part())

    # ── drawing ──────────────────────────────────────────────────────

    def show_model(self, model: BraidModel) -> None:
        """Draw one group and part, and say what the plot is showing."""
        previous = self._selected_node()
        previous_key = self._restore_selection or (
            (self._selected_index, previous.lanes) if previous is not None else None
        )
        self._restore_selection = None
        self._model = model
        palette = self.palette()
        draw_braid(self._braid.getPlotItem(), model, palette)
        draw_separation(self._separation.getPlotItem(), model, palette)
        self._selection_line = None
        self._drag_ghost = None
        with _quiet(self._node_box):
            self._node_box.clear()
            for node in model.nodes:
                self._node_box.addItem(self._node_text(node, node.index), node)
            chosen = next(
                (
                    index
                    for index, node in enumerate(model.nodes)
                    if (node.index, node.lanes) == previous_key
                ),
                0,
            )
            self._node_box.setCurrentIndex(chosen if model.nodes else -1)
        selected = self._selected_node()
        self._selected_index = selected.index if selected is not None else None
        self._evidence.setText(self.describe())
        self._evidence.setAccessibleDescription(self.describe())
        self._show_selection(focus=False, seek=False)

    def set_loading(self) -> None:
        """Keep old evidence from being edited while a newer slice is read."""
        node = self._selected_node()
        if node is not None and self._selected_index is not None:
            self._restore_selection = (self._selected_index, node.lanes)
        self._set_empty(tr("Loading identity evidence…"))

    def set_video_available(self, available: bool) -> None:
        """Disable review playback when there is no video to review."""
        self._video_available = available
        self._update_actions()

    def _set_empty(self, message: str) -> None:
        self._model = None
        self._selected_index = None
        self._selection_line = None
        self._drag_ghost = None
        self._braid.getPlotItem().clear()
        self._separation.getPlotItem().clear()
        with _quiet(self._node_box):
            self._node_box.clear()
        self._evidence.setText(message)
        self._update_actions()

    def changeEvent(self, event: QEvent) -> None:
        """Re-theme: pyqtgraph canvases do not receive a palette change."""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._apply_palette()
            if self._model is not None:
                self.show_model(self._model)

    def _apply_palette(self) -> None:
        apply_canvas_palette(self._braid, self.palette())
        apply_canvas_palette(self._separation, self.palette())

    def describe(self) -> str:
        """What the braid shows, in words, for a reader who cannot see it.

        A plot is invisible to a screen reader and the crossings on it are the
        whole content, so this is the content rather than a caption (rule 17).
        """
        model = self._model
        if model is None or not model.lanes:
            return self._evidence.text()
        accepted = [node for node in model.nodes if node.accepted]
        candidates = [node for node in model.nodes if not node.accepted]
        lanes = tr(" and ").join(model.lanes)
        return tr(
            "{lanes}: {accepted} accepted swap(s), {candidates} candidate(s). "
            "Drag a line onto another row to swap the identities from there on."
        ).format(lanes=lanes, accepted=len(accepted), candidates=len(candidates))

    # ── the gesture ──────────────────────────────────────────────────

    def _on_clicked(self, x: float, _y: float) -> None:
        model = self._model
        if model is None:
            return
        node = model.nearest_node(x, self._tolerance())
        if node is not None:
            for index in range(self._node_box.count()):
                if self._node_box.itemData(index) == node:
                    if self._node_box.currentIndex() == index:
                        self._show_selection(focus=True, seek=True)
                    else:
                        self._node_box.setCurrentIndex(index)
                    break
            return
        self.seek_requested.emit(x)

    def _on_node_changed(self, _index: int) -> None:
        node = self._selected_node()
        self._selected_index = node.index if node is not None else None
        self._show_selection(focus=True, seek=True)

    def _selected_node(self) -> BraidNode | None:
        node = self._node_box.currentData()
        return node if isinstance(node, BraidNode) else None

    def _frame_of(self, index: int) -> int:
        model = self._model
        if (
            model is not None
            and model.frame_numbers is not None
            and index < len(model.frame_numbers)
        ):
            return int(model.frame_numbers[index])
        return index

    def _node_text(self, node: BraidNode, index: int) -> str:
        kind = tr("accepted") if node.accepted else tr("candidate")
        frame = self._frame_of(index)
        return tr("Frame {frame}: {a} ↔ {b} ({kind})").format(
            frame=frame, a=node.lanes[0], b=node.lanes[1], kind=kind
        )

    def _show_selection(self, *, focus: bool, seek: bool) -> None:
        model = self._model
        node = self._selected_node()
        if model is None or node is None or self._selected_index is None or not len(model.times):
            self._update_actions()
            return
        at = float(model.times[self._selected_index])
        plot = self._braid.getPlotItem()
        if self._selection_line is not None:
            plot.removeItem(self._selection_line)
        self._selection_line = pg.InfiniteLine(
            pos=at,
            angle=90,
            movable=False,
            pen=pg.mkPen(self.palette().text().color(), style=Qt.PenStyle.DashLine),
        )
        plot.addItem(self._selection_line)
        if focus:
            low, high = model.span()
            plot.setXRange(max(low, at - 5.0), min(high, at + 5.0), padding=0)
        if seek:
            self.seek_requested.emit(at)
        self._node_box.setItemText(
            self._node_box.currentIndex(), self._node_text(node, self._selected_index)
        )
        detail = node.detail or self.describe()
        if self._selected_index != node.index:
            detail = tr("Proposed swap moved to frame {frame}. Original evidence: {detail}").format(
                frame=self._frame_of(self._selected_index), detail=detail
            )
        self._evidence.setText(detail)
        self._update_actions()

    def _update_actions(self) -> None:
        node = self._selected_node() if hasattr(self, "_node_box") else None
        model = self._model
        proposed = node is not None and not node.accepted and model is not None
        if hasattr(self, "_back"):
            index = self._selected_index
            self._back.setEnabled(bool(proposed and index is not None and index > 0))
            self._forward.setEnabled(
                bool(
                    proposed
                    and index is not None
                    and model is not None
                    and index < len(model.times) - 1
                )
            )
            self._play.setEnabled(node is not None and self._video_available)
            self._play.setToolTip(
                tr("Select a crossing and load a video to review it")
                if not self._play.isEnabled()
                else tr("Loop two seconds before and after this crossing in the main video")
            )
            self._apply.setEnabled(proposed)
            self._remove.setEnabled(node is not None and node.accepted)

    def _nudge(self, step: int) -> None:
        model = self._model
        if model is None or self._selected_index is None:
            return
        self._selected_index = max(0, min(len(model.times) - 1, self._selected_index + step))
        self._show_selection(focus=True, seek=True)

    def _play_selection(self) -> None:
        model = self._model
        if model is None or self._selected_index is None or not self._video_available:
            return
        at = float(model.times[self._selected_index])
        low, high = model.span()
        self.play_region_requested.emit(
            max(low, at - _REVIEW_SECONDS), min(high, at + _REVIEW_SECONDS)
        )

    def _selected_event(self) -> SwapEvent | None:
        node = self._selected_node()
        if node is None or self._selected_index is None:
            return None
        parts = ALL_PARTS if self.part() == ALL_PARTS_ITEM else (self.part(),)
        return SwapEvent(
            index=self._selected_index, group=self.group_id(), lanes=node.lanes, parts=parts
        )

    def _apply_selection(self) -> None:
        node = self._selected_node()
        event = self._selected_event()
        if node is not None and not node.accepted and event is not None:
            self.swap_requested.emit(event)

    def _remove_selection(self) -> None:
        node = self._selected_node()
        event = self._selected_event()
        if node is not None and node.accepted and event is not None:
            self.undo_requested.emit(event)

    def _fit_all(self) -> None:
        if self._model is not None:
            self._braid.getPlotItem().setXRange(*self._model.span(), padding=0.01)

    def _on_dragged(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        """Turn "this line belongs on that row" into a flip, or into its undo."""
        if self._drag_ghost is not None:
            self._braid.getPlotItem().removeItem(self._drag_ghost)
            self._drag_ghost = None
        model = self._model
        group = self.group()
        if model is None or group is None:
            return
        held = model.lane_at(start_y)
        target = model.lane_at(end_y)
        if (
            held is None
            or target is None
            or held == target
            or abs(model.row(held) - start_y) > _ROW_TOLERANCE
            or abs(model.row(target) - end_y) > _ROW_TOLERANCE
        ):
            return

        node = model.nearest_node(start_x, self._tolerance()) or model.nearest_node(
            end_x, self._tolerance()
        )
        index = node.index if node is not None else model.index_at(start_x)
        lanes = (held, target)
        parts = ALL_PARTS if self.part() == ALL_PARTS_ITEM else (self.part(),)
        event = SwapEvent(index=index, group=group.name, lanes=lanes, parts=parts)

        if node is not None and node.accepted and set(node.lanes) == set(lanes):
            # Dragged back off a crossing: the user is undoing that flip, not
            # asking for a second one that happens to compose to the same thing.
            self.undo_requested.emit(event)
            return
        self.swap_requested.emit(event)

    def _on_dragging(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        """Show the proposed connection without mutating the recording."""
        model = self._model
        if model is None:
            return
        held = model.lane_at(start_y)
        if held is None or abs(model.row(held) - start_y) > _ROW_TOLERANCE:
            return
        if self._drag_ghost is None:
            self._drag_ghost = self._braid.getPlotItem().plot(
                pen=pg.mkPen(self.palette().text().color(), width=2, style=Qt.PenStyle.DashLine)
            )
        self._drag_ghost.setData([start_x, end_x], [model.row(held), end_y])

    def _tolerance(self) -> float:
        model = self._model
        if model is None:
            return 0.0
        if len(model.times) < 2:
            return _SNAP_SECONDS
        step = abs(float(model.times[1] - model.times[0]))
        return max(min(3.1 * step, _SNAP_SECONDS), 1e-9)

    def nodes(self) -> tuple[BraidNode, ...]:
        """What the plot is currently offering, for tests and for the window."""
        return self._model.nodes if self._model is not None else ()


class IdentityWindow(QDockWidget):
    """A closable identity editor beside the video, floatable to another screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Fix Identities"))
        self.setObjectName("fix_identities_dock")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.panel = IdentityPanel(self)
        self.setWidget(self.panel)


class _quiet:
    """Block a combo box's signals while it is rebuilt."""

    def __init__(self, box: QComboBox) -> None:
        self._box = box

    def __enter__(self) -> QComboBox:
        self._box.blockSignals(True)
        return self._box

    def __exit__(self, *_exception: object) -> None:
        self._box.blockSignals(False)
