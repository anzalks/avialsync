"""Unit tests for core.inspection dataclasses (ImportReport, IntegrityFlags, SourceInspection)."""

from __future__ import annotations

import pytest

from kinochronix.core.inspection import (
    ImportReport,
    IntegrityFlags,
    SourceInspection,
)


class TestImportReport:
    def test_defaults(self):
        r = ImportReport()
        assert r.rows_parsed == 0
        assert r.gap_count == 0
        assert r.gap_locations == ()
        assert r.nan_count == 0

    def test_roundtrip(self):
        r = ImportReport(
            rows_parsed=1000,
            rows_dropped_duplicate=5,
            rows_dropped_nonmonotonic=2,
            gap_count=3,
            nan_count=7,
            sentinel_count=1,
            gap_locations=(1.5, 2.3, 4.7),
            import_timestamp=1700000000.0,
        )
        assert ImportReport.from_dict(r.as_dict()) == r

    def test_empty_roundtrip(self):
        r = ImportReport()
        assert ImportReport.from_dict(r.as_dict()) == r

    def test_as_dict_keys(self):
        d = ImportReport().as_dict()
        assert "rows_parsed" in d
        assert "gap_locations" in d
        assert "import_timestamp" in d

    def test_from_dict_partial(self):
        """from_dict must tolerate a dict with only some keys (e.g. older data)."""
        r = ImportReport.from_dict({"rows_parsed": 42})
        assert r.rows_parsed == 42
        assert r.gap_count == 0


class TestIntegrityFlags:
    def test_defaults_no_flag(self):
        f = IntegrityFlags()
        assert not f.any_flag
        assert f.flag_labels() == []

    def test_any_flag(self):
        f = IntegrityFlags(is_vfr=True)
        assert f.any_flag

    def test_flag_labels_content(self):
        f = IntegrityFlags(is_vfr=True, fps_mismatch=True)
        labels = f.flag_labels()
        assert len(labels) == 2
        assert any("vfr" in lbl.lower() or "variable" in lbl.lower() for lbl in labels)

    def test_roundtrip(self):
        f = IntegrityFlags(is_vfr=True, has_gaps=True, drift_nonzero=False)
        assert IntegrityFlags.from_dict(f.as_dict()) == f

    def test_from_dict_defaults(self):
        f = IntegrityFlags.from_dict({})
        assert not f.any_flag

    def test_frozen(self):
        f = IntegrityFlags()
        with pytest.raises((TypeError, AttributeError)):
            f.is_vfr = True  # type: ignore[misc]


class TestSourceInspection:
    def test_defaults(self):
        ins = SourceInspection(path="/tmp/test.csv")
        assert ins.loader_id == ""
        assert ins.import_report is None
        assert not ins.integrity_flags.any_flag

    def test_roundtrip_minimal(self):
        ins = SourceInspection(path="/tmp/test.csv")
        restored = SourceInspection.from_dict(ins.as_dict())
        assert restored.path == ins.path
        assert restored.loader_id == ins.loader_id

    def test_roundtrip_full(self):
        ins = SourceInspection(
            path="/data/sensors.csv",
            loader_id="CSVLoader",
            import_config={"sep": ",", "time_col": "t"},
            import_report=ImportReport(rows_parsed=500, gap_count=2),
            integrity_flags=IntegrityFlags(has_gaps=True),
            fps_binding="bound:/data/cam.mp4",
        )
        d = ins.as_dict()
        restored = SourceInspection.from_dict(d)
        assert restored.path == ins.path
        assert restored.loader_id == ins.loader_id
        assert restored.import_config == ins.import_config
        assert restored.import_report == ins.import_report
        assert restored.integrity_flags == ins.integrity_flags
        assert restored.fps_binding == ins.fps_binding

    def test_as_dict_contains_version(self):
        ins = SourceInspection(path="/x.csv")
        d = ins.as_dict()
        assert "path" in d

    def test_from_dict_no_report(self):
        ins = SourceInspection.from_dict({"path": "/y.csv"})
        assert ins.import_report is None

    def test_import_config_is_mutable(self):
        """SourceInspection is not frozen — its dict field must be mutable."""
        ins = SourceInspection(path="/z.csv", import_config={"k": "v"})
        ins.import_config["extra"] = 1
        assert ins.import_config["extra"] == 1
