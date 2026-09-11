"""The badge that was computed and thrown away.

`ui/quality_badge.py` was written in Phase 7 to answer "what is worth knowing
about this source", including a "No accepted alignment" finding put there for
the purpose. Nothing in `src/` imported it. The badge that shipped read
`inspection.integrity_flags`, which describes the *file* and structurally
cannot know whether a source has been aligned -- so the "data dirty" half of
architecture rule 10 and WP-10's persistent confidence badge had no display.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.inspection import SourceInspection
from avialsync.core.session import SyncProvenance
from avialsync.core.sync import AlignmentMethod
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sidebar import VideoInfoWidget

CAMERA = "/tmp/cam1.mp4"


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


@pytest.fixture
def widget(qtbot) -> VideoInfoWidget:
    w = VideoInfoWidget(CAMERA, {})
    qtbot.addWidget(w)
    return w


class TestTheBadgeSaysWhatTheFileCannot:
    def test_an_unaligned_source_is_reported_as_unaligned(self, widget: VideoInfoWidget) -> None:
        """A clean file with no accepted alignment still has something to say."""
        widget.set_inspection(SourceInspection(path=CAMERA))
        widget.set_alignment("no accepted alignment", accepted=False)

        assert widget._badge_btn.isVisible() or widget._badge_btn.toolTip()
        assert "No accepted alignment" in widget._badge_btn.toolTip()

    def test_an_aligned_source_stops_saying_it(self, widget: VideoInfoWidget) -> None:
        widget.set_inspection(SourceInspection(path=CAMERA))
        widget.set_alignment("aligned to ephys.csv", accepted=True)

        assert "No accepted alignment" not in widget._badge_btn.toolTip()

    def test_the_alignment_summary_reaches_the_tooltip(self, widget: VideoInfoWidget) -> None:
        """Not only that it is unaligned -- how, when it is."""
        widget.set_inspection(SourceInspection(path=CAMERA))
        widget.set_alignment("set by hand: offset +1.250000 s", accepted=False)

        assert "set by hand" in widget._badge_btn.toolTip()

    def test_a_screen_reader_gets_the_findings_too(self, widget: VideoInfoWidget) -> None:
        """Rule 17: a coloured glyph is not a report."""
        widget.set_inspection(SourceInspection(path=CAMERA))
        widget.set_alignment("no accepted alignment", accepted=False)

        assert widget._badge_btn.accessibleDescription()

    def test_order_of_arrival_does_not_matter(self, widget: VideoInfoWidget) -> None:
        """Inspection and alignment arrive from different subsystems, and which
        lands first depends on how fast a probe returned."""
        widget.set_alignment("no accepted alignment", accepted=False)
        widget.set_inspection(SourceInspection(path=CAMERA))

        assert "No accepted alignment" in widget._badge_btn.toolTip()


class TestTheWindowKeepsItCurrent:
    def test_superseded_evidence_does_not_count_as_aligned(self, window: MainWindow) -> None:
        """A source a person moved by hand sits somewhere legitimate, and that
        is an entirely different claim from a fit nobody has contradicted."""
        window._sync_provenance.append(
            SyncProvenance(
                reference_id="/tmp/ephys.csv",
                target_id=CAMERA,
                offset=1.0,
                drift_ppm=0.0,
                rms_residual=0.001,
                max_residual=0.003,
                matched_count=47,
                rejected_count=1,
                tolerance=0.005,
            )
        )
        assert window._has_live_alignment(CAMERA)

        window._recorded_mappings[CAMERA] = (1.0, 0.0)
        window._record_mapping_change(CAMERA, 1.2, 0.0)

        assert not window._has_live_alignment(CAMERA)

    def test_a_manual_mapping_counts_as_an_alignment_it_just_says_so(
        self, window: MainWindow
    ) -> None:
        window._sync_provenance.append(
            SyncProvenance(
                reference_id="/tmp/ephys.csv",
                target_id=CAMERA,
                offset=1.25,
                drift_ppm=0.0,
                rms_residual=0.0,
                max_residual=0.0,
                matched_count=0,
                rejected_count=0,
                tolerance=0.0,
                method=AlignmentMethod.MANUAL,
            )
        )

        assert window._has_live_alignment(CAMERA)
        assert "set by hand" in window.alignment_confidence(CAMERA)

    def test_refreshing_with_nothing_loaded_is_harmless(self, window: MainWindow) -> None:
        """It runs on session restore, before any source has arrived."""
        window.refresh_alignment_badges()
