"""Portable record ownership keeps collisions, future schemas and malformed tombstones intact."""

from pathlib import Path

import pytest

from avialsync.core import identity_sidecar, point_edit_sidecar, prop_file
from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import Ladder


@pytest.mark.parametrize("sidecar", [identity_sidecar, point_edit_sidecar])
def test_blank_lines_and_unrecognized_comments_preserve_readable_records(
    tmp_path: Path, sidecar
) -> None:
    source = tmp_path / "pose.csv"
    if sidecar is identity_sidecar:
        text = "frame,group,lane_a,lane_b,parts\n1,animals,a,b,head\n"
    else:
        text = "frame,bodypart,x,y\n1,head,2,3\n"
    sidecar.sidecar_path(source).write_text("\n# future: value\n\n" + text)
    result = sidecar.read(source)
    assert result is not None and result.skipped == 0


def test_future_existing_prop_is_never_overwritten(tmp_path: Path) -> None:
    target = prop_file.prop_path(tmp_path, "ladder")
    text = 'format="future/2"\n[prop]\nversion=1\nkind="ladder"\nname="ladder"\nremoved=false\n'
    target.write_text(text)
    with pytest.raises(PropModelError, match="unreadable"):
        prop_file.write_ladder(tmp_path, Ladder("ladder"))
    assert target.read_text() == text


def test_case_sensitive_folder_collisions_are_portably_detected(
    tmp_path: Path, monkeypatch
) -> None:
    existing = prop_file.prop_path(tmp_path, "lower")
    existing.write_text("another record")
    target = prop_file.prop_path(tmp_path, "LOWER")
    exists = Path.exists
    # Model a case-sensitive recording volume, including on Windows/macOS.
    monkeypatch.setattr(Path, "exists", lambda path: False if path == target else exists(path))
    with pytest.raises(PropModelError, match="already uses"):
        prop_file.write_ladder(tmp_path, Ladder("LOWER"))
    assert existing.read_text() == "another record"


def test_duplicate_case_folded_records_keep_one_and_report_the_other(
    tmp_path: Path, monkeypatch
) -> None:
    paths = [prop_file.prop_path(tmp_path, "ladder"), prop_file.prop_path(tmp_path, "LADDER")]
    monkeypatch.setattr(Path, "glob", lambda path, pattern: iter(paths))
    monkeypatch.setattr(
        prop_file,
        "read_text",
        lambda path: (
            f'[prop]\nversion=1\nkind="ladder"\nname="{path.name[: -len(prop_file.PROP_SUFFIX)]}"\n'
        ),
    )
    props, issues, removed = prop_file.read_prop_records(tmp_path)
    assert len(props) == 1 and not removed and issues[0].reason == "name_mismatch"


def test_conflicting_wheel_and_future_tombstones_do_not_become_props(tmp_path: Path) -> None:
    bad = tmp_path / "wheel_prop.toml"
    bad.write_text('[prop]\nversion=1\nkind="wheel"\nname="wheel"\n[wheel]\nremoved=true\n')
    future = tmp_path / "future_prop.toml"
    future.write_text('[prop]\nversion=1\nkind="future"\nname="future"\nremoved=true\n')
    props, issues, removed = prop_file.read_prop_records(tmp_path)
    assert not props and not removed
    assert any(issue.reason == "damaged" for issue in issues)
    assert future.exists() and bad.exists()
