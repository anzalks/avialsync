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
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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
_SNAP = 0.02

#: Height the braid claims against the separation trace under it.
_BRAID_STRETCH = 3


def group_label(group_id: str) -> str:
    """The name a group is shown under.

    The id is a persisted identifier written into the sidecar beside the pose
    file, so it stays ascii and untranslated; this is the only place it becomes
    words (D-141).
    """
    if group_id == "animals":
        return tr("Animals")
    if group_id == "sides":
        return tr("Left / Right")
    if group_id.startswith("sides:"):
        return tr("Left / Right — {individual}").format(individual=group_id.split(":", 1)[1])
    return group_id


class _BraidViewBox(NavigableViewBox):
    """The braid's view box: a drag across rows is an edit, not a pan."""

    #: ``(start x, start y, end x, end y)`` in view coordinates.
    dragged = Signal(float, float, float, float)
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
    #: ``(group id, part)`` -- what the selectors now show.
    selection_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups: tuple[SwapGroup, ...] = ()
        self._model: BraidModel | None = None
        self._source_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(self._build_controls())

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

        self._evidence = QLabel(self)
        self._evidence.setWordWrap(True)
        layout.addWidget(self._evidence)

        box = self._braid.getPlotItem().getViewBox()
        box.dragged.connect(self._on_dragged)
        box.clicked.connect(self._on_clicked)
        self._apply_palette()
        self._set_empty(tr("Import a tracking file with more than one identity."))

    # ── the controls ─────────────────────────────────────────────────

    def _build_controls(self) -> QHBoxLayout:
        controls = QHBoxLayout()
        self._group_box = QComboBox(self)
        self._group_box.setAccessibleName(tr("Identity group"))
        self._group_box.setToolTip(tr("Which labels this tracker could confuse"))
        self._group_box.currentIndexChanged.connect(self._on_group_changed)

        self._part_box = QComboBox(self)
        self._part_box.setAccessibleName(tr("Body part"))
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

        controls.addWidget(QLabel(tr("Group"), self))
        controls.addWidget(self._group_box, 1)
        controls.addWidget(QLabel(tr("Part"), self))
        controls.addWidget(self._part_box, 1)
        controls.addWidget(self._detect)
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
            self._set_empty(tr("This recording has no labels that could be confused."))

    def _refresh_parts(self) -> None:
        group = self.group()
        with _quiet(self._part_box):
            self._part_box.clear()
            if group is None:
                return
            self._part_box.addItem(self._part_text(group.name, ALL_PARTS_ITEM), ALL_PARTS_ITEM)
            for part in group.parts:
                self._part_box.addItem(self._part_text(group.name, part), part)

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
        self._model = model
        palette = self.palette()
        draw_braid(self._braid.getPlotItem(), model, palette)
        draw_separation(self._separation.getPlotItem(), model, palette)
        self._evidence.setText(self.describe())
        self._evidence.setAccessibleDescription(self.describe())

    def _set_empty(self, message: str) -> None:
        self._model = None
        self._braid.getPlotItem().clear()
        self._separation.getPlotItem().clear()
        self._evidence.setText(message)

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
            self._evidence.setText(node.detail or self.describe())
            self.seek_requested.emit(node.at)
            return
        self.seek_requested.emit(x)

    def _on_dragged(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        """Turn "this line belongs on that row" into a flip, or into its undo."""
        model = self._model
        group = self.group()
        if model is None or group is None:
            return
        held = model.lane_at(start_y)
        target = model.lane_at(end_y)
        if held is None or target is None or held == target:
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

    def _tolerance(self) -> float:
        model = self._model
        if model is None:
            return 0.0
        low, high = model.span()
        return max((high - low) * _SNAP, 1e-9)

    def nodes(self) -> tuple[BraidNode, ...]:
        """What the plot is currently offering, for tests and for the window."""
        return self._model.nodes if self._model is not None else ()


class IdentityWindow(QDialog):
    """The panel as its own non-blocking window.

    A dialog rather than a fourth splitter pane: this is consulted while
    watching the footage the crossing is in, and it must be possible to put it
    on a second screen beside the video.  Shown with ``show()``, never
    ``exec()`` -- rule 11 permits a modal for a dialog the user asked for, and
    this one declines it for the reason the alignment evidence does.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Fix Identities"))
        self.setModal(False)
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = IdentityPanel(self)
        layout.addWidget(self.panel)


class _quiet:
    """Block a combo box's signals while it is rebuilt."""

    def __init__(self, box: QComboBox) -> None:
        self._box = box

    def __enter__(self) -> QComboBox:
        self._box.blockSignals(True)
        return self._box

    def __exit__(self, *_exception: object) -> None:
        self._box.blockSignals(False)
