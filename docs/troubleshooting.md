# Troubleshooting

## A video says “No Footage”

This is usually correct: the selected master time is outside that camera’s recording. Check its span
in **Data Streams** and its offset in the left panel. It is safer than displaying the last frame from
another time.

## Video viewer remains grey on Windows

AvialView uses libmpv's Qt OpenGL render path on Windows and macOS, and native `wid` embedding on Linux.
If the viewer is grey, open **Help → Diagnostics** and confirm libmpv is available; then update your GPU driver
and restart. The demo's test-pattern videos should be visible before you add your own files. In a headless
environment, video output is intentionally disabled (`vo=null`), so use the time-series and metadata checks only.

## Videos and traces do not line up

First check that the relevant files overlap in **Data Streams**. Then adjust a visible event manually
or use TTL/event synchronization. Accept a proposed synchronization only after reviewing its match
quality.

## A file does not open

Check its **Properties** or import report for the detected format and error. For a lab-specific file,
install the matching plugin. For a video, make sure the installed AvialView release or local media
software can open the codec.

## The plots look slow or too dense

AvialView draws a compact representation of dense signals while you navigate. Zoom into the part
you need; it will show the available detail without trying to draw every sample at once.
