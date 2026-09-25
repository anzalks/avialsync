"""Dialog for verifying and categorizing batch drag-and-drop imports."""

import logging
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
from avialsync.ui.i18n import tr

logger = logging.getLogger(__name__)


class BatchImportDialog(QDialog):
    """Presents dropped files to the user for type verification before loading."""

    def __init__(
        self,
        candidates: Sequence[tuple[Path, type[TimeSeriesSource | VideoSource] | None, dict | None]],
        parent: QWidget | None = None,
        labels: Mapping[str, str] | None = None,
        kinds: Mapping[str, str] | None = None,
        video_paths: Sequence[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Review Import Candidates"))
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
        self._video_paths = list(
            dict.fromkeys(
                [
                    *video_paths,
                    *(
                        str(path)
                        for path, loader, _ in self._candidates
                        if loader is not None and issubclass(loader, VideoSource)
                    ),
                    *(
                        str(config["overlay_video"])
                        for _, _, config in self._candidates
                        if config and config.get("overlay_video")
                    ),
                ]
            )
        )

        layout = QVBoxLayout(self)

        self._table = QTableWidget(len(self._candidates), 3)
        self._table.setHorizontalHeaderLabels(
            [tr("File / Group"), tr("Detected Type"), tr("Use as")]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().hide()
        layout.addWidget(self._table)

        self._combos: list[QComboBox] = []
        self._role_combos: list[QComboBox] = []

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
            fallback_index = 0
            for i, (label, loader_cls) in enumerate(self._categories, start=1):
                combo.addItem(label, loader_cls)
                if loader_cls != default_loader:
                    continue
                if fallback_index == 0:
                    fallback_index = i
                if wanted_kind and label == wanted_kind:
                    default_index = i
            # Index 0 is "Skip". A declared kind that matches none of its own
            # loader's labels must fall back to that loader, not silently drop
            # the row: the user would have seen it listed and not imported.
            if default_index == 0:
                if wanted_kind:
                    logger.warning(
                        "%s declared kind %r, which %s does not offer; using its own name.",
                        path.name,
                        wanted_kind,
                        default_loader.__name__ if default_loader else "no loader",
                    )
                default_index = fallback_index

            combo.setCurrentIndex(default_index)
            self._table.setCellWidget(row, 1, combo)
            self._combos.append(combo)
            role_combo = QComboBox(self._table)
            role_combo.setAccessibleName(tr("Use for {file}").format(file=path.name))
            role_combo.setAccessibleDescription(
                tr("Choose data channels, 3D pose, or 2D pose for a named camera video")
            )
            self._table.setCellWidget(row, 2, role_combo)
            self._role_combos.append(role_combo)
            combo.currentIndexChanged.connect(lambda _index, at=row: self._update_roles(at))
            self._update_roles(row)

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

    def _update_roles(self, row: int) -> None:
        """Offer only pose uses the chosen loader declares, with a camera target."""
        combo = self._role_combos[row]
        loader = self._combos[row].currentData()
        config = self._candidates[row][2] or {}
        previous = combo.currentData()
        wanted = (
            previous
            if previous is not None
            else [
                config.get("role", ""),
                config.get("overlay_video", ""),
            ]
        )
        combo.clear()
        combo.addItem(tr("Data channels"), ["", ""])
        if isinstance(loader, type) and issubclass(loader, TimeSeriesSource):
            roles = loader.pose_roles()
            if "pose3d" in roles or config.get("role") == "pose3d":
                combo.addItem(tr("3D pose"), ["pose3d", ""])
            if "overlay2d" in roles or config.get("role") == "overlay2d":
                for video in self._video_paths:
                    combo.addItem(
                        tr("2D pose on {video}").format(video=Path(video).name),
                        ["overlay2d", video],
                    )
        index = combo.findData(wanted)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.setEnabled(combo.count() > 1)

    def get_selections(
        self,
    ) -> list[tuple[Path, type[TimeSeriesSource | VideoSource], dict | None]]:
        """Return the user-approved (Path, Loader, Config) tuples."""
        results = []
        for (path, _, config), combo, role_combo in zip(
            self._candidates, self._combos, self._role_combos, strict=True
        ):
            loader_cls = combo.currentData()
            if loader_cls is not None:
                role, video = role_combo.currentData()
                chosen = dict(config or {})
                chosen.pop("role", None)
                chosen.pop("overlay_video", None)
                if role:
                    chosen["role"] = role
                if video:
                    chosen["overlay_video"] = video
                results.append((path, loader_cls, chosen if chosen or config is not None else None))
        return results
