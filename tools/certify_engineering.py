"""Run fixture-backed engineering certification in isolated application processes."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run_case(
    output: Path, name: str, selection: str, environment: dict[str, str]
) -> dict[str, Any]:
    """Run one isolated pytest scenario and retain its raw measurements."""
    report = output / f"{name}.json"
    command = [
        sys.executable,
        "-m",
        "pytest",
        selection,
        "-x",
        "-q",
        "--benchmark-only",
        "--benchmark-save-data",
        f"--benchmark-json={report}",
    ]
    result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if not report.exists():
        return {"exit_code": result.returncode, "report": str(report)}
    payload = json.loads(report.read_text(encoding="utf-8"))
    measurements = []
    import numpy as np

    for benchmark in payload.get("benchmarks", []):
        samples = benchmark["stats"].get("data", [])
        measurements.append(
            {
                "name": benchmark["name"],
                "rounds": len(samples),
                "mean_ms": float(np.mean(samples) * 1000),
                "p50_ms": float(np.percentile(samples, 50) * 1000),
                "p95_ms": float(np.percentile(samples, 95) * 1000),
                "p99_ms": float(np.percentile(samples, 99) * 1000),
                "maximum_ms": max(samples) * 1000,
                **benchmark.get("extra_info", {}),
            }
        )
    return {"exit_code": result.returncode, "report": str(report), "measurements": measurements}


def main() -> int:
    """Generate fixtures before launching separately measured application processes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-bytes", type=int, default=1_000_000_000)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from tools.make_fixtures import generate_certification_signal

    source = output / "fixture.csv"
    fixture = generate_certification_signal(source, args.target_bytes)
    (output / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    env = dict(os.environ)
    env.update({"QT_QPA_PLATFORM": "offscreen", "AVIALSYNC_CERTIFICATION_ROOT": str(output)})
    cases = [
        (
            "import",
            "tests/benchmarks/test_bench_certification.py::test_certification_cold_import_and_warm_reopen",
        ),
        (
            "frames",
            "tests/benchmarks/test_bench_certification.py::test_certification_three_camera_painted_seek",
        ),
        *[
            (
                f"plots-{count}",
                f"tests/benchmarks/test_bench_certification.py::test_certification_populated_interactions[{count}]",
            )
            for count in (4, 32, 128)
        ],
    ]
    records = {name: run_case(output, name, test, env) for name, test in cases}
    from avialsync import __version__

    result = {
        "software": {
            "avialsync": __version__,
            "python": platform.python_version(),
            **{name: version(name) for name in ("PySide6", "numpy", "av", "polars")},
        },
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "fixture": fixture,
        "cases": records,
        "measurement_scope": (
            "Each scenario has its own application/test process. Process peak RSS excludes "
            "fixture generation. Qt renders offscreen; no native-compositor or field-data "
            "certification is claimed."
        ),
    }
    target = output / "certification.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Certification measurements: {target}")
    return int(any(value["exit_code"] for value in records.values()))


if __name__ == "__main__":
    raise SystemExit(main())
