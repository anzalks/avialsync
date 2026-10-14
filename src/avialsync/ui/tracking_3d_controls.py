"""Video-style bottom tools and a floating, labeled 3D display panel."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.action_button import ActionButton, ActionCheckBox
from avialsync.ui.design_tokens import ControlRole, apply_role, spacing
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.tracking_skeleton import BoneMode


class Tracking3DControls(QWidget):
    """Keep view commands visible while bone appearance uses a small popup.

    Thickness remains the rendering authority: zero draws lines, a positive
    diameter draws tubes. The style selector reflects that value and remembers
    the last positive diameter only for switching back from lines.
    """

    def __init__(self, maximum_thickness: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tube_diameter = 1.0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(spacing("xs"), spacing("xs"), spacing("xs"), spacing("xs"))
        layout.setSpacing(spacing("s"))
        self.title_label = QLabel(tr("3D"), self)
        self.title_label.setAccessibleName(tr("3D Tracking"))
        self.status_label = ElidedLabel(
            tr("No XYZ tracking channels"), self, Qt.TextElideMode.ElideRight
        )
        self.reprojection_button = ActionButton(self)
        self.up_axis_combo = self._up_axis_control()
        self.display_button = QPushButton(tr("Display"), self)
        self.display_button.setAccessibleName(tr("3D display settings"))
        self.display_button.setAccessibleDescription(
            tr("Choose the skeleton, line or tube drawing, and bone thickness.")
        )
        self.display_button.setToolTip(self.display_button.accessibleDescription())
        apply_role(self.display_button, ControlRole.TOOL, "settings")
        self.display_button.clicked.connect(self._open_display_popup)

        self.fit_button = QPushButton(tr("Fit View"), self)
        self.fit_button.setAccessibleName(self.fit_button.text())
        self.fit_button.setAccessibleDescription(tr("Fit the 3D camera to the current scene."))
        self.fit_button.setToolTip(self.fit_button.accessibleDescription())
        apply_role(self.fit_button, ControlRole.TOOL, "fit-view")
        self.fit_button.setEnabled(False)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.up_axis_combo)
        for button in (self.display_button, self.reprojection_button, self.fit_button):
            layout.addWidget(button)
        self._build_display_panel(maximum_thickness)

    def _up_axis_control(self) -> QComboBox:
        combo = QComboBox(self)
        combo.setAccessibleName(tr("Vertical axis"))
        combo.setAccessibleDescription(
            tr("Choose which source axis points up; overrides the detected orientation.")
        )
        combo.setToolTip(combo.accessibleDescription())
        for label, axis, inverted in (
            (tr("Up: X"), 0, False),
            (tr("Up: -X"), 0, True),
            (tr("Up: Y"), 1, False),
            (tr("Up: -Y"), 1, True),
            (tr("Up: Z"), 2, False),
            (tr("Up: -Z"), 2, True),
        ):
            combo.addItem(label, (axis, inverted))
        return combo

    def _build_display_panel(self, maximum_thickness: float) -> None:
        # Camera levels use a popup frame too: interactive controls embedded
        # in QMenu can be disabled or sized while hidden on native platforms.
        self.display_popup = QFrame(self, Qt.WindowType.Popup)
        self.display_popup.setAttribute(Qt.WidgetAttribute.WA_WindowPropagation)
        self.display_popup.setFrameShape(QFrame.Shape.StyledPanel)
        self.display_popup.setAccessibleName(tr("3D display settings"))
        self.display_popup.setAccessibleDescription(
            tr("Appearance of the skeleton in the 3D view.")
        )
        layout = QVBoxLayout(self.display_popup)
        layout.setContentsMargins(spacing("l"), spacing("m"), spacing("l"), spacing("m"))
        layout.setSpacing(spacing("m"))
        self.point_labels_checkbox = ActionCheckBox(self.display_popup)
        self.point_labels_checkbox.setAccessibleDescription(
            tr("Show or hide body-part names in this 3D view; video labels are independent.")
        )
        layout.addWidget(self.point_labels_checkbox)
        form = QFormLayout()
        form.setHorizontalSpacing(spacing("m"))
        form.setVerticalSpacing(spacing("s"))
        self.bone_combo = self._skeleton_control()
        form.addRow(tr("Skeleton"), self.bone_combo)
        self._add_drawing_controls(form, maximum_thickness)
        form.addRow(tr("Units"), QLabel(tr("Calibration units"), self.display_popup))
        layout.addLayout(form)
        note = QLabel(tr("Detected bones stay dashed."), self.display_popup)
        layout.addWidget(note)

    def _skeleton_control(self) -> QComboBox:
        combo = QComboBox(self.display_popup)
        combo.setAccessibleName(tr("Skeleton"))
        combo.setAccessibleDescription(
            tr("Auto uses the session skeleton or detected bones. Detected bones are dashed.")
        )
        combo.setToolTip(combo.accessibleDescription())
        for label, mode in (
            (tr("Auto"), BoneMode.AUTO),
            (tr("Detected"), BoneMode.DETECTED),
            (tr("Off"), BoneMode.OFF),
        ):
            combo.addItem(label, mode)
        return combo

    def _add_drawing_controls(self, form: QFormLayout, maximum_thickness: float) -> None:
        self.bone_style_combo = QComboBox(self.display_popup)
        self.bone_style_combo.setAccessibleName(tr("Bone drawing"))
        self.bone_style_combo.setAccessibleDescription(
            tr("Draw session-declared bones as lines or shaded tubes.")
        )
        self.bone_style_combo.setToolTip(self.bone_style_combo.accessibleDescription())
        self.bone_style_combo.addItem(tr("Lines"))
        self.bone_style_combo.addItem(tr("Tubes"))
        self.bone_style_combo.activated.connect(self._on_style_selected)
        form.addRow(tr("Drawing"), self.bone_style_combo)
        self.bone_thickness = QDoubleSpinBox(self.display_popup)
        self.bone_thickness.setRange(0.0, maximum_thickness)
        self.bone_thickness.setDecimals(3)
        self.bone_thickness.setSingleStep(0.1)
        self.bone_thickness.setKeyboardTracking(False)
        self.bone_thickness.setAccessibleName(tr("Bone thickness"))
        self.bone_thickness.setAccessibleDescription(
            tr("Tube diameter in the calibration's 3D coordinate units; use the props' units.")
        )
        self.bone_thickness.setToolTip(self.bone_thickness.accessibleDescription())
        self.bone_thickness.setEnabled(False)
        self.bone_thickness.valueChanged.connect(self._on_thickness_changed)
        form.addRow(tr("Thickness"), self.bone_thickness)

    def _open_display_popup(self) -> None:
        """Open the settings like camera levels, constrained to the screen."""
        popup = self.display_popup
        popup.ensurePolished()
        layout = popup.layout()
        if layout is not None:
            layout.activate()
        popup.adjustSize()
        anchor = self.display_button.mapToGlobal(QPoint(0, self.display_button.height()))
        position = QPoint(anchor.x(), anchor.y() - self.display_button.height() - popup.height())
        screen = self.display_button.screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            if position.y() < bounds.top():
                position.setY(anchor.y() + spacing("s"))
            position.setX(min(max(position.x(), bounds.left()), bounds.right() + 1 - popup.width()))
            position.setY(
                min(max(position.y(), bounds.top()), bounds.bottom() + 1 - popup.height())
            )
        popup.move(position)
        popup.show()
        self.bone_combo.setFocus()

    def _on_style_selected(self, index: int) -> None:
        """Use the existing diameter value to select line or tube rendering."""
        self.bone_thickness.setValue(0.0 if index == 0 else self._tube_diameter)

    def _on_thickness_changed(self, diameter: float) -> None:
        """Keep the style selector in step with direct edits of the diameter."""
        if diameter > 0.0:
            self._tube_diameter = diameter
        blocked = self.bone_style_combo.blockSignals(True)
        try:
            self.bone_style_combo.setCurrentIndex(int(diameter > 0.0))
        finally:
            self.bone_style_combo.blockSignals(blocked)
        self.bone_thickness.setEnabled(diameter > 0.0)
