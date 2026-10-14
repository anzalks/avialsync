# Performance verification

Correctness runs on every supported operating system. Timing certification runs locally because
the machine and its storage affect the result. Neither a passing component mean nor a headless
build certifies the complete application on a scientist's computer.

## Requirements and measurements

The requirements in `BLUEPRINT.md` remain unchanged: 2.5 seconds to build a 180-million-sample
pyramid, 5 milliseconds to query it, 2 milliseconds for a populated cursor update or a 128-point
3D sample, 16 milliseconds for a plot frame, and 250 milliseconds for synchronization preview
or a three-camera exact seek. A cached three-camera/four-channel session should open in 3 seconds;
a 1 GB CSV should import with progress within 60 seconds. UI callbacks have a 30 millisecond
hard ceiling and an 8 millisecond target.

The [2026-10-14 local measurement report](engineering-certification.md) records a real 1 GB,
four-channel 50 kHz import, five cached reopens, sixty painted three-camera seeks, and sixty
mixed interactions each with 4, 32 and 128 populated channels. It includes p50/p95/p99, maxima,
Qt heartbeat gaps and process peak RSS. Fixture generation runs outside each measured application
process. The report also records its limits: a 32 GB macOS machine, synthetic recordings and
offscreen rendering. Native desktop, Windows/Linux speed, private field data and a 16 GB machine
remain external checks.

Mean cursor and paint costs pass their local component budgets. Resize/event-delivery tails and
heartbeat gaps exceed the responsiveness target, especially at 128 channels. Those observations
remain visible in the report; this is not a certification that every UI callback or full
pan/zoom-to-paint interaction meets its requirement.

## Work ownership

- `MasterClock` advances from monotonic elapsed time and never waits for a decoder.
- Each video pane has a decode worker. Playback retains only the latest request and drops frames
  to preserve synchronization; paused seeks select the exact presentation interval.
- Imports, cache construction, session IO, exports, synchronization and diagnostics use registered
  background jobs. Parser staging is chunked and cache replacement is recoverable.
- Plot workers query bounded mmap pyramid slices. UI installation is sliced, resize/window
  requests coalesce, and offscreen rows defer graphics updates until they are revealed.
- Culled cursor pixels are restored from the existing sweep authority before scrolling or a
  full-stack snapshot reveals them. This creates no second clock.
- 3D setup and skeleton estimation run in workers. Current-pose sampling shares timestamp lookups
  and never loads a full trajectory into the paint path.

On macOS the first system-accent lookup can still run `defaults` synchronously with a one-second
timeout. It is cached, but remains a startup responsiveness caveat.

## What the checks measure

| Check | Evidence | Limits |
|---|---|---|
| `test_bench_pyramid.py` | 180 M-sample build/query; populated plot, transport, channel and camera readouts | Local mean component budgets; in-memory input |
| `test_bench_plot_pane.py` | Prepared 4/32/128-channel rows, bounded queries, delivered resize events and actual visible paints | Component costs; synthetic data and offscreen Qt |
| `test_seek_backends.py` | Three 1440×1080 long-GOP cameras: jump, drag, re-scrub and presentation-frame correctness | Local decoder/settle workload, separate from native compositor |
| `test_bench_certification.py` | Isolated 1 GB import/reopen, rendered frame strips, populated interaction distributions, heartbeat and RSS | Opt-in; hardware and remaining tails recorded in the report |
| Tracking, imaging and sync benchmarks | Current-pose, lazy plane/average, deterministic event-fitting budgets | Their own fixtures; not a whole-session certificate |
| Exact-mapping tests and provenance benchmark | Million-frame mapping ownership, acceptance/save/load, and shared conversion for 128 channels | Separate memory and worker-path checks |

## Running local certification

```shell
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest --benchmark-only
conda run -n avialsync --no-capture-output python tools/certify_engineering.py --output /tmp/avialsync-certification
```

The second command generates at least one billion bytes of deterministic input and launches a
separate pytest process per scenario. It writes raw benchmark distributions and `certification.json`
outside the repository. Run it without another benchmark or test suite competing for the machine.
The opt-in scenarios are skipped by the ordinary benchmark command unless a certification fixture
root is supplied. Keep baselines with `--benchmark-autosave` and compare with `--benchmark-compare`.
Do not increase a threshold to accommodate a slow result; changed requirements need a decision.

## GitHub verification

Each branch push runs the full three-OS/two-interpreter correctness matrix, lint/typing, and
warnings-as-errors documentation. Linux/Python 3.12 additionally enforces 80% overall coverage and
every executable core line and branch. Benchmarks remain excluded from both workflows.
Interpreter-specific constraints pin runtime, test, documentation and isolated-build dependencies.

A release tag additionally builds and smoke-tests the wheel and all three PyInstaller installers,
including native xcb smoke on Linux. A branch push does not build installers. Hosted correctness,
wheel resolution and build artifacts do not certify speed or native desktop behavior.
