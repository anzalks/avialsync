"""Dialog for verifying and categorizing batch drag-and-drop imports."""

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.registry import LoaderRegistry
from avialsync.core.rig_naming import match_label
from avialsync.core.source import ImagingSource, TimeSeriesSource, VideoSource
from avialsync.ui.design_tokens import spacing
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.tables import ThemedTable

logger = logging.getLogger(__name__)
SourceLoader = type[TimeSeriesSource | VideoSource | ImagingSource]


class BatchImportDialog(QDialog):
    """Presents dropped files to the user for type verification before loading."""

    def __init__(
        self,
        candidates: Sequence[tuple[Path, SourceLoader | None, dict | None]],
        parent: QWidget | None = None,
        labels: Mapping[str, str] | None = None,
        kinds: Mapping[str, str] | None = None,
        video_paths: Sequence[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Review Import Candidates"))
        # Wide enough that a lab filename keeps both ends after elision.
        self.setMinimumSize(920, 400)

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
            item: tuple[Path, SourceLoader | None, dict | None],
        ) -> tuple[str, str]:
            path, loader_cls, _config = item
            type_name = loader_cls.__name__ if loader_cls else "zzz_none"
            return (type_name, self._row_name(path).lower())

        self._candidates = sorted(candidates, key=sort_key)
        self._calibration_paths = sorted(
            {path for path, _loader, _config in self._candidates if path.suffix.lower() == ".xcp"}
            | {
                path.with_suffix(".xcp")
                for path, _loader, _config in self._candidates
                if path.suffix.lower() == ".c3d" and path.with_suffix(".xcp").is_file()
            },
            key=lambda path: str(path).lower(),
        )
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

        self._table = ThemedTable(len(self._candidates), 4)
        self._table.setHorizontalHeaderLabels(
            [tr("File / Group"), tr("Detected Type"), tr("Use as"), tr("Calibration (XCP)")]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        # A column of identical prefixes is what ElideRight gives you here: a
        # DeepLabCut export names every artifact after the same model and
        # snapshot, so what tells `..._el.csv` from `..._full.mp4` is the tail.
        # The same reasoning, and the same choice, as `ui/elided_label.py`.
        self._table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().hide()
        layout.addWidget(self._table)

        self._combos: list[QComboBox] = []
        self._role_combos: list[QComboBox] = []
        self._calibration_combos: list[QComboBox] = []
        self._calibration_previous_indices: list[int] = []

        for row, (path, default_loader, _config) in enumerate(self._candidates):
            name_item = QTableWidgetItem(self._row_name(path))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setToolTip(str(path))
            self._table.setItem(row, 0, name_item)
            # Drawn by the widget the application already uses for data text,
            # rather than left to the view's own eliding. A view elides to the
            # column it was given; this elides to the width it has, keeps both
            # ends, and carries the whole path in its tooltip -- which is what
            # turns nine rows of "Trial …" back into nine distinguishable
            # files. The item above stays for anything reading the table.
            name_label = ElidedLabel(self._row_name(path), self._table)
            name_label.setToolTip(str(path))
            name_label.setContentsMargins(spacing("s"), 0, spacing("s"), 0)
            self._table.setCellWidget(row, 0, name_label)

            combo = QComboBox()
            sidecar_suffix = path.suffix.lower()
            if sidecar_suffix == ".xcp":
                combo.addItem(tr("Calibration sidecar; select it on a tracking row"), None)
                combo.setEnabled(False)
            elif sidecar_suffix == ".x2d":
                combo.addItem(tr("Unsupported Vicon camera data; not a tracking source"), None)
                combo.setEnabled(False)
            else:
                combo.addItem(tr("— Skip / Do Not Load —"), None)

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

            calibration_combo = QComboBox(self._table)
            calibration_combo.setAccessibleName(
                tr("Calibration file for {file}").format(file=path.name)
            )
            calibration_combo.setAccessibleDescription(
                tr("Choose a Vicon XCP camera calibration file")
            )
            calibration_combo.addItem(tr("Not required"), None)
            calibration_combo.setEnabled(False)
            calibration_combo.currentIndexChanged.connect(
                lambda index, at=row: self._calibration_changed(at, index)
            )
            self._table.setCellWidget(row, 3, calibration_combo)
            self._calibration_combos.append(calibration_combo)
            self._calibration_previous_indices.append(0)
            combo.currentIndexChanged.connect(lambda _index, at=row: self._update_calibration(at))
            self._update_calibration(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_calibration(self, row: int) -> None:
        combo = self._calibration_combos[row]
        loader = self._combos[row].currentData()
        if getattr(loader, "calibration_suffix", None) != ".xcp":
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("Not required"), None)
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
            combo.blockSignals(False)
            self._calibration_previous_indices[row] = 0
            return

        path, _default_loader, config = self._candidates[row]
        config_xcp = str((config or {}).get("xcp_path", ""))
        calibration_paths = list(self._calibration_paths)
        sibling_xcp = path.with_suffix(".xcp")
        if sibling_xcp.is_file() and sibling_xcp not in calibration_paths:
            calibration_paths.append(sibling_xcp)
        if config_xcp and Path(config_xcp) not in calibration_paths:
            calibration_paths.append(Path(config_xcp))

        previous_data = combo.currentData()
        calibration_values = {str(calibration_path) for calibration_path in calibration_paths}
        default_xcp = (
            previous_data
            if isinstance(previous_data, str) and previous_data in calibration_values
            else config_xcp
        )
        if not default_xcp and sibling_xcp.is_file():
            default_xcp = str(sibling_xcp)
        if not default_xcp and len(calibration_paths) == 1:
            default_xcp = str(calibration_paths[0])

        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("Auto-detect matching XCP"), None)
        for calibration_path in calibration_paths:
            combo.addItem(calibration_path.name, str(calibration_path))
        combo.addItem(tr("Browse…"), "__browse_xcp__")
        selected_index = combo.findData(default_xcp) if default_xcp else 0
        combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        combo.setEnabled(True)
        combo.blockSignals(False)
        self._calibration_previous_indices[row] = combo.currentIndex()

    def _calibration_changed(self, row: int, index: int) -> None:
        combo = self._calibration_combos[row]
        if combo.itemData(index) != "__browse_xcp__":
            self._calibration_previous_indices[row] = index
            return

        path = self._candidates[row][0]
        selected, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select Vicon Calibration"),
            str(path.parent),
            tr("Vicon calibration files (*.xcp)"),
        )
        combo.blockSignals(True)
        if selected:
            selected_index = combo.findData(selected)
            if selected_index < 0:
                combo.insertItem(combo.count() - 1, Path(selected).name, selected)
                selected_index = combo.findData(selected)
            combo.setCurrentIndex(selected_index)
            self._calibration_previous_indices[row] = selected_index
        else:
            combo.setCurrentIndex(self._calibration_previous_indices[row])
        combo.blockSignals(False)

    def _row_name(self, path: Path) -> str:
        """Return what to call *path*: the session's own label, else its filename."""
        return self._labels.get(str(path)) or path.name

    def _build_category_map(self) -> None:
        """Map semantic labels to actual loader classes."""
        self._categories: list[tuple[str, SourceLoader]] = []
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
            if "pose3d_overlay2d" in roles or config.get("role") == "pose3d_overlay2d":
                for video in self._video_paths:
                    combo.addItem(
                        tr("3D pose and 2D overlay on {video}").format(video=Path(video).name),
                        ["pose3d_overlay2d", video],
                    )
            if "overlay2d" in roles or config.get("role") == "overlay2d":
                for video in self._video_paths:
                    combo.addItem(
                        tr("2D pose on {video}").format(video=Path(video).name),
                        ["overlay2d", video],
                    )
        if wanted == ["", ""]:
            wanted = self._declared_by_the_file(row, loader) or wanted
        index = combo.findData(wanted)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.setEnabled(combo.count() > 1)

    def _declared_by_the_file(self, row: int, loader: object) -> list[str] | None:
        """The pose use this file names for itself, when it names one.

        A tracking file whose name says which camera it came from has already
        answered the question the combo asks, and defaulting it to *Data
        channels* is how a pose file gets imported as eighty-one plotted
        columns. It still draws dots on the video -- the overlay accepts loose
        readers -- so everything looks right while nothing knows it is a pose:
        no schema, no corrections, and Fix Identities greyed out with no way to
        find out why.

        Only when it is unambiguous. One loaded video, or exactly one whose
        name this file is named after; several cameras and no match keeps the
        choice with the person, which is what the dialog is for.
        """
        if not isinstance(loader, type) or not issubclass(loader, TimeSeriesSource):
            return None
        if "overlay2d" not in loader.pose_roles():
            return None
        path = self._candidates[row][0]
        stems = {Path(video).stem: video for video in self._video_paths}
        named = match_label(path.stem, stems)
        if named is not None:
            return ["overlay2d", stems[named]]
        if len(self._video_paths) == 1:
            return ["overlay2d", self._video_paths[0]]
        return None

    def get_selections(
        self,
    ) -> list[tuple[Path, SourceLoader, dict | None]]:
        """Return the user-approved (Path, Loader, Config) tuples."""
        results = []
        for (path, _, config), combo, role_combo, calibration_combo in zip(
            self._candidates,
            self._combos,
            self._role_combos,
            self._calibration_combos,
            strict=True,
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
                calibration_path = calibration_combo.currentData()
                if isinstance(calibration_path, str):
                    chosen["xcp_path"] = calibration_path
                results.append((path, loader_cls, chosen if chosen or config is not None else None))
        return results
