"""Exported provenance must reconstruct the mapping that produced timestamps."""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.artifact_provenance import record
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.errors import SyncEvidenceError
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.session import SyncProvenance
from avialsync.core.timeline import TimeMap
from avialsync.core.video_timing import frame_index_at
from avialsync.engine.export import _time_maps, export_data_slice_csv
from avialsync.engine.export_worker import DataExportWorker, ReaderReference


def test_affine_export_distinguishes_reference_times() -> None:
    first, second = TimeMap(), TimeMap()
    first.set_mapping(0.0, 3600.0, t_ref=0.0)
    second.set_mapping(0.0, 3600.0, t_ref=100.0)
    left = _time_maps([SimpleNamespace(source_id="source.csv", time_map=first)])
    right = _time_maps([SimpleNamespace(source_id="source.csv", time_map=second)])
    assert left != right
    restored = TimeMap.from_record(json.loads(json.dumps(right["source.csv"])))
    assert restored.to_source(101.0) == second.to_source(101.0)


def test_exact_export_distinguishes_nonlinear_evidence() -> None:
    first, second = TimeMap(), TimeMap()
    master = np.array([0.0, 1.0, 2.0])
    first.set_exact_mapping(master, master)
    second.set_exact_mapping(master, np.array([0.0, 1.1, 2.0]))
    left = _time_maps([SimpleNamespace(source_id="source.csv", time_map=first)])
    right = _time_maps([SimpleNamespace(source_id="source.csv", time_map=second)])
    assert left != right
    restored = TimeMap.from_record(json.loads(json.dumps(right["source.csv"])))
    assert restored.has_exact_mapping
    np.testing.assert_allclose(restored.to_source_array(master), [0.0, 1.1, 2.0])
    pts = np.arange(21, dtype=np.float64) / 10.0
    assert frame_index_at(pts, restored.to_source(1.0)) == 11


def test_dynamic_drift_anchor_round_trips_without_a_jump() -> None:
    mapping = TimeMap(0.25, 25.0)
    mapping.update(0.5, 40.0, 1000.0)
    restored = TimeMap.from_record(mapping.to_record())
    np.testing.assert_allclose(
        restored.to_source_array(np.array([0.0, 500.0, 1000.0, 2000.0])),
        mapping.to_source_array(np.array([0.0, 500.0, 1000.0, 2000.0])),
        rtol=0.0,
        atol=1e-12,
    )
    assert restored.offset == mapping.offset


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("mapping_version", 2),
        ("kind", "guessed"),
        ("reference_seconds", float("nan")),
        ("base_offset_seconds", float("inf")),
        ("offset_seconds", True),
        ("drift_ms_per_hour", "25"),
    ],
)
def test_invalid_mapping_records_are_rejected(key: str, value: object) -> None:
    payload = TimeMap().to_record()
    payload[key] = value
    with pytest.raises(SyncEvidenceError):
        TimeMap.from_record(payload)


def test_missing_mapping_fields_are_rejected() -> None:
    with pytest.raises(SyncEvidenceError):
        TimeMap.from_record({})


@pytest.mark.parametrize("source", [[0.0, 0.0], [1.0, 0.0], [0.0], [0.0, float("nan")]])
def test_invalid_exact_mapping_records_are_rejected(source: list[float]) -> None:
    mapping = TimeMap()
    mapping.set_exact_mapping(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    payload = mapping.to_record()
    payload["source_seconds"] = source
    with pytest.raises(SyncEvidenceError):
        TimeMap.from_record(payload)


def test_source_identity_and_sampled_fingerprint_distinguish_equal_names(tmp_path: Path) -> None:
    first, second = tmp_path / "first" / "signal.csv", tmp_path / "second" / "signal.csv"
    for path, content in [(first, "0,1\n"), (second, "0,2\n")]:
        path.parent.mkdir()
        path.write_text(content, encoding="utf-8")
    sources = record("data-slice-csv", [first, second])["sources"]
    assert sources[0]["name"] == sources[1]["name"]
    assert sources[0]["path"] != sources[1]["path"]
    assert sources[0]["fingerprint"] != sources[1]["fingerprint"]
    assert sources[0]["fingerprint_algorithm"] == "xxh64-first-middle-last-64KiB"


def test_unavailable_source_is_identified_without_an_invented_fingerprint(tmp_path: Path) -> None:
    source = record("snapshot", [tmp_path / "missing.mp4"])["sources"][0]
    assert source["size_bytes"] is None
    assert source["fingerprint"] is None


def test_many_channels_serialize_one_source_mapping_once() -> None:
    class CountingMapping(TimeMap):
        calls = 0

        def to_record(self) -> dict:
            self.calls += 1
            return super().to_record()

    mapping = CountingMapping()
    readers = [SimpleNamespace(source_id="signal.csv", time_map=mapping) for _ in range(128)]
    assert len(_time_maps(readers)) == 1
    assert mapping.calls == 1


def test_equal_channel_and_source_names_remain_identifiable_in_csv(tmp_path: Path) -> None:
    readers = []
    for index in range(2):
        source = tmp_path / str(index) / "signal.csv"
        source.parent.mkdir()
        source.write_text(f"{index}\n", encoding="utf-8")
        cache = source.parent / "cache"
        cache.mkdir()
        PyramidBuilder(cache, "signal").build_and_save(
            np.array([0.0, 1.0]), np.array([float(index), float(index)])
        )
        readers.append(MappedChannelReader(PyramidReader(cache, "signal"), source_id=str(source)))
    output = tmp_path / "slice.csv"
    export_data_slice_csv(readers, 0.0, 1.0, output)
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    identities = [
        row[0].removeprefix("# Source ID: ")
        for row in rows
        if row and row[0].startswith("# Source ID:")
    ]
    payload = json.loads(rows[-1][0].removeprefix("# avialsync: "))
    assert identities == [reader.source_id for reader in readers]
    assert set(identities) == set(payload["time_maps"])


def test_export_worker_preserves_accepted_raw_evidence_and_precision(tmp_path: Path) -> None:
    source = tmp_path / "signal.csv"
    source.write_text("original", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    PyramidBuilder(cache, "signal").build_and_save(np.array([0.0, 1.0]), np.array([2.0, 3.0]))
    evidence = SyncProvenance(
        "reference.csv",
        str(source),
        0.0,
        0.0,
        0.001,
        0.002,
        3,
        1,
        0.005,
        matches=[{"reference_time": 0.0, "target_time": 0.0}],
        precision_requirement=0.005,
        precision_verified=True,
    )
    output = tmp_path / "export.csv"
    worker = DataExportWorker(
        [ReaderReference(cache, "signal", source_id=str(source))],
        0.0,
        1.0,
        output,
        alignment_evidence=(dataclasses.replace(evidence),),
    )
    evidence.superseded_by = "manual"
    worker.run()
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    saved = json.loads(rows[-1][0].removeprefix("# avialsync: "))["alignment_evidence"][0]
    assert saved["matches"] == [{"reference_time": 0.0, "target_time": 0.0}]
    assert saved["precision_verified"] is True
    assert saved["superseded_by"] == ""
