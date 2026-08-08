# Licensing

AvialSync is free software under the **GNU Affero General Public License,
version 3 or later**, and under nothing else. The full text ships as `LICENSE`
in the repository and inside every release.

## What you can do

Use it, study it, modify it, redistribute it. The single condition is
reciprocity: if you convey a modified version — including letting other people
use it over a network — you publish your changes under the same licence.

All of this is covered, with nothing to sign and nothing to pay:

- running AvialSync in your lab, on any number of machines;
- modifying it for your own use;
- publishing papers about results you obtained with it;
- writing plugins for your own rig;
- sharing your changes with collaborators, or contributing them back.

## Plugins are your own work

A plugin that uses only the documented {doc}`TimeSeriesSource, VideoSource and
SessionSource <plugin-guide>` interfaces is a separate work, and you choose its
licence. You are **not** required to publish a loader you wrote for your lab's
proprietary instrument format.

That boundary is deliberate. A plugin system whose use forced every lab to
publish its file formats would not be used, which is the opposite of the point.

If you plan to distribute a closed plugin *alongside* a modified AvialSync, the
line is worth agreeing in writing first.

## Contributing

Contributions are accepted under the project's own licence,
AGPL-3.0-or-later. There is no contributor agreement to sign — open a pull
request and that is the whole process. You keep the copyright in your work.

## Bundled components

Video decoding comes from [PyAV](https://pypi.org/project/av/), whose wheels
carry their own FFmpeg. PyAV itself is BSD-3-Clause, and the FFmpeg it bundles
is GPL-configured — it includes `libx264` and `libx265`, both GPL-2.0-or-later,
which is compatible with this project's AGPL-3.0-or-later distribution.

The other Python dependencies are LGPL-3.0 (PySide6), MIT (pyqtgraph, polars),
and BSD (numpy, neo, xxhash). Their own licences continue to apply to them.

Release installers bundle nothing further: proxy generation, clip export, and
the sample-session generator all run against the same in-process FFmpeg, so
there are no separate media executables in an installer to attribute.
