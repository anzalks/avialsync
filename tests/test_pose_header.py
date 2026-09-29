"""The one parser for a DLC / LightningPose header block."""

from pathlib import Path

from avialsync.core.pose_header import parse_pose_header, read_pose_header

SINGLE = [
    "scorer,DLC,DLC,DLC",
    "bodyparts,nose,nose,nose",
    "coords,x,y,likelihood",
    "0,1.0,2.0,0.9",
]

MULTI = [
    "scorer,DLC,DLC,DLC,DLC,DLC,DLC,DLC,DLC,DLC",
    "individuals,mouseA,mouseA,mouseA,mouseB,mouseB,mouseB,single,single,single",
    "bodyparts,snout,snout,snout,snout,snout,snout,corner,corner,corner",
    "coords,x,y,likelihood,x,y,likelihood,x,y,likelihood",
    "0,1.0,2.0,0.9,3.0,4.0,0.8,5.0,6.0,0.7",
]


def _write(tmp_path: Path, lines: list[str], name: str = "pose.csv") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_single_animal_header_is_three_rows(tmp_path: Path) -> None:
    header = read_pose_header(_write(tmp_path, SINGLE))

    assert header is not None
    assert header.rows == 3
    assert header.multi_animal is False
    assert header.flat_names() == ["frame_index", "nose_x", "nose_y", "nose_likelihood"]


def test_multi_animal_header_is_four_rows_and_names_the_individual(tmp_path: Path) -> None:
    header = read_pose_header(_write(tmp_path, MULTI))

    assert header is not None
    assert header.rows == 4
    assert header.multi_animal is True
    assert header.flat_names() == [
        "frame_index",
        "mouseA_snout_x",
        "mouseA_snout_y",
        "mouseA_snout_likelihood",
        "mouseB_snout_x",
        "mouseB_snout_y",
        "mouseB_snout_likelihood",
        "single_corner_x",
        "single_corner_y",
        "single_corner_likelihood",
    ]


def test_repeated_body_part_keeps_one_column_per_individual(tmp_path: Path) -> None:
    """The failure this exists to prevent: two mice collapsing into one point."""
    header = read_pose_header(_write(tmp_path, MULTI))

    assert header is not None
    index = header.column_index()
    assert index[("mouseA_snout", "x")] == 1
    assert index[("mouseB_snout", "x")] == 4
    assert index[("mouseA_snout", "likelihood")] == 3


def test_non_pose_csv_is_not_claimed(tmp_path: Path) -> None:
    path = _write(tmp_path, ["time,voltage", "0.0,1.0", "0.1,2.0"], name="signal.csv")

    assert read_pose_header(path) is None


def test_missing_file_is_not_claimed(tmp_path: Path) -> None:
    assert read_pose_header(tmp_path / "absent.csv") is None


def test_individuals_row_without_the_rest_is_not_claimed() -> None:
    assert parse_pose_header([line.split(",") for line in MULTI[:2] + ["0,1.0"]]) is None


def test_unnamed_column_is_left_unnamed_rather_than_borrowing_its_neighbour() -> None:
    lines = [
        "scorer,DLC,DLC,DLC",
        "bodyparts,nose,nose,",
        "coords,x,y,",
        "0,1.0,2.0,",
    ]
    header = parse_pose_header([line.split(",") for line in lines])

    assert header is not None
    # Distinct names, and nothing that collides with the index column: a reader
    # handed two columns called the same thing keeps one of them, silently.
    names = header.flat_names()
    assert names[:3] == ["frame_index", "nose_x", "nose_y"]
    assert len(set(names)) == len(names)
    assert header.named_columns() == ["nose_x", "nose_y"]
