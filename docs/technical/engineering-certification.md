# Local engineering measurements — 2026-10-14

The engineering-hardening branch measured the following workloads after fixing hidden-row cursor
updates and transient linked ranges during resize. All five scenarios passed their existing
component assertions. The measurements also expose
remaining resize and event-loop tails, so this report does not certify all responsiveness targets.
The {download}`machine-readable results <engineering-certification-2026-10-14.json>` contain the
unrounded statistics.

## Environment and method

Apple M1 Pro, eight logical CPUs, 32 GiB RAM, macOS 27.0.1 arm64; AvialSync 0.1.11;
Python 3.12.13, PySide6 6.11.2, NumPy 2.5.3, PyAV 19.0.1 and Polars 1.43.0.
Qt renders offscreen at 1280×800, with resize widths from 1100 to 1600 pixels.
This is a synthetic, local measurement on a 32 GB host. Windows/Linux timing, native compositors,
private field recordings and the intended 16 GB machine remain external checks.

`tools/certify_engineering.py` generates fixtures before launching separately measured application
processes. Garbage from earlier tests is collected before window construction; collection remains
enabled during the workload. Peak RSS excludes the fixture generator and uses decimal MB.
The heartbeat is a 2 ms Qt timer: its maximum is the observed delivery gap, including timer
scheduling, paints and event processing, rather than a claim about one callback's duration.

## Import, reopening and rendered video

The CSV contains 30,500,000 chronological rows, four int16 signals at 50 kHz and
1,013,749,844 bytes. It includes known sine/ramp/step/noise values. The real registered import job
reported progress four times, reached 100%, installed four plot rows, and passed exact step-value
checks. The cold import took **2.087 s** after window construction, with a **95.83 ms** maximum
heartbeat gap. This is one cold sample, not a distribution. Peak RSS across cold import and
five warm reopens was **1,745.08 MB**.

Cold means an empty AvialSync cache. The CSV was generated immediately before the test;
the operating system's file cache was not flushed. This does not measure a cold physical disk.

Warm reopening loads the cached four-channel recording plus three cameras. Rendered-seek tests use
three 640×360, 30 fps fixture cameras and decode their binary frame strip from widget grabs after
every seek. They do not rely on the decoder buffer or a reported timestamp. The separate long-GOP
1440×1080 benchmark retains its own budgets.

| Measurement | Rounds | Mean ms | p50 ms | p95 ms | p99 ms | Maximum ms |
|---|---:|---:|---:|---:|---:|---:|
| Cached reopen, including scenario setup/close | 5 | 343.38 | 344.45 | 350.59 | 351.60 | 351.86 |
| Three-camera seek through painted frame verification | 60 | 13.17 | 12.77 | 13.70 | 20.45 | 29.78 |

The seek process peaked at 406.29 MB RSS and a 22.13 ms heartbeat gap. These short-GOP fixture
results must not be substituted for long-GOP, high-resolution or native-display measurements.

## Populated plot interactions

Each scenario installs all rows before measuring sixty rounds of cursor, duration change,
resize/event delivery, worker settlement and widget-grab paint. Resize includes delivery of pending
Qt events; it is not the duration of a single resize callback. All rows remain loaded, while the
viewport draws only nearby rows. Scroll and full-stack snapshot tests verify restoration of culled
cursor/sweep pixels, including collapsed gaps.

| Channels | Operation | Mean ms | p50 ms | p95 ms | p99 ms | Maximum ms |
|---|---|---:|---:|---:|---:|---:|
| 4 | Cursor | 0.20 | 0.13 | 0.63 | 0.80 | 0.83 |
| 4 | Zoom request | 1.34 | 1.37 | 1.66 | 1.73 | 1.73 |
| 4 | Resize/event delivery | 19.45 | 18.47 | 25.62 | 26.79 | 27.36 |
| 4 | Paint | 7.53 | 7.50 | 11.27 | 11.57 | 11.72 |
| 32 | Cursor | 0.45 | 0.29 | 1.22 | 2.15 | 2.17 |
| 32 | Zoom request | 4.80 | 4.86 | 6.01 | 6.66 | 6.88 |
| 32 | Resize/event delivery | 46.81 | 39.18 | 65.27 | 65.73 | 65.98 |
| 32 | Paint | 11.42 | 11.53 | 16.51 | 16.67 | 16.72 |
| 128 | Cursor | 0.72 | 0.33 | 2.41 | 5.72 | 6.17 |
| 128 | Zoom request | 15.54 | 15.53 | 18.93 | 20.33 | 20.39 |
| 128 | Resize/event delivery | 91.52 | 78.65 | 119.09 | 142.31 | 150.93 |
| 128 | Paint | 12.55 | 12.73 | 18.14 | 18.38 | 18.45 |

| Channels | Maximum heartbeat gap ms | Peak RSS MB |
|---|---:|---:|
| 4 | 38.49 | 343.74 |
| 32 | 87.70 | 418.02 |
| 128 | 183.78 | 701.66 |

The hidden-row optimization lowered the 128-channel cursor mean from the original mixed-workload
2.79 ms to 0.72 ms. Mean cursor and paint costs pass their 2/16 ms component budgets; the 128-channel
zoom target of 8 ms is missed, and p95 paint/cursor costs exceed their mean marks. Full interaction
latency and heartbeat maxima remain larger than component means. Further profiling should identify
individual layout, worker-installation and paint contributions before changing that path.
The final sixty-resize callback benchmark, including lifetime and block-state preservation,
reports a 15.76 ms mean and **22.32 ms maximum**. Pixel-executing cursor means are 0.39/1.48 ms
at 32/128 rows, and the complete four-channel/readout/camera tick averages 0.11 ms.

## Reproducing the report

```shell
conda run -n avialsync --no-capture-output python tools/certify_engineering.py --output /tmp/avialsync-certification
```

Keep raw JSON and hardware details with each measurement. Do not generate a report while another
test suite or benchmark competes for the machine, and do not describe offscreen evidence as
completed native or field-data certification.
