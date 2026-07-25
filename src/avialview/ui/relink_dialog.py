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
        self.setWindowTitle("Missing Files")
        self.setMinimumWidth(600)
        self.setMinimumHeight(300)

        self._mapping: dict[str, str] = {}

        layout = QVBoxLayout(self)

        info = QLabel(
            "The following files referenced by this session could not be found.\n"
            "Use the Browse button to locate each file, or press Skip to open "
            "the session without them."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._table = QTableWidget(len(missing_paths), 4)
        self._table.setHorizontalHeaderLabels(["Type", "Original Path", "New Path", ""])
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

        for row, orig in enumerate(missing_paths):
            kind = kind_labels.get(orig, "file")
            kind_item = QTableWidgetItem(kind)
            self._table.setItem(row, 0, kind_item)

            orig_item = QTableWidgetItem(orig)
            orig_item.setToolTip(orig)
            self._table.setItem(row, 1, orig_item)

            new_item = QTableWidgetItem("")
            self._table.setItem(row, 2, new_item)

            browse_btn = QPushButton("Browse…")
            browse_btn.clicked.connect(lambda _checked, r=row, o=orig: self._browse(r, o))
            self._table.setCellWidget(row, 3, browse_btn)

        layout.addWidget(self._table)

        btn_box = QDialogButtonBox()
        self._open_btn = btn_box.addButton("Open", QDialogButtonBox.ButtonRole.AcceptRole)
        self._skip_btn = btn_box.addButton("Skip Missing", QDialogButtonBox.ButtonRole.AcceptRole)
        self._cancel_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)

        self._open_btn.clicked.connect(self.accept)
        self._skip_btn.clicked.connect(self.accept)
        self._cancel_btn.clicked.connect(self.reject)

        layout.addWidget(btn_box)

    def _browse(self, row: int, original: str) -> None:
        ext = Path(original).suffix
        if ext.lower() in (".mp4", ".mov", ".avi", ".mkv"):
            filter_str = f"Video files (*{ext});;All files (*)"
        elif ext.lower() in (".csv", ".txt", ".tsv"):
            filter_str = f"Data files (*{ext});;All files (*)"
        else:
            filter_str = "All files (*)"

        orig_parent = Path(original).parent
        start_dir = str(orig_parent) if orig_parent.exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Locate {Path(original).name}",
            start_dir,
            filter_str,
        )
        if path:
            self._mapping[original] = path
            self._table.item(row, 2).setText(path)

    def resolved_mapping(self) -> dict[str, str]:
        """Return {original_path: new_path} for files the user relocated."""
        return dict(self._mapping)
