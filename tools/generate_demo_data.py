"""Generate the same complete demo dataset used by ``avialview demo``."""

from pathlib import Path

from avialview.demo import DemoData, _has_header, _write_tracking, ensure_demo_data


def _make_pose_csv(path: Path) -> None:
    """Compatibility wrapper for tests and downstream development scripts."""
    _write_tracking(path)


def _is_dlc_pose_csv(path: Path) -> bool:
    """Return whether a pose file satisfies the demo's DLC header contract."""
    return _has_header(path, ",".join(["scorer"] + ["DLC"] * 20))


def main() -> DemoData:
    """Generate fixtures under ``examples/data`` and print reusable progress."""
    output = Path(__file__).resolve().parent.parent / "examples" / "data"
    data = ensure_demo_data(
        lambda value, message: print(f"[{value:3d}%] {message}"),
        directory=output,
    )
    print(f"Demo data ready in {output}")
    return data


if __name__ == "__main__":
    main()
