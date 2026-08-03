# Licensing

AvialSync is free software under the **GNU Affero General Public License,
version 3 or later**. The full text ships as `LICENSE` in the repository and
inside every release.

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

Contributions are accepted under the terms in `CLA.md`. You keep the copyright
in your own work; the agreement keeps the copyright in the project as a whole in
one place, so it can be licensed coherently. One line in your first pull request
covers it.

## Bundled components

Release installers bundle libmpv and FFmpeg in LGPL-licensed builds, verified
during packaging. The Python dependencies are LGPL-3.0 (PySide6), MIT
(pyqtgraph, polars), BSD (numpy, neo, xxhash), and LGPLv2.1+ (python-mpv). Their
own licences continue to apply to them.

## Other arrangements

A small number of situations cannot accommodate the AGPL's reciprocity at all —
for example software that must ship inside a closed product, or an organisation
whose policy forbids AGPL code outright. If that is genuinely your position,
write to <anzal.ks@gmail.com> describing what you want to build and how you
intend to distribute it, and it can be discussed case by case.

This is rarely necessary. Ordinary research use is already covered above.
