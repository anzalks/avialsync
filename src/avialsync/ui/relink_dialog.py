"""Missing-file relink dialog shown when session files cannot be found."""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from avialsync.ui.i18n import tr
from avialsync.ui.tables import ThemedTable


class RelinkDialog(QDialog):
    """Lets the user relocate missing files referenced by a session.

    Shows a table of missing paths with a Browse button per row.
    Returns a mapping {original_path: new_path} for resolved entries.
    """

    def __init__(
        self,
        missing_paths: list[str],
        kind_labels: dict[str, str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Missing Files"))
        self.setMinimumWidth(600)
        self.setMinimumHeight(300)

        self._mapping: dict[str, str] = {}

        layout = QVBoxLayout(self)

        info = QLabel(
            tr(
                "The following files referenced by this session could not be found.\n"
                "Browse to one, and any others that moved with it are found in the "
                "same place. Open uses what you located; anything still missing is "
                "left out and reported."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._missing = list(missing_paths)
        self._table = ThemedTable(len(missing_paths), 4)
        self._table.setHorizontalHeaderLabels([tr("Type"), tr("Original Path"), tr("New Path"), ""])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        kind_labels = kind_labels or {}
        kind_names = {
            "video": tr("Video"),
            "sensor": tr("Data"),
            "imaging": tr("Imaging"),
            "trigger": tr("Trigger evidence"),
        }

        for row, orig in enumerate(missing_paths):
            kind = kind_labels.get(orig, "file")
            kind_item = QTableWidgetItem(kind_names.get(kind, kind))
            self._table.setItem(row, 0, kind_item)

            orig_item = QTableWidgetItem(orig)
            orig_item.setToolTip(orig)
            self._table.setItem(row, 1, orig_item)

            new_item = QTableWidgetItem("")
            self._table.setItem(row, 2, new_item)

            browse_btn = QPushButton(tr("Browse…"))
            browse_btn.setAccessibleName(tr("Locate {name}").format(name=Path(orig).name))
            browse_btn.clicked.connect(lambda _checked, r=row, o=orig: self._browse(r, o))
            self._table.setCellWidget(row, 3, browse_btn)

        layout.addWidget(self._table)

        # Two different outcomes, named as such: "Open" and "Skip Missing" both
        # just accepted, so the choice between them meant nothing.
        btn_box = QDialogButtonBox()
        self._open_btn = btn_box.addButton(
            tr("Open with Located Files"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._skip_btn = btn_box.addButton(
            tr("Open Without Missing Files"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._cancel_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._open_btn.setEnabled(False)

        self._open_btn.clicked.connect(self.accept)
        self._skip_btn.clicked.connect(self._open_without)
        self._cancel_btn.clicked.connect(self.reject)

        layout.addWidget(btn_box)

    def _open_without(self) -> None:
        self._mapping.clear()
        self.accept()

    def _browse(self, row: int, original: str) -> None:
        ext = Path(original).suffix
        if ext.lower() in (".mp4", ".mov", ".avi", ".mkv"):
            filter_str = tr("Video files (*{ext});;All files (*)").format(ext=ext)
        elif ext.lower() in (".csv", ".txt", ".tsv"):
            filter_str = tr("Data files (*{ext});;All files (*)").format(ext=ext)
        else:
            filter_str = tr("All files (*)")

        orig_parent = Path(original).parent
        start_dir = str(orig_parent) if orig_parent.exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Locate {name}").format(name=Path(original).name),
            start_dir,
            filter_str,
        )
        if path:
            self._resolve(row, original, path, chosen=True)
            self._resolve_siblings(original, path)

    def _resolve(self, row: int, original: str, path: str, *, chosen: bool) -> None:
        """Record *path* for *original* and say how it was found."""
        self._mapping[original] = path
        cell = self._table.item(row, 2)
        if cell is not None:
            cell.setText(path)
            notes = []
            if not chosen:
                notes.append(tr("Found where the file you located moved to."))
            if Path(path).name != Path(original).name:
                # Not refused -- renaming is legitimate -- but a fitted alignment
                # landing on the wrong camera is not something to find out later.
                notes.append(tr("A different file name: check it is the same recording."))
            cell.setToolTip("\n".join([path, *notes]))
        self._open_btn.setEnabled(True)

    def _resolve_siblings(self, original: str, chosen: str) -> None:
        """Find the other missing files where the one the user located moved to.

        A session's files usually move together (a renamed drive, a copied
        experiment folder), so one Browse per file was the slow way. The old
        and new paths share a tail; the differing heads are the move.
        """
        old_parts, new_parts = Path(original).parts, Path(chosen).parts
        shared = 0
        while (
            shared < min(len(old_parts), len(new_parts)) - 1
            and old_parts[-2 - shared] == new_parts[-2 - shared]
        ):
            shared += 1
        old_root = Path(*old_parts[: len(old_parts) - 1 - shared])
        new_root = Path(*new_parts[: len(new_parts) - 1 - shared])
        for row, other in enumerate(self._missing):
            if other in self._mapping:
                continue
            try:
                candidate = new_root / Path(other).relative_to(old_root)
            except ValueError:
                candidate = Path(chosen).parent / Path(other).name
            if candidate.exists():
                self._resolve(row, other, str(candidate), chosen=False)

    def resolved_mapping(self) -> dict[str, str]:
        """Return {original_path: new_path} for files the user relocated."""
        return dict(self._mapping)
