"""Collapsible source-properties panels for VideoInfoWidget and SensorInfoWidget (D-020).

VideoPropertiesPanel: extended video metadata (codec, resolution, fps, file size, …).
SensorPropertiesPanel: channel metadata, cache status, import provenance.

Both implement as_plain_text() for the Copy-as-text button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialview.core.inspection import SourceInspection
from avialview.core.source import VideoMetadata

if TYPE_CHECKING:
    pass


def _row(label: str, value: str) -> tuple[str, str]:
    return label, value


class _PropertiesBase(QGroupBox):
    """Shared skeleton: collapsible section with a Copy button."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        hdr = QHBoxLayout()
        self._toggle_btn = QPushButton("▶ " + title)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet("text-align:left;")
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._toggle_btn, stretch=1)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setFixedWidth(44)
        self._copy_btn.setToolTip("Copy properties as plain text")
        self._copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.as_plain_text())
        )
        hdr.addWidget(self._copy_btn)
        outer.addLayout(hdr)

        self._body = QWidget()
        self._form = QFormLayout(self._body)
        self._form.setContentsMargins(4, 2, 4, 2)
        self._form.setSpacing(2)
        self._body.setVisible(False)
        outer.addWidget(self._body)

        self._rows: list[tuple[str, QLabel]] = []
        self._title = title

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        arrow = "▼" if not self._collapsed else "▶"
        self._toggle_btn.setText(f"{arrow} {self._title}")

    def _add_row(self, label: str, value: str) -> QLabel:
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #888;")
        val = QLabel(value)
        val.setWordWrap(True)
        self._form.addRow(lbl, val)
        self._rows.append((label, val))
        return val

    def _update_row(self, label: str, value: str) -> None:
        for lbl, val in self._rows:
            if lbl == label:
                val.setText(value)
                return

    def as_plain_text(self) -> str:
        lines = [self._title, "=" * len(self._title)]
        for lbl, val in self._rows:
            lines.append(f"{lbl:<26}{val.text()}")
        return "\n".join(lines)


class VideoPropertiesPanel(_PropertiesBase):
    """Collapsible properties panel for one video source."""

    def __init__(self, loader: Any, parent: QWidget | None = None) -> None:
        super().__init__("Video Properties", parent)
        self._loader = loader
        self._pane: Any = None  # VideoPane ref for live mpv properties
        self._populate()

    def _populate(self) -> None:
        lo = self._loader
        metadata = lo.video_metadata() if hasattr(lo, "video_metadata") else None
        if not isinstance(metadata, VideoMetadata):
            metadata = VideoMetadata(
                container=getattr(lo, "_container", ""),
                codec=getattr(lo, "_codec", "unknown"),
                profile=getattr(lo, "_profile", ""),
                pixel_format=getattr(lo, "_pix_fmt", ""),
                width=getattr(lo, "_width", 0),
                height=getattr(lo, "_height", 0),
                nominal_fps=getattr(lo, "_fps", 0.0),
                frame_count=getattr(lo, "_frame_count", None),
                duration=getattr(lo, "_duration", 0.0),
                start_time=getattr(lo, "_start_time", None),
                file_size_bytes=getattr(lo, "_file_size", 0),
            )
        self._metadata = metadata
        self._add_row("Container", metadata.container or "—")
        self._add_row("Codec", metadata.codec or "—")
        self._add_row("Profile", metadata.profile or "—")
        self._add_row("Pixel format", metadata.pixel_format or "—")
        w = metadata.width
        h = metadata.height
        self._add_row("Resolution", f"{w}×{h}" if w and h else "—")
        self._add_row("Timing", "VFR" if metadata.is_vfr else "CFR")
        self._add_row("Nominal CFR", f"{metadata.nominal_fps:.3f} fps")
        if metadata.is_vfr:
            measured = (
                f"{metadata.measured_fps:.3f} fps average "
                f"({metadata.min_frame_rate:.3f}–{metadata.max_frame_rate:.3f})"
            )
        else:
            measured = f"{metadata.measured_fps:.3f} fps"
        self._add_row("Timestamp rate", measured)
        self._add_row("Decoder fps", "—")
        self._add_row("Decode mode", "—")
        fc = metadata.frame_count
        self._add_row("Frame count", str(fc) if fc is not None else "—")
        self._add_row("Duration", f"{metadata.duration:.3f} s")
        st = metadata.start_time
        self._add_row("Metadata start", f"{st:.6f} s" if st is not None else "—")
        sz = metadata.file_size_bytes
        self._add_row("File size", f"{sz / 1_048_576:.1f} MB" if sz else "—")
        self._add_row("Drift (ppm)", "—")

    def set_pane(self, pane: Any) -> None:
        self._pane = pane

    def refresh_live(self) -> None:
        """Read live mpv properties; call when the panel is expanded."""
        if self._pane is None or self._pane.mpv is None:
            return
        fps = getattr(self._pane.mpv, "estimated_vf_fps", None) or 0.0
        self._update_row("Decoder fps", f"{fps:.3f}")
        hw = str(getattr(self._pane.mpv, "hwdec_current", "") or "software")
        self._update_row("Decode mode", hw)

    def _toggle(self) -> None:
        super()._toggle()
        if not self._collapsed:
            self.refresh_live()

    def set_drift(self, drift_ppm: float) -> None:
        label = f"{drift_ppm:+.2f} ppm" if drift_ppm != 0.0 else "0 ppm"
        self._update_row("Drift (ppm)", label)


class SensorPropertiesPanel(_PropertiesBase):
    """Collapsible properties panel for one data source."""

    def __init__(
        self,
        inspection: SourceInspection,
        channel_infos: list[Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Sensor Properties", parent)
        self._inspection = inspection
        self._populate(channel_infos or [])

    def _populate(self, channel_infos: list[Any]) -> None:
        ins = self._inspection
        # This is provenance, not a path operation.  Preserve the serialized
        # spelling so a session created on another OS remains inspectable.
        self._add_row("Path", ins.path)
        self._add_row("Loader", ins.loader_id or "—")
        self._add_row("FPS binding", ins.fps_binding or "—")

        if channel_infos:
            ch_lines = "; ".join(
                f"{c.name}" + (f" ({c.unit})" if getattr(c, "unit", "") else "")
                for c in channel_infos
            )
            self._add_row("Channels", ch_lines)
            rates = list(
                {getattr(c, "rate_hz", None) for c in channel_infos if getattr(c, "rate_hz", None)}
            )
            self._add_row("Sample rate", f"{rates[0]:,.0f} Hz" if len(rates) == 1 else "mixed")
        else:
            self._add_row("Channels", "—")
            self._add_row("Sample rate", "—")

        rep = ins.import_report
        if rep:
            import datetime as _dt

            ts = _dt.datetime.fromtimestamp(rep.import_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            self._add_row("Imported at", ts)
            self._add_row("Rows parsed", f"{rep.rows_parsed:,}")
            self._add_row("NaN values", f"{rep.nan_count:,}")
            self._add_row("Gaps", str(rep.gap_count))
        else:
            self._add_row("Imported at", "—")
            self._add_row("Rows parsed", "—")
            self._add_row("NaN values", "—")
            self._add_row("Gaps", "—")

        flags = ins.integrity_flags
        flag_text = "; ".join(flags.flag_labels()) if flags.any_flag else "none"
        self._add_row("Integrity", flag_text)

    def update_inspection(self, inspection: SourceInspection) -> None:
        self._inspection = inspection
        # Rebuild body completely
        while self._form.rowCount():
            self._form.removeRow(0)
        self._rows.clear()
        self._populate([])
