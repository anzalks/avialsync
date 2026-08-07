"""Dialog for verifying and categorizing batch drag-and-drop imports."""

from collections.abc import Mapping, Sequence
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

from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import TimeSeriesSource, VideoSource


class BatchImportDialog(QDialog):
    """Presents dropped files to the user for type verification before loading."""

    def __init__(
        self,
        candidates: Sequence[tuple[Path, type[TimeSeriesSource | VideoSource] | None, dict | None]],
        parent: QWidget | None = None,
        labels: Mapping[str, str] | None = None,
        kinds: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Import Candidates")
        self.setMinimumSize(600, 400)

        #: Row names a session supplied, by path. A recording's streams are all
        #: read by the same loader and all live under directories named after
        #: the acquisition board, so filename and type together still did not
        #: say which row was the 32-channel 30 kHz one — the only row whose
        #: import costs minutes and gigabytes.
        self._labels: Mapping[str, str] = labels or {}

        #: The kind of data a session declared for a path. One loader reads many
        #: kinds — every stream of a recording goes through the same reader — so
        #: without this an 18-channel IMU was typed "Electrophysiology Data"
        #: purely because neo is what reads it.
        self._kinds: Mapping[str, str] = kinds or {}

        # Group by detected type, then by the name actually shown, so a session's
        # rows sort the way they are read rather than by a path the user cannot see.
        def sort_key(
            item: tuple[Path, type[TimeSeriesSource | VideoSource] | None, dict | None],
        ) -> tuple[str, str]:
            path, loader_cls, _config = item
            type_name = loader_cls.__name__ if loader_cls else "zzz_none"
            return (type_name, self._row_name(path).lower())

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
            name_item = QTableWidgetItem(self._row_name(path))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setToolTip(str(path))
            self._table.setItem(row, 0, name_item)

            combo = QComboBox()
            # Populate dropdown
            combo.addItem("— Skip / Do Not Load —", None)

            # A declared kind selects among the loader's own labels; without one
            # the loader's primary name is the default, as before.
            wanted_kind = self._kinds.get(str(path), "")
            default_index = 0
            for i, (label, loader_cls) in enumerate(self._categories, start=1):
                combo.addItem(label, loader_cls)
                if loader_cls != default_loader:
                    continue
                if wanted_kind and label == wanted_kind:
                    default_index = i
                elif not wanted_kind and default_index == 0:
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

    def _row_name(self, path: Path) -> str:
        """Return what to call *path*: the session's own label, else its filename."""
        return self._labels.get(str(path)) or path.name

    def _build_category_map(self) -> None:
        """Map semantic labels to actual loader classes."""
        self._categories: list[tuple[str, type[TimeSeriesSource | VideoSource]]] = []
        available_loaders = self._registry.loaders()

        # Add predefined semantic mappings for built-in loaders
        # Every format names itself, so a new one appears here by being
        # installed. A third-party plugin is listed exactly like a built-in;
        # this dialog knows no format by name.
        for loader in available_loaders:
            self._categories.append((loader.display_name(), loader))
            for alias in loader.display_aliases():
                self._categories.append((alias, loader))

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
