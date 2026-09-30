"""Left Sidebar / Inspector Pane."""

from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.inspection import SourceInspection
from avialsync.ui.channel_tree import group_prefixes, matches_filter, split_channel
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.quality_badge import findings_for, worst_severity
from avialsync.ui.source_properties import VideoPropertiesPanel
from avialsync.ui.theme import follow_palette, set_bold

_W = TypeVar("_W", bound=QWidget)


def _widgets_of(layout: QVBoxLayout, kind: type[_W]) -> "list[_W]":
    """Return the layout's direct child widgets of *kind*, skipping empty slots.

    ``QLayout.itemAt`` and ``QLayoutItem.widget`` both return None for a spacer
    or a slot that has been taken; every call site here wants "the real widgets
    of this type", so express that once.
    """
    found: list[_W] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        widget = item.widget()
        if isinstance(widget, kind):
            found.append(widget)
    return found


def _children_of(item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    """Return *item*'s direct children.

    ``QTreeWidgetItem.child`` is typed as returning None for an out-of-range
    index; walking ``range(childCount())`` never asks for one, so express that
    once here rather than guarding at each call site.
    """
    children = [item.child(index) for index in range(item.childCount())]
    return [child for child in children if child is not None]


#: Channel count above which the per-source filter is worth its own row.
_FILTER_THRESHOLD = 8


def _commit_on_edit(spin: QDoubleSpinBox) -> None:
    """Emit one value per edit, not one per keystroke.

    Qt spin boxes track the keyboard by default, so typing ``123`` emits 1,
    then 12, then 123. Each of those is a complete re-alignment of a source:
    three remaps, three coverage updates, and -- while the master timeline was
    still an accumulator -- three permanent stretches of it. Typing a
    four-digit offset walked the session through every prefix of it and kept
    the widest.

    Off, the value commits on Return, on Tab, on focus loss, and on the arrow
    keys and the step buttons, which is every gesture that means "I have
    decided". The digits in between are not decisions.
    """
    spin.setKeyboardTracking(False)


def _show_value(spin: QDoubleSpinBox, value: float) -> None:
    """Display *value* in *spin*, widening its range rather than clamping.

    A Qt spin box silently substitutes its own limit for anything outside its
    range, and `mapping()` then reports the substitute as fact -- which is how
    a session came to be saved with an offset nobody chose (D-026). These
    controls carry a hand correction, so the declared range is the right one to
    *type* in; a value that arrives from a restored session or an accepted fit
    is shown as it is, whatever it is.
    """
    value = float(value)
    minimum, maximum = spin.minimum(), spin.maximum()
    if value < minimum or value > maximum:
        spin.setRange(min(minimum, value), max(maximum, value))
    spin.setValue(value)


def _issues_button(parent: QWidget) -> QPushButton:
    """Create the compact native-icon action for source quality details."""
    button = QPushButton(parent)
    button.setFixedSize(24, 24)
    button.setIconSize(QSize(16, 16))
    button.setIcon(button.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
    button.setAccessibleName(tr("Source issues"))
    button.setAccessibleDescription(
        tr("Open details about this source's data quality and alignment.")
    )
    button.setToolTip(tr("Open source quality and alignment details"))
    return button


#: Range of the per-source offset controls, in seconds. A full day either way.
#:
#: It was +/-1 hour, which silently truncated any session whose sources carry a
#: wall-clock time base. An AOL recording is timed as seconds since midnight, so
#: a mid-morning session needs about -34500 s; the spin box clamped that to
#: -3600 and `mapping()` then reported the clamp as fact. Nothing warned, the
#: live view stayed correct because the value is applied with signals blocked,
#: and the wrong number only surfaced on save -- reopening the session put the
#: source hours away from the video. A control that cannot express a legitimate
#: value must not silently substitute one (D-026).
#:
#: A day is enough only because a source carrying wall-clock time is now placed
#: against the session zero on load (`core/session_time.py`), so what the user
#: types here is a residual correction rather than an epoch. Without that, an
#: `epoch_ms` CSV needs about 1.7e9 and this control could not express it at
#: any width -- which is the same defect one order of magnitude further out.
_OFFSET_LIMIT_S = 86_400.0


class SensorInfoWidget(QFrame):
    """Displays metadata and per-channel controls for one loaded sensor CSV."""

    filter_changed = Signal()
    remove_requested = Signal(str)  # whole sensor removed
    channel_remove_requested = Signal(str, str)  # sensor_path, channel_name
    channel_visibility_changed = Signal(str, str, bool)  # sensor_path, channel_name, is_visible
    #: sensor_path, group label, list of channel ids, is_visible. One signal
    #: for the whole group so the window can record a single undo step rather
    #: than one per channel.
    channel_group_visibility_changed = Signal(str, str, list, bool)
    #: Tracking source path, presentation surface (``overlay`` or ``plot``), visibility.
    tracking_visibility_changed = Signal(str, str, bool)
    badge_clicked = Signal(str)  # path
    report_requested = Signal(str)  # path
    # Source-to-master mapping, mirroring VideoInfoWidget.offset_changed (P3.5).
    mapping_changed = Signal(str, float, float)  # path, offset_s, drift_ppm

    def __init__(self, path: str, channels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self._channels = list(channels)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)

        # ── Header: filename + badge + remove whole source ──────────
        header = QHBoxLayout()
        name_lbl = ElidedLabel(Path(path).name)
        name_lbl.setToolTip(path)
        set_bold(name_lbl)

        self._badge_btn = _issues_button(self)
        self._badge_btn.setVisible(False)
        self._badge_btn.clicked.connect(lambda: self.badge_clicked.emit(self.path))
        self.identity_count = QLabel(self)
        self.identity_count.setAccessibleName(tr("Accepted identity swaps"))
        self.identity_count.setVisible(False)

        #: Everything the badge reports comes from these three. Alignment is
        #: session state, not file state, so it arrives separately.
        self._inspection: SourceInspection | None = None
        self._alignment_summary: str = ""
        self._has_accepted_alignment: bool = True

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setToolTip(tr("Remove entire sensor source"))
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))

        header.addWidget(name_lbl, stretch=1)
        header.addWidget(self.identity_count)
        header.addWidget(self._badge_btn)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Tracking overlays start enabled; high-volume plot rows stay opt-in.
        # Ordinary time-series sources keep their existing controls.
        self._tracking_controls = QWidget(self)
        tracking_row = QHBoxLayout(self._tracking_controls)
        tracking_row.setContentsMargins(0, 0, 0, 0)
        self.show_overlay = QCheckBox(tr("Show overlay"), self._tracking_controls)
        self.show_overlay.setObjectName("show_overlay")
        self.show_overlay.setAccessibleName(tr("Show tracking overlay"))
        self.show_overlay.setAccessibleDescription(
            tr("Show this tracking source on its available visual view.")
        )
        self.show_plot = QCheckBox(tr("Show plot"), self._tracking_controls)
        self.show_plot.setObjectName("show_plot")
        self.show_plot.setAccessibleName(tr("Show tracking plot"))
        self.show_plot.setAccessibleDescription(
            tr("Show this tracking source's coordinate channels in the plots.")
        )
        tracking_row.addWidget(self.show_overlay)
        tracking_row.addWidget(self.show_plot)
        tracking_row.addStretch()
        self._tracking_controls.setVisible(False)
        self.show_overlay.toggled.connect(
            lambda checked: self.tracking_visibility_changed.emit(self.path, "overlay", checked)
        )
        self.show_plot.toggled.connect(
            lambda checked: self.tracking_visibility_changed.emit(self.path, "plot", checked)
        )
        layout.addWidget(self._tracking_controls)

        # ── Metadata: path + channel count ──────────────────────────
        # A path is one unbreakable token, so wrapping it does nothing and it
        # kept reporting its full width as the panel's minimum: 491 px for a
        # real session path. Elided, its length no longer constrains anything.
        path_lbl = ElidedLabel(path)
        layout.addWidget(path_lbl)

        n_ch = len(channels)
        ch_count_lbl = QLabel(f"{n_ch} channel{'s' if n_ch != 1 else ''}")
        layout.addWidget(ch_count_lbl)

        # ── Sync controls: same offset/drift treatment as video (P3.5) ─
        #
        # One control per row. Measured: "Offset:" plus its spin box plus
        # "Drift:" plus its spin box want 564 px of width, in a sidebar whose
        # minimum is 180 px. Side by side they were cramped before this phase
        # and worse after raising the offset precision -- each was squeezed to
        # a fraction of the digits it has to show. A form layout gives each
        # its own line and lets the spin box use the width that is there.
        sync_form = QFormLayout()
        sync_form.setContentsMargins(0, 0, 0, 0)
        sync_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        sync_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-_OFFSET_LIMIT_S, _OFFSET_LIMIT_S)
        # Six decimals, not three. At 230 fps one frame is 4.35 ms, which
        # millisecond precision cannot express -- a frame-accurate nudge
        # silently rounded to 4 ms and the source drifted a fraction of a
        # frame every nudge. The sync fit already reports offsets to six
        # places, so this matches what the evidence view shows.
        self.offset_spin.setDecimals(6)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setSuffix(" s")
        # Allowed to shrink. Six decimals over a full-day range asks for 192 px;
        # a control that refuses to go below its ideal width drags the whole
        # panel out of shape in a narrow sidebar. Widen the sidebar to read the
        # full precision.
        # `setMinimumWidth` alone does not let it shrink: Qt floors a widget at
        # its own `minimumSizeHint`, which for six decimals over a full-day
        # range is 192 px. `Ignored` tells the layout to disregard that hint and
        # give it whatever width is going, which is what stops one control
        # dragging the whole panel out of shape.
        self.offset_spin.setMinimumWidth(90)
        self.offset_spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.offset_spin.setAccessibleName(f"Time offset for {Path(path).name}")
        self.offset_spin.setToolTip(
            tr("Shift this source against the master clock. Cached samples are never rewritten.")
        )
        _commit_on_edit(self.offset_spin)
        self.offset_spin.valueChanged.connect(self._on_mapping_changed)
        sync_form.addRow(tr("Offset:"), self.offset_spin)

        self.drift_spin = QDoubleSpinBox()
        self.drift_spin.setRange(-100000.0, 100000.0)
        self.drift_spin.setDecimals(1)
        self.drift_spin.setSingleStep(10.0)
        self.drift_spin.setSuffix(" ppm")
        self.drift_spin.setMinimumWidth(90)
        self.drift_spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.drift_spin.setAccessibleName(f"Clock drift for {Path(path).name}")
        self.drift_spin.setToolTip(
            tr("Rate difference between this source's clock and master time.")
        )
        _commit_on_edit(self.drift_spin)
        self.drift_spin.valueChanged.connect(self._on_mapping_changed)
        sync_form.addRow(tr("Drift:"), self.drift_spin)
        layout.addLayout(sync_form)

        # ── Separator ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # ── Channel Tree ─────────────────────────────────────────────

        self.tree = QTreeWidget()
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setIndentation(12)
        self.tree.setMinimumHeight(120)
        self.tree.setMaximumHeight(250)
        follow_palette(
            self.tree,
            lambda palette: (
                "QTreeWidget { border: 1px solid "
                f"{palette.color(QPalette.ColorRole.Mid).name()}"
                "; background: transparent; }"
            ),
        )
        # Filter, above the tree. A seventy-channel source is a scrolling
        # column otherwise, and the spec targets 128 (WP-11).
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("Filter channels…"))
        self._filter.setClearButtonEnabled(True)
        self._filter.setAccessibleName(f"Filter the channels of {Path(path).name}")
        self._external_filter = ""
        self._filter.textChanged.connect(self._on_local_filter_changed)
        if len(channels) > _FILTER_THRESHOLD:
            layout.addWidget(self._filter)
        else:
            # A filter over six channels is furniture. It still exists so the
            # code path is uniform, it is simply not shown.
            self._filter.setVisible(False)

        layout.addWidget(self.tree)

        self._channel_items: dict[str, QTreeWidgetItem] = {}
        self._group_items: list[QTreeWidgetItem] = []
        #: Held while a group toggle is being applied, so recomputing a parent
        #: from its children does not report a second group action.
        self._applying_group = False
        nodes = {"": self.tree.invisibleRootItem()}

        # Prefixes are decided across the whole source: whether "Jaw" is a
        # group depends on how many other channels share it, which no single
        # name can say.
        groupable = group_prefixes(list(channels))

        for ch in channels:
            parts = split_channel(ch, groupable)
            parent_path = ""
            for part in parts[:-1]:
                path_key = parent_path + "/" + part if parent_path else part
                if path_key not in nodes:
                    group_item = QTreeWidgetItem(nodes[parent_path])
                    group_item.setText(0, part)
                    font = group_item.font(0)
                    font.setBold(True)
                    group_item.setFont(0, font)
                    group_item.setExpanded(True)
                    # Checkable, so forty channels can be hidden in one click.
                    # Tristate because a partly-hidden group must look partly
                    # hidden rather than claim to be one or the other.
                    group_item.setFlags(
                        group_item.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsAutoTristate
                    )
                    group_item.setCheckState(0, Qt.CheckState.Checked)
                    nodes[path_key] = group_item
                    self._group_items.append(group_item)
                parent_path = path_key

            leaf_part = parts[-1]
            item = QTreeWidgetItem(nodes[parent_path])
            item.setText(0, leaf_part)
            item.setToolTip(0, ch)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)

            self._channel_items[ch] = item

        self.tree.itemChanged.connect(self._on_item_changed)

        # ── Show all / Hide all, for the whole source ────────────────
        bulk_row = QHBoxLayout()
        show_all_btn = QPushButton("Show all")
        show_all_btn.setToolTip(tr("Show every channel of this source"))
        show_all_btn.clicked.connect(lambda: self._on_bulk_visibility(True))
        hide_all_btn = QPushButton("Hide all")
        hide_all_btn.setToolTip(tr("Hide every channel of this source"))
        hide_all_btn.clicked.connect(lambda: self._on_bulk_visibility(False))
        # A push button defaults to the `Minimum` policy, which floors it at its
        # full sizeHint -- 110 px each here, so this pair alone demanded 223 px
        # and became the widest row in the panel. `Preferred` is not enough,
        # because a button reports the same minimumSizeHint as sizeHint; only
        # `Ignored` lets the layout go below it. The explicit floor is what
        # keeps them from collapsing to a sliver in the narrowest sidebar.
        #
        # `Ignored` also drops the *preferred* width to zero, so the trailing
        # stretch -- the only item the row gave a stretch factor -- claimed all
        # the free width and left both buttons a few pixels each. Each then
        # painted at its own 64 px floor from a position computed for those few
        # pixels, so "Show all" and "Hide all" landed on top of each other and
        # rendered as one unreadable "SHide all" at every sidebar width. Giving
        # the buttons a stretch factor of their own is what makes the layout
        # allocate the width they are going to paint at.
        for button in (show_all_btn, hide_all_btn):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(64)
        bulk_row.addWidget(show_all_btn, 1)
        bulk_row.addWidget(hide_all_btn, 1)
        bulk_row.addStretch(1)
        if len(channels) > 1:
            layout.addLayout(bulk_row)

        # ── Report button + Properties panel ─────────────────────────
        report_row = QHBoxLayout()
        self._report_btn = QPushButton("Report…")
        self._report_btn.setVisible(False)
        self._report_btn.clicked.connect(lambda: self.report_requested.emit(self.path))
        report_row.addWidget(self._report_btn)
        report_row.addStretch()
        layout.addLayout(report_row)

        from avialsync.ui.source_properties import SensorPropertiesPanel

        self._props_panel = SensorPropertiesPanel(_make_empty_inspection(path), parent=self)
        layout.addWidget(self._props_panel)

    def set_identity_count(self, count: int) -> None:
        """Show how many accepted flips this pose source carries."""
        self.identity_count.setText(tr("Swaps: {count}").format(count=count))
        self.identity_count.setToolTip(tr("{count} accepted identity swap(s)").format(count=count))
        self.identity_count.setVisible(count > 0)

    def set_tracking_controls(
        self, role: str, *, overlay_visible: bool, plot_visible: bool
    ) -> None:
        """Show the per-source presentation controls for a routed pose source."""
        is_tracking = role in {"overlay2d", "pose3d"}
        self._tracking_controls.setVisible(is_tracking)
        if not is_tracking:
            return
        if role == "overlay2d":
            self.show_overlay.setAccessibleDescription(
                tr("Draw this 2D tracking source over its assigned camera.")
            )
        else:
            self.show_overlay.setAccessibleDescription(
                tr("Show this 3D tracking source in the 3D tracking view.")
            )
        self.show_plot.setAccessibleDescription(
            tr("Show this tracking source's coordinate channels in the plots.")
        )
        for box, visible in ((self.show_overlay, overlay_visible), (self.show_plot, plot_visible)):
            blocked = box.blockSignals(True)
            box.setChecked(visible)
            box.blockSignals(blocked)

    def set_tracking_visible(self, surface: str, visible: bool) -> None:
        """Update one tracking presentation checkbox without reporting a command."""
        box = self.show_overlay if surface == "overlay" else self.show_plot
        blocked = box.blockSignals(True)
        box.setChecked(visible)
        box.blockSignals(blocked)

    def checked_channels(self) -> list[str]:
        """Return the channels selected for this source's plot presentation."""
        return [
            channel
            for channel, item in self._channel_items.items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def _apply_filter(self, needle: str) -> None:
        """Show only channels matching *needle*, keeping their groups visible.

        Hiding rather than rebuilding: the check state of every channel lives
        on its item, and rebuilding the tree to filter it would either lose
        that or need it mirrored somewhere else.
        """
        for channel, item in self._channel_items.items():
            matches_local = matches_filter(channel, needle)
            matches_external = matches_filter(channel, self._external_filter)
            item.setHidden(not (matches_local and matches_external))

        # A group whose every child is filtered out is noise; one with a
        # surviving child has to stay, and stay open, or the match is hidden
        # inside a collapsed node.
        for group in reversed(self._group_items):
            visible_children = any(not child.isHidden() for child in _children_of(group))
            group.setHidden(not visible_children)
            if visible_children and (needle or self._external_filter):
                group.setExpanded(True)

    def _on_local_filter_changed(self, needle: str) -> None:
        """Apply the local query, then let the sidebar update source cards."""
        self._apply_filter(needle)
        self.filter_changed.emit()

    def set_external_filter(self, needle: str) -> None:
        """Apply the inspector-wide query without changing the local filter."""
        self._external_filter = needle.strip().lower()
        self._apply_filter(self._filter.text())

    def visible_channel_count(self) -> int:
        """How many channels the filter currently shows."""
        return sum(1 for item in self._channel_items.values() if not item.isHidden())

    def _on_bulk_visibility(self, visible: bool) -> None:
        """Report Show all / Hide all as one action over every shown channel.

        Only what the filter is showing: a Hide all that also hid the channels
        the user had filtered out would be a surprise with no visible control
        saying it happened.
        """
        channels = [channel for channel, item in self._channel_items.items() if not item.isHidden()]
        if channels:
            state = Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
            blocked = self.tree.blockSignals(True)
            try:
                for channel in channels:
                    self._channel_items[channel].setCheckState(0, state)
            finally:
                self.tree.blockSignals(blocked)
            self.channel_group_visibility_changed.emit(
                self.path, Path(self.path).name, channels, visible
            )

    def _channels_under(self, group: QTreeWidgetItem) -> list[str]:
        """Every channel id beneath *group*, however deeply nested."""
        found: list[str] = []
        stack = _children_of(group)
        while stack:
            node = stack.pop()
            channel = node.toolTip(0)
            if channel:
                found.append(channel)
            stack.extend(_children_of(node))
        return found

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        channel = item.toolTip(0)
        if channel:
            is_visible = item.checkState(0) == Qt.CheckState.Checked
            self.channel_visibility_changed.emit(self.path, channel, is_visible)
            return

        # A group. Qt's auto-tristate has already propagated the new state down
        # and emitted itemChanged for each child, so this only reports the group
        # as one action -- and only when the user drove it, not when a child
        # change recomputed the parent.
        if item not in self._group_items or self._applying_group:
            return
        state = item.checkState(0)
        if state == Qt.CheckState.PartiallyChecked:
            return
        channels = self._channels_under(item)
        if channels:
            self.channel_group_visibility_changed.emit(
                self.path, item.text(0), channels, state == Qt.CheckState.Checked
            )

    def set_group_visible(self, group_label: str, visible: bool) -> None:
        """Set every channel under *group_label* without re-reporting the group.

        Used by undo. The per-channel signals still fire, because the plot rows
        are what they drive; the group signal does not, because replaying one
        command must not record another.
        """
        self._applying_group = True
        try:
            state = Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
            for group in self._group_items:
                if group.text(0) == group_label:
                    group.setCheckState(0, state)
        finally:
            self._applying_group = False

    def set_channel_visible(self, channel: str, visible: bool) -> bool:
        """Set a channel checkbox and return whether this source owns it."""
        item = self._channel_items.get(channel)
        if item is None:
            return False
        state = Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
        item.setCheckState(0, state)
        return True

    def _on_channel_remove(self, sensor_path: str, channel: str) -> None:
        item = self._channel_items.pop(channel, None)
        if item:
            parent = item.parent() or self.tree.invisibleRootItem()
            parent.removeChild(item)
        self.channel_remove_requested.emit(sensor_path, channel)

    def _on_mapping_changed(self, _value: float) -> None:
        self.mapping_changed.emit(self.path, self.offset_spin.value(), self.drift_spin.value())

    def set_mapping(self, offset: float, drift_ppm: float) -> None:
        """Show a restored mapping without re-emitting it back to the caller."""
        for spin, value in ((self.offset_spin, offset), (self.drift_spin, drift_ppm)):
            blocked = spin.blockSignals(True)
            _show_value(spin, value)
            spin.blockSignals(blocked)

    def mapping(self) -> tuple[float, float]:
        """Return the displayed ``(offset_s, drift_ppm)``."""
        return self.offset_spin.value(), self.drift_spin.value()

    def set_inspection(self, inspection: SourceInspection) -> None:
        """Update badge and properties panel from a SourceInspection."""
        self._inspection = inspection
        self._report_btn.setVisible(True)
        self._props_panel.update_inspection(inspection)
        self._refresh_badge()

    def set_alignment(self, summary: str, *, accepted: bool) -> None:
        """Record how this source is aligned, for the badge to report."""
        self._alignment_summary = summary
        self._has_accepted_alignment = accepted
        self._refresh_badge()

    def _refresh_badge(self) -> None:
        """One badge, from every finding -- the file's and the session's."""
        _render_badge(
            self._badge_btn,
            self._inspection,
            has_accepted_alignment=self._has_accepted_alignment,
            alignment_summary=self._alignment_summary,
        )


def _render_badge(
    button: QPushButton,
    inspection: SourceInspection | None,
    *,
    has_accepted_alignment: bool,
    alignment_summary: str,
) -> None:
    """Drive one source's badge from every finding about it, not only the file's.

    `ui/quality_badge.py` was written in Phase 7 to be exactly this -- including
    a "No accepted alignment" finding put there for the purpose -- and then
    nothing in `src/` ever imported it. The badge that shipped read
    `inspection.integrity_flags` instead, which is a property of the *file* and
    structurally cannot know whether the source has been aligned. So the "data
    dirty" half of architecture rule 10, and WP-10's persistent confidence
    badge, were computed and thrown away.

    Alignment is passed in rather than read off the inspection because it
    belongs to the session: the same recording is aligned in one and not in
    another.
    """
    findings = findings_for(inspection, has_accepted_alignment=has_accepted_alignment)
    if not findings:
        button.setVisible(False)
        return

    severity = worst_severity(findings)
    lines = [f"{finding.summary} \u2014 {finding.detail}" for finding in findings]
    if alignment_summary:
        lines.append(alignment_summary)
    button.setToolTip("\n\n".join(lines))
    button.setAccessibleDescription(" ".join(finding.summary for finding in findings))

    standard_icon = {
        "error": QStyle.StandardPixmap.SP_MessageBoxCritical,
        "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
        "info": QStyle.StandardPixmap.SP_MessageBoxInformation,
    }[severity]
    button.setIcon(button.style().standardIcon(standard_icon))
    button.setVisible(True)


def _make_empty_inspection(path: str) -> SourceInspection:

    return SourceInspection(path=path)


class VideoInfoWidget(QFrame):
    """Displays metadata and controls for a single loaded video."""

    remove_requested = Signal(str)  # Emits the file path
    offset_changed = Signal(str, float)  # Emits path, new offset
    mapping_changed = Signal(str, float, float)  # path, offset_s, drift_ppm
    visibility_changed = Signal(str, bool)  # Emits path, is_visible
    badge_clicked = Signal(str)  # path

    def __init__(self, path: str, metadata: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header: Checkbox, Name, and Close button
        from PySide6.QtWidgets import QCheckBox

        header_layout = QHBoxLayout()

        self.visibility_cb = QCheckBox()
        self.visibility_cb.setChecked(True)
        self.visibility_cb.setToolTip(tr("Show/Hide video pane"))
        self.visibility_cb.toggled.connect(
            lambda checked: self.visibility_changed.emit(self.path, checked)
        )

        name_lbl = ElidedLabel(Path(path).name)
        name_lbl.setToolTip(path)
        set_bold(name_lbl)

        close_btn = QPushButton("X")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))

        header_layout.addWidget(self.visibility_cb)
        header_layout.addWidget(name_lbl, stretch=1)
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)

        # Metadata
        fps = metadata.get("fps", 0.0)
        codec = metadata.get("codec", "unknown")
        duration = metadata.get("duration", 0.0)
        file_size = metadata.get("file_size_bytes", 0)
        is_vfr = metadata.get("is_vfr", False)
        measured_fps = metadata.get("measured_fps", fps)

        timing = f"VFR {measured_fps:.2f} avg (nominal {fps:.2f})" if is_vfr else f"CFR {fps:.2f}"
        size = f" | {file_size / 1_048_576:.1f} MB" if file_size else ""
        meta_lbl = QLabel(f"{codec.upper()} | {timing} | {duration:.1f}s{size}")
        # Wrapped: unwrapped it wants 432 px on one line -- the widest thing in
        # a sidebar whose minimum is 180 px -- and forced everything else out
        # of alignment rather than folding.
        meta_lbl.setWordWrap(True)
        layout.addWidget(meta_lbl)

        # Sync controls, in a form row for the same width reason as the sensor
        # widget: label plus spin box want 300 px against a 180 px sidebar
        # minimum, and a stretched QHBoxLayout squeezes the digits away.
        sync_form = QFormLayout()
        sync_form.setContentsMargins(0, 0, 0, 0)
        sync_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        sync_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-_OFFSET_LIMIT_S, _OFFSET_LIMIT_S)
        # Six decimals, not three. At 230 fps one frame is 4.35 ms, which
        # millisecond precision cannot express -- a frame-accurate nudge
        # silently rounded to 4 ms and the source drifted a frame every
        # nudge. The sync fit already reports offsets to six places.
        self.offset_spin.setDecimals(6)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setSuffix(" s")
        # `setMinimumWidth` alone does not let it shrink: Qt floors a widget at
        # its own `minimumSizeHint`, which for six decimals over a full-day
        # range is 192 px. `Ignored` tells the layout to disregard that hint and
        # give it whatever width is going, which is what stops one control
        # dragging the whole panel out of shape.
        self.offset_spin.setMinimumWidth(90)
        self.offset_spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.offset_spin.setAccessibleName(f"Time offset for {Path(path).name}")
        self.offset_spin.setToolTip(
            tr("Shift this camera against the master clock. The recording is never rewritten.")
        )
        _commit_on_edit(self.offset_spin)
        self.offset_spin.valueChanged.connect(self._on_offset_changed)
        sync_form.addRow(tr("Offset:"), self.offset_spin)

        # A camera had offset but no drift, so a rate difference could only ever
        # reach it through an accepted fit. A user watching a camera slip
        # against the sensor had to drift the *sensor* instead, which moves it
        # relative to every other camera at the same time.
        self.drift_spin = QDoubleSpinBox()
        self.drift_spin.setRange(-100000.0, 100000.0)
        self.drift_spin.setDecimals(1)
        self.drift_spin.setSingleStep(10.0)
        self.drift_spin.setSuffix(" ppm")
        self.drift_spin.setMinimumWidth(90)
        self.drift_spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.drift_spin.setAccessibleName(f"Clock drift for {Path(path).name}")
        self.drift_spin.setToolTip(
            tr("Rate difference between this camera's clock and master time.")
        )
        _commit_on_edit(self.drift_spin)
        self.drift_spin.valueChanged.connect(self._on_mapping_changed)
        sync_form.addRow(tr("Drift:"), self.drift_spin)
        layout.addLayout(sync_form)

        # Badge (hidden until inspection is available)
        self._badge_btn = _issues_button(self)
        self._badge_btn.setVisible(False)
        self._badge_btn.clicked.connect(lambda: self.badge_clicked.emit(self.path))
        header_layout.insertWidget(2, self._badge_btn)  # between name and close

        #: Everything the badge reports comes from these three. Alignment is
        #: session state, not file state, so it arrives separately.
        self._inspection: SourceInspection | None = None
        self._alignment_summary: str = ""
        self._has_accepted_alignment: bool = True

        self._props_panel = VideoPropertiesPanel(loader=None, parent=self)
        self._loader: object = None
        layout.addWidget(self._props_panel)

    def _on_offset_changed(self, val: float) -> None:
        self.offset_changed.emit(self.path, val)
        self._on_mapping_changed(val)

    def _on_mapping_changed(self, _value: float) -> None:
        self.mapping_changed.emit(self.path, self.offset_spin.value(), self.drift_spin.value())

    def mapping(self) -> tuple[float, float]:
        """Return the displayed ``(offset_s, drift_ppm)``."""
        return self.offset_spin.value(), self.drift_spin.value()

    def set_mapping(self, offset: float, drift_ppm: float) -> None:
        """Show a mapping without re-emitting it, as :meth:`set_offset` does."""
        for spin, value in ((self.offset_spin, offset), (self.drift_spin, drift_ppm)):
            blocked = spin.blockSignals(True)
            try:
                _show_value(spin, value)
            finally:
                spin.blockSignals(blocked)

    def set_offset(self, offset: float) -> None:
        """Show *offset* without re-emitting it.

        Blocked because the caller is undo or a session restore, which has
        already applied the value everywhere else; letting the spin box echo it
        back would record a second command for the same change.
        """
        blocked = self.offset_spin.blockSignals(True)
        try:
            _show_value(self.offset_spin, offset)
        finally:
            self.offset_spin.blockSignals(blocked)

    def set_visible(self, visible: bool) -> None:
        """Set the visibility checkbox without re-emitting it, as above."""
        blocked = self.visibility_cb.blockSignals(True)
        try:
            self.visibility_cb.setChecked(visible)
        finally:
            self.visibility_cb.blockSignals(blocked)

    def set_loader(self, loader: object) -> None:
        """Attach the VideoStandardLoader for metadata display."""
        self._loader = loader
        from avialsync.ui.source_properties import VideoPropertiesPanel

        self._props_panel.setParent(None)
        self._props_panel.deleteLater()
        self._props_panel = VideoPropertiesPanel(loader=loader, parent=self)
        panel_layout = self.layout()
        if panel_layout is not None:
            panel_layout.addWidget(self._props_panel)

    def set_pane(self, pane: object) -> None:
        """Attach the VideoPane so its live decode state can be shown."""
        self._props_panel.set_pane(pane)

    def set_inspection(self, inspection: SourceInspection) -> None:
        """Update the badge from everything known about this camera."""
        self._inspection = inspection
        self._refresh_badge()

    def set_alignment(self, summary: str, *, accepted: bool) -> None:
        """Record how this source is aligned, for the badge to report."""
        self._alignment_summary = summary
        self._has_accepted_alignment = accepted
        self._refresh_badge()

    def _refresh_badge(self) -> None:
        """One badge, from every finding -- the file's and the session's."""
        _render_badge(
            self._badge_btn,
            self._inspection,
            has_accepted_alignment=self._has_accepted_alignment,
            alignment_summary=self._alignment_summary,
        )


def _wrapped_note(text: str) -> QLabel:
    """A placeholder line that folds instead of setting the sidebar's width.

    Unwrapped, "No sensor data loaded." reports 264 px as its minimum, which in
    a 200 px sidebar is the difference between a scrollbar and none.
    """
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class SidebarPane(QWidget):
    """The left sidebar for file management and metadata."""

    open_video_requested = Signal()
    open_sensor_requested = Signal()

    video_offset_changed = Signal(str, float)
    video_mapping_changed = Signal(str, float, float)  # path, offset_s, drift_ppm
    video_remove_requested = Signal(str)
    video_visibility_changed = Signal(str, bool)
    video_badge_clicked = Signal(str)  # path
    sensor_remove_requested = Signal(str)
    sensor_mapping_changed = Signal(str, float, float)  # path, offset_s, drift_ppm
    sensor_badge_clicked = Signal(str)  # path
    sensor_report_requested = Signal(str)  # path
    channel_remove_requested = Signal(str, str)  # sensor_path, channel_name
    channel_visibility_changed = Signal(str, str, bool)  # sensor_path, channel_name, is_visible
    channel_group_visibility_changed = Signal(str, str, list, bool)
    tracking_visibility_changed = Signal(str, str, bool)  # source_path, surface, is_visible
    grid_mode_changed = Signal(bool)  # True = NxN grid, False = strip
    reset_session_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Measured, not guessed. The widest thing the sidebar has to hold is a
        # source panel, whose own minimum is 192 px once the header button and
        # the offset/drift spins are allowed to shrink. 180 px was below that,
        # and the 12 px difference is what pushed panel edges out of line.
        self.setMinimumWidth(200)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        # `AlwaysOff` does not make content fit -- it makes content that does
        # not fit unreachable, cut off at the viewport edge with no way to
        # scroll to it. The minimum above is set so the bar stays hidden in
        # normal use; this is the backstop for when something outgrows it.
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # A scrollbar is an interactive control, so it needs a name like any
        # other. Qt does not give one, and while the horizontal bar was forced
        # off it never appeared for a screen reader to trip over.
        self._scroll_area.horizontalScrollBar().setAccessibleName(tr("Scroll the sidebar sideways"))
        self._scroll_area.verticalScrollBar().setAccessibleName(tr("Scroll the sidebar"))

        scroll_content = QWidget()
        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(5, 5, 5, 5)

        # Row 1: Actions
        actions_group = QGroupBox("Open Files")
        actions_layout = QVBoxLayout(actions_group)
        self.btn_open_video = QPushButton("Open Videos")
        self.btn_open_sensor = QPushButton("Open Sensor/Ephys Data")
        self.btn_reset_session = QPushButton("Reset Session")
        self.btn_reset_session.setToolTip(tr("Close all loaded sources and start a fresh session"))
        self.btn_open_video.clicked.connect(self.open_video_requested)
        self.btn_open_sensor.clicked.connect(self.open_sensor_requested)
        self.btn_reset_session.clicked.connect(self.reset_session_requested)
        # Stacked, not side by side. "Open Sensor/Ephys Data" alone wants 278 px
        # and the pair wanted 430, which made this group the widest thing in the
        # sidebar by a wide margin -- so either the labels were cut off or the
        # sidebar had to carry a horizontal scrollbar to reach them. One button
        # per row costs a little height, of which the sidebar has plenty.
        for button in (self.btn_open_video, self.btn_open_sensor, self.btn_reset_session):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(120)
            actions_layout.addWidget(button)
        self.content_layout.addWidget(actions_group)

        self._source_filter = QLineEdit()
        self._source_filter.setPlaceholderText(tr("Filter sources and channels…"))
        self._source_filter.setClearButtonEnabled(True)
        self._source_filter.setAccessibleName(tr("Filter loaded sources and channels"))
        self._source_filter.setAccessibleDescription(
            tr("Search source names and channel names across the inspector.")
        )
        self._source_filter.textChanged.connect(self._apply_source_filter)
        self.content_layout.addWidget(self._source_filter)

        # Row 2: Videos — header has an inline "Grid" checkbox
        self.videos_group = QGroupBox()
        videos_top = QHBoxLayout()
        videos_top.setContentsMargins(0, 0, 0, 0)
        videos_title = QLabel("Videos")
        set_bold(videos_title)
        self._grid_chk = QCheckBox("⊞ Grid")
        self._grid_chk.setToolTip(tr("Arrange videos in an NxN grid instead of a horizontal strip"))
        self._grid_chk.toggled.connect(self.grid_mode_changed)
        videos_top.addWidget(videos_title)
        videos_top.addStretch()
        videos_top.addWidget(self._grid_chk)
        self.videos_layout = QVBoxLayout(self.videos_group)
        self.videos_layout.setContentsMargins(5, 5, 5, 5)
        self.videos_layout.addLayout(videos_top)
        self.content_layout.addWidget(self.videos_group)
        self._video_widgets: dict[str, VideoInfoWidget] = {}

        # Row 3: Sensors
        self.sensors_group = QGroupBox("Sensor Data")
        self.sensors_layout = QVBoxLayout(self.sensors_group)
        self.sensors_layout.addWidget(_wrapped_note("No sensor data loaded."))
        self.content_layout.addWidget(self.sensors_group)

        self.content_layout.addStretch(1)

        self._scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self._scroll_area)

    def add_video(self, path: str, metadata: dict) -> None:
        """Add a video info widget to the sidebar."""
        if path in self._video_widgets:
            return

        widget = VideoInfoWidget(path, metadata)
        widget.offset_changed.connect(self.video_offset_changed)
        widget.mapping_changed.connect(self.video_mapping_changed)
        widget.remove_requested.connect(self.video_remove_requested)
        widget.visibility_changed.connect(self.video_visibility_changed)
        widget.badge_clicked.connect(self.video_badge_clicked)

        self.videos_layout.addWidget(widget)
        self._video_widgets[path] = widget
        self._apply_source_filter(self._source_filter.text())

    def remove_video(self, path: str) -> None:
        """Remove a video info widget."""
        widget = self._video_widgets.pop(path, None)
        if widget:
            self.videos_layout.removeWidget(widget)
            widget.deleteLater()

    def clear_sources(self) -> None:
        """Remove every source summary from the sidebar."""
        self._source_filter.clear()
        for path in list(self._video_widgets):
            self.remove_video(path)
        for widget in _widgets_of(self.sensors_layout, SensorInfoWidget):
            self.remove_sensor(widget.path)

    def add_sensor(self, path: str, channels: list[str]) -> None:
        """Add a sensor info widget to the sidebar."""
        # Remove placeholder if present
        if self.sensors_layout.count() == 1:
            for placeholder in _widgets_of(self.sensors_layout, QLabel):
                self.sensors_layout.removeWidget(placeholder)
                placeholder.deleteLater()

        widget = SensorInfoWidget(path, channels)
        widget.remove_requested.connect(self.sensor_remove_requested)
        widget.channel_remove_requested.connect(self.channel_remove_requested)
        widget.channel_visibility_changed.connect(self.channel_visibility_changed)
        widget.channel_group_visibility_changed.connect(self.channel_group_visibility_changed)
        widget.tracking_visibility_changed.connect(self.tracking_visibility_changed)
        widget.badge_clicked.connect(self.sensor_badge_clicked)
        widget.report_requested.connect(self.sensor_report_requested)
        widget.mapping_changed.connect(self.sensor_mapping_changed)
        widget.filter_changed.connect(self._refresh_source_filter)
        self.sensors_layout.addWidget(widget)
        self._apply_source_filter(self._source_filter.text())

    def _refresh_source_filter(self) -> None:
        """Reevaluate source cards after a per-source filter edit."""
        self._apply_source_filter(self._source_filter.text())

    def _apply_source_filter(self, text: str) -> None:
        """Filter source cards and channel rows across the whole inspector."""
        needle = text.strip().lower()
        for path, widget in self._video_widgets.items():
            widget.setVisible(not needle or needle in path.lower())

        for sensor_widget in _widgets_of(self.sensors_layout, SensorInfoWidget):
            source_matches = bool(needle and needle in sensor_widget.path.lower())
            sensor_widget.set_external_filter("" if source_matches else needle)
            sensor_widget.setVisible(
                not needle or source_matches or sensor_widget.visible_channel_count() > 0
            )

    def set_tracking_controls(
        self, path: str, role: str, *, overlay_visible: bool, plot_visible: bool
    ) -> None:
        """Configure the presentation controls for one routed tracking source."""
        widget = self.sensor_widget(path)
        if widget is not None:
            widget.set_tracking_controls(
                role, overlay_visible=overlay_visible, plot_visible=plot_visible
            )

    def set_tracking_visible(self, path: str, surface: str, visible: bool) -> None:
        """Mirror a tracking presentation change into its sidebar control."""
        widget = self.sensor_widget(path)
        if widget is not None:
            widget.set_tracking_visible(surface, visible)

    def set_channel_visible(self, channel: str, visible: bool, source_id: str = "") -> bool:
        """Mirror plot-row visibility to the owning channel checkbox.

        *source_id* disambiguates a channel name shared by several loaded files.
        Without it the first owner wins, which is only safe when the caller
        already knows the name is unique.
        """
        if source_id:
            widget = self.sensor_widget(source_id)
            if widget is not None:
                return widget.set_channel_visible(channel, visible)
            return False
        for widget in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if widget.set_channel_visible(channel, visible):
                return True
        return False

    def remove_sensor(self, path: str) -> None:
        """Remove a sensor info widget."""
        for w in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if True and w.path == path:
                self.sensors_layout.removeWidget(w)
                w.deleteLater()
                break

        if self.sensors_layout.count() == 0:
            self.sensors_layout.addWidget(_wrapped_note("No sensor data loaded."))

    def set_video_loader(self, path: str, loader: object) -> None:
        """Forward loader reference to VideoInfoWidget for properties panel."""
        w = self._video_widgets.get(path)
        if w:
            w.set_loader(loader)

    def set_video_pane(self, path: str, pane: object) -> None:
        """Forward VideoPane reference to VideoInfoWidget for live decode state."""
        w = self._video_widgets.get(path)
        if w:
            w.set_pane(pane)

    def set_video_alignment(self, path: str, summary: str, *, accepted: bool) -> None:
        """Tell one camera's badge how it is aligned."""
        widget = self._video_widgets.get(path)
        if widget:
            widget.set_alignment(summary, accepted=accepted)

    def set_sensor_alignment(self, path: str, summary: str, *, accepted: bool) -> None:
        """Tell one sensor's badge how it is aligned."""
        for widget in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if widget.path == path:
                widget.set_alignment(summary, accepted=accepted)
                return

    def set_video_inspection(self, path: str, inspection: SourceInspection) -> None:
        """Forward SourceInspection to the VideoInfoWidget badge."""
        w = self._video_widgets.get(path)
        if w:
            w.set_inspection(inspection)

    def sensor_widget(self, path: str) -> SensorInfoWidget | None:
        """Return the widget owning *path*, or None when it is not loaded."""
        for widget in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if True and widget.path == path:
                return widget
        return None

    def set_sensor_identity_count(self, path: str, count: int) -> None:
        """Show the accepted flip count beside one loaded pose source."""
        widget = self.sensor_widget(path)
        if widget is not None:
            widget.set_identity_count(count)

    def set_sensor_mapping(self, path: str, offset: float, drift_ppm: float) -> None:
        """Show a restored sensor mapping without re-emitting it."""
        widget = self.sensor_widget(path)
        if widget is not None:
            widget.set_mapping(offset, drift_ppm)

    def set_video_offset(self, path: str, offset: float) -> None:
        """Show a restored or undone video offset, mirroring the sensor path.

        Undo has to drive the control the user drove, not just the pane behind
        it: leaving the spin box on the old value would show an offset the
        session no longer has.
        """
        widget = self._video_widgets.get(path)
        if widget is not None:
            widget.set_offset(offset)

    def video_offset(self, path: str) -> float:
        """Return the displayed offset for *path*, or 0.0 when not loaded."""
        widget = self._video_widgets.get(path)
        return widget.offset_spin.value() if widget is not None else 0.0

    def set_video_mapping(self, path: str, offset: float, drift_ppm: float) -> None:
        """Show a video's offset and drift together, without re-emitting either.

        `set_video_offset` moves one control; this moves both, for the callers
        that have a whole mapping to show -- a restored session, an accepted
        fit -- and would otherwise leave the drift reading the previous one's.
        """
        widget = self._video_widgets.get(path)
        if widget is not None:
            widget.set_mapping(offset, drift_ppm)

    def video_mapping(self, path: str) -> tuple[float, float]:
        """Return the displayed ``(offset_s, drift_ppm)`` for *path*."""
        widget = self._video_widgets.get(path)
        return widget.mapping() if widget is not None else (0.0, 0.0)

    def set_video_visible(self, path: str, visible: bool) -> None:
        """Set a video's visibility checkbox without re-emitting it."""
        widget = self._video_widgets.get(path)
        if widget is not None:
            widget.set_visible(visible)

    def sensor_mapping(self, path: str) -> tuple[float, float]:
        """Return the displayed ``(offset_s, drift_ppm)`` for *path*."""
        widget = self.sensor_widget(path)
        return widget.mapping() if widget is not None else (0.0, 0.0)

    def set_sensor_inspection(self, path: str, inspection: SourceInspection) -> None:
        """Forward SourceInspection to the SensorInfoWidget badge + panel."""
        for w in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if True and w.path == path:
                w.set_inspection(inspection)
                break
