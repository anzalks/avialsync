"""Dialog for verifying and categorizing batch drag-and-drop imports."""

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialview.core.registry import LoaderRegistry
from avialview.core.source import TimeSeriesSource, VideoSource

# Semantic labels mapping to specific built-in loaders.
# This allows multiple semantic concepts (like Camera TTL vs Generic CSV)
# to point to the same underlying loader for easier categorization in the future.
_CATEGORY_DEFAULTS = [
    ("Electrophysiology Data", "NeoLoader"),
    ("Video", "VideoStandardLoader"),
    ("Tracking Data (2D/3D)", "TrackingLoader"),
    ("Generic CSV Time Series", "CSVLoader"),
    ("Camera TTLs / Events (CSV)", "CSVLoader"),
    ("Frame Triggers (CSV)", "CSVLoader"),
    ("AOL 3D Tracking", "AOLEksLoader"),
    ("AOL Encoder Log", "AOLEncoderLoader"),
]


class BatchImportDialog(QDialog):
    """Presents dropped files to the user for type verification before loading."""

    def __init__(
        self,
        candidates: Sequence[tuple[Path, type[TimeSeriesSource | VideoSource] | None, dict | None]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Import Candidates")
        self.setMinimumSize(600, 400)

        # Sort candidates: group by detected loader type, then alphabetically by filename
        def sort_key(
            item: tuple[Path, type[TimeSeriesSource | VideoSource] | None, dict | None],
        ) -> tuple[str, str]:
            path, loader_cls, _config = item
            type_name = loader_cls.__name__ if loader_cls else "zzz_none"
            return (type_name, path.name.lower())

        self._candidates = sorted(candidates, key=sort_key)
        self._registry = LoaderRegistry()
        self._build_category_map()

        layout = QVBoxLayout(self)

        self._table = QTableWidget(len(self._candidates), 2)
        self._table.setHorizontalHeaderLabels(["File / Group", "Detected Type"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().hide()
        layout.addWidget(self._table)

        self._combos: list[QComboBox] = []

        for row, (path, default_loader, _config) in enumerate(self._candidates):
            name_item = QTableWidgetItem(path.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setToolTip(str(path))
            self._table.setItem(row, 0, name_item)

            combo = QComboBox()
            # Populate dropdown
            combo.addItem("— Skip / Do Not Load —", None)

            default_index = 0
            for i, (label, loader_cls) in enumerate(self._categories, start=1):
                combo.addItem(label, loader_cls)
                if default_loader and loader_cls == default_loader and default_index == 0:
                    default_index = i

            combo.setCurrentIndex(default_index)
            self._table.setCellWidget(row, 1, combo)
            self._combos.append(combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_category_map(self) -> None:
        """Map semantic labels to actual loader classes."""
        self._categories: list[tuple[str, type[TimeSeriesSource | VideoSource]]] = []
        available_loaders = self._registry.loaders()

        # Add predefined semantic mappings for built-in loaders
        for label, class_name in _CATEGORY_DEFAULTS:
            loader_cls = next(
                (loader for loader in available_loaders if loader.__name__ == class_name),
                None,
            )
            if loader_cls:
                self._categories.append((label, loader_cls))

        # Add any third-party plugins that aren't in the defaults
        default_class_names = {name for _, name in _CATEGORY_DEFAULTS}
        for loader in available_loaders:
            if loader.__name__ not in default_class_names:
                self._categories.append((f"{loader.__name__} (Plugin)", loader))

    def get_selections(
        self,
    ) -> list[tuple[Path, type[TimeSeriesSource | VideoSource], dict | None]]:
        """Return the user-approved (Path, Loader, Config) tuples."""
        results = []
        for (path, _, config), combo in zip(self._candidates, self._combos, strict=True):
            loader_cls = combo.currentData()
            if loader_cls is not None:
                results.append((path, loader_cls, config))
        return results
