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
from PySide6.QtGui import QKeySequence
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
from avialsync.ui.theme import set_bold

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
    #: Accept a swap where the review is: the selected crossing when there is
    #: one, and otherwise wherever the master clock has got to.
    apply_requested = Signal()
    #: Undo the accepted swap in force where the video is.
    remove_requested = Signal()
    #: Undo every accepted swap on this tracking file, in one step.
    remove_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups: tuple[SwapGroup, ...] = ()
        self._model: BraidModel | None = None
        self._source_id = ""
        self._swap_count = 0
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
        # Rows are identities, not a measurement: there is nothing to see by
        # zooming them, and a stray wheel that scrolled the lanes off the top
        # left no way back. Time is the only axis worth navigating here.
        self._braid.setMouseEnabled(x=True, y=False)
        self._braid.setAccessibleName(tr("Identity braid"))
        self._braid.setLabel("left", tr("Identity"))
        layout.addWidget(self._braid, _BRAID_STRETCH)

        self._separation = pg.PlotWidget(viewBox=_BraidViewBox())
        self._separation.setMenuEnabled(False)
        self._separation.getPlotItem().hideButtons()
        self._separation.setMouseEnabled(x=True, y=False)
        self._separation.setAccessibleName(tr("Separation between the two lanes"))
        self._separation.setLabel("left", tr("Apart (px)"))
        self._separation.setLabel("bottom", tr("Master time (s)"))
        self._separation.setXLink(self._braid)
        layout.addWidget(self._separation, 1)

        layout.addLayout(self._build_review_controls())

        self._evidence = QLabel(self)
        self._evidence.setWordWrap(True)
        layout.addWidget(self._evidence)

        # Clicking the separation trace seeks as clicking the braid does: it
        # is the same time axis, and the closest approach is exactly the moment
        # a reviewer wants to see in the video.
        self._separation.getPlotItem().getViewBox().clicked.connect(
            lambda x, _y: self.seek_requested.emit(x)
        )
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
        self._pair_box = QComboBox(self)
        self._pair_box.setAccessibleName(tr("Identities to compare"))
        self._pair_box.setAccessibleDescription(
            tr("Which two of this group's identities the braid compares and a swap exchanges")
        )
        self._pair_box.setToolTip(tr("Which two identities to compare"))
        self._pair_box.currentIndexChanged.connect(self._on_part_changed)
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
        self._pair_label = QLabel(tr("Compare"), self)
        group_row.addWidget(self._pair_label)
        group_row.addWidget(self._pair_box, 1)
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
            tr(
                "Route the two identities from the selected crossing, or from where "
                "the video is now when no crossing is selected"
            )
        )
        self._apply.setToolTip(
            tr("Swap these two from here on — watch the video and press it (Ctrl+Shift+S)")
        )
        self._apply.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._apply.clicked.connect(self.apply_requested)
        self._remove = QPushButton(tr("Remove swap"), self)
        self._remove.setAccessibleName(tr("Remove the selected accepted identity swap"))
        self._remove.setAccessibleDescription(tr("Restore the routing before this accepted event"))
        self._remove.setToolTip(
            tr("Reverse the swap in force at the playhead, putting the identities back")
        )
        self._remove.clicked.connect(self.remove_requested)
        self._remove_all = QPushButton(tr("Remove all swaps"), self)
        self._remove_all.setAccessibleName(tr("Remove every accepted swap on this file"))
        self._remove_all.setAccessibleDescription(
            tr("Restore every identity in this tracking file to what the model predicted")
        )
        self._remove_all.clicked.connect(self.remove_all_requested)
        for button in (self._back, self._forward, self._play):
            review.addWidget(button)
        controls.addLayout(review)
        edits = QHBoxLayout()
        edits.addWidget(self._apply)
        edits.addWidget(self._remove)
        edits.addWidget(self._remove_all)
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

    def set_swap_count(self, count: int) -> None:
        """Say how many accepted swaps this whole file holds.

        On the button, because *Remove all* clears the file rather than the
        group and part on screen, and a button that says how much it will
        remove is the difference between a shortcut and a surprise.
        """
        self._swap_count = int(count)
        self._remove_all.setEnabled(self._swap_count > 0)
        self._remove_all.setText(
            tr("Remove all swaps ({n})").format(n=self._swap_count)
            if self._swap_count
            else tr("Remove all swaps")
        )
        self._remove_all.setToolTip(
            tr("Remove every accepted swap on this tracking file, in one undoable step")
        )

    def set_counts(self, counts: Mapping[tuple[str, str], tuple[int, int]]) -> None:
        """Update candidate counts without losing the selected group or part."""
        selected = self.part()
        self._counts = dict(counts)
        self._refresh_parts()
        index = self._part_box.findData(selected)
        with _quiet(self._part_box):
            self._part_box.setCurrentIndex(max(0, index))

    def _refresh_pairs(self) -> None:
        """Offer every pair of lanes, or hide the choice when there is none.

        Two lanes is one pair and no decision; three animals is three pairs,
        and picking "the first two" for the person is a guess dressed as an
        answer. The row appears only when the group has something to choose.
        """
        group = self.group()
        lanes = group.lanes if group is not None else ()
        with _quiet(self._pair_box):
            self._pair_box.clear()
            for first in range(len(lanes)):
                for second in range(first + 1, len(lanes)):
                    self._pair_box.addItem(
                        tr("{a} and {b}").format(a=lanes[first], b=lanes[second]),
                        [lanes[first], lanes[second]],
                    )
            self._pair_box.setCurrentIndex(0 if self._pair_box.count() else -1)
        visible = self._pair_box.count() > 1
        self._pair_box.setVisible(visible)
        self._pair_label.setVisible(visible)

    def pair(self) -> tuple[str, str] | None:
        """The two lanes being compared, or None when the group has fewer."""
        data = self._pair_box.currentData()
        if not data or len(data) != 2:
            return None
        return (str(data[0]), str(data[1]))

    def _refresh_parts(self) -> None:
        self._refresh_pairs()
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

    def _bound_navigation(self, model: BraidModel) -> None:
        """Stop either plot from being scrolled or zoomed off its own data.

        Without limits a wheel notch could leave both plots showing empty space
        with nothing on screen to say where the recording went. Bounded, the
        worst a gesture can do is show all of it -- and *Show all* is still
        there for the one press that undoes any amount of exploring.
        """
        low, high = model.span()
        if high <= low:
            return
        margin = (high - low) * 0.02
        for plot in (self._braid, self._separation):
            plot.getPlotItem().getViewBox().setLimits(
                xMin=low - margin, xMax=high + margin, minXRange=(high - low) * 1e-4
            )

    def show_model(self, model: BraidModel) -> None:
        """Draw one group and part, and say what the plot is showing."""
        previous = self._selected_node()
        previous_key = self._restore_selection or (
            (self._selected_index, previous.lanes) if previous is not None else None
        )
        self._restore_selection = None
        self._model = model
        palette = self.palette()
        draw_braid(self._braid.getPlotItem(), model, palette, self._select_node)
        draw_separation(self._separation.getPlotItem(), model, palette)
        self._bound_navigation(model)
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

    def _select_node(self, node: BraidNode) -> None:
        """Review the crossing a click landed on, and take the video there."""
        for index in range(self._node_box.count()):
            if self._node_box.itemData(index) == node:
                if self._node_box.currentIndex() == index:
                    self._show_selection(focus=True, seek=True)
                else:
                    self._node_box.setCurrentIndex(index)
                return
        self.seek_requested.emit(node.at)

    def _on_clicked(self, x: float, _y: float) -> None:
        model = self._model
        if model is None:
            return
        node = model.nearest_node(x, self._tolerance())
        if node is not None:
            self._select_node(node)
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
            self._bring_into_view(at)
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

    def _bring_into_view(self, at: float) -> None:
        """Pan to *at* only when it is off screen, keeping the zoom as it was.

        Re-framing on every selection is what made clicking a crossing feel
        like the plot had thrown the recording away: it jumped to a five-second
        window around the node whether or not the node was already visible, and
        the way back was a button the person had not needed until then.
        """
        model = self._model
        if model is None:
            return
        view = self._braid.getPlotItem().getViewBox()
        (low, high), _ = view.viewRange()
        if low <= at <= high:
            return
        half = (high - low) / 2.0
        span_low, span_high = model.span()
        start = max(span_low, min(at - half, span_high - 2 * half))
        view.setXRange(start, start + 2 * half, padding=0)

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
            # Never conditional on the list. Applying means "swap these two
            # from where the video is", and the video is always somewhere: a
            # swap accepted at frame 7 left the button greyed at frame 8,
            # because the crossing it had just created was the selected row.
            self._apply.setEnabled(model is not None and model.pair is not None)
            # Symmetric with Apply: it acts where the video is, so it is
            # offered whenever this view holds a swap that could be in force
            # there -- not only when the list happens to have one selected.
            self._remove.setEnabled(
                model is not None and any(candidate.accepted for candidate in model.nodes)
            )

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

    def event_at(self, index: int, lanes: tuple[str, str] | None = None) -> SwapEvent | None:
        """The swap that accepting *index* would mean, in what is on screen.

        One place decides what a frame means -- the drag, the reviewed row and
        the playhead all come here -- so the three gestures cannot disagree
        about which lanes moved or which parts went with them.
        """
        model = self._model
        group = self.group()
        pair = lanes or self.pair() or (model.pair if model is not None else None)
        if pair is None and group is not None and len(group.lanes) >= 2:
            # A rebuild clears the braid, and an apply during one still means
            # the group on screen. The model's pair and the group's first two
            # lanes are the same thing; this is the one that survives a redraw.
            pair = (group.lanes[0], group.lanes[1])
        if pair is None or group is None:
            return None
        parts = ALL_PARTS if self.part() == ALL_PARTS_ITEM else (self.part(),)
        bounded = int(index)
        if model is not None and len(model.times):
            bounded = max(0, min(bounded, len(model.times) - 1))
        return SwapEvent(index=max(0, bounded), group=group.name, lanes=pair, parts=parts)

    def selected_index(self) -> int | None:
        """Deprecated shape kept out of the apply path deliberately.

        Every way of choosing a crossing -- clicking it on the braid, picking
        it from the list, nudging it a frame -- seeks the video to it, so the
        playhead *is* the frame under review. Applying reads the clock and
        nothing else, which is why a swap lands on the frame the person is
        looking at whether they reviewed a proposal or just watched one happen.
        """
        node = self._selected_node()
        return self._selected_index if node is not None and not node.accepted else None

    def index_at(self, at: float) -> int | None:
        """The sample index master time *at* falls on, or None with no braid."""
        model = self._model
        return model.index_at(at) if model is not None and len(model.times) else None

    def _selected_event(self) -> SwapEvent | None:
        node = self._selected_node()
        if node is None or self._selected_index is None:
            return None
        # An accepted crossing names its own scope. Rebuilding it from the part
        # selector meant asking to remove a wrist swap and removing the
        # whole-animal one accepted at the same frame -- which reads, correctly
        # from where the user sits, as "it removed everything".
        parts = (
            node.parts
            if node.accepted
            else (ALL_PARTS if self.part() == ALL_PARTS_ITEM else (self.part(),))
        )
        return SwapEvent(
            index=node.index if node.accepted else self._selected_index,
            group=self.group_id(),
            lanes=node.lanes,
            parts=parts,
        )

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
            # Not a swap: it stayed in one lane, or it began or ended away from
            # a lane line. It is still a gesture at a time, so it seeks there.
            # pyqtgraph delivers a press that moves one pixel as a drag rather
            # than a click, so returning here is what made the braid look like
            # it ignored clicks entirely while the trace beneath it did not.
            self._on_clicked(end_x, end_y)
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


class _DockTitleBar(QWidget):
    """A dock's own title row: what it is, and the two things you can do to it.

    Qt's stock title bar carries a float button drawn as a pair of overlapping
    squares, which says nothing about what it does and looks the same whichever
    state it is in. The way back from a detached panel belongs *on the panel*,
    named, rather than on the main window -- where it is of no use to somebody
    looking at the panel, and of no use at all if the panel is on another
    screen.
    """

    def __init__(self, dock: QDockWidget) -> None:
        super().__init__(dock)
        self._dock = dock
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 4, 2)
        row.setSpacing(4)

        title = QLabel(dock.windowTitle(), self)
        set_bold(title, True)
        row.addWidget(title)
        row.addStretch(1)

        self._attach = QPushButton(self)
        self._attach.setFlat(True)
        self._attach.clicked.connect(self._toggle_floating)
        row.addWidget(self._attach)

        close = QPushButton(tr("Close"), self)
        close.setFlat(True)
        close.setAccessibleName(tr("Close this panel"))
        close.setAccessibleDescription(tr("Hide the panel; reopen it from the Edit menu"))
        close.setToolTip(tr("Close this panel"))
        close.clicked.connect(dock.close)
        row.addWidget(close)

        dock.topLevelChanged.connect(lambda _floating: self._describe())
        self._describe()

    def _toggle_floating(self) -> None:
        self._dock.setFloating(not self._dock.isFloating())

    def _describe(self) -> None:
        """Name the button for what pressing it does, not for what it is."""
        floating = self._dock.isFloating()
        self._attach.setText(tr("Attach") if floating else tr("Detach"))
        self._attach.setAccessibleName(
            tr("Attach this panel to the main window")
            if floating
            else tr("Detach this panel into its own window")
        )
        self._attach.setToolTip(self._attach.accessibleName())


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
        self.title_bar = _DockTitleBar(self)
        self.setTitleBarWidget(self.title_bar)
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
