AvialSync documentation
==========================

|PyPI| |Python| |CI| |Documentation| |Licence| |Platforms|

The Advanced Video and Instrument Alignment Library.

AvialSync helps you inspect video and time-stamped experiment recordings on one shared timeline.
It is for looking carefully at data, checking alignment, and preparing observations for analysis.

.. image:: _static/screenshots/aol_session_overview.gif
   :alt: A one-second loop of three synchronised camera views of a head-fixed mouse with 2D pose
         overlays, a triangulated 3D pose drawn as a skeleton, and per-ROI motion traces measured
         from the video, all advancing together on one master timeline.
   :width: 100%

*Three cameras at 230 fps with per-camera 2D pose, triangulated 3D pose drawn with the skeleton the
session declares, and per-ROI motion measured from the video — one second of it, at the speed it
was recorded, every source moving on one master clock. The folder was opened by dropping it on the
window; a session plugin recognised the layout.*

Project links
-------------

- `Source code on GitHub <https://github.com/anzalks/avialsync>`_
- `Report an issue <https://github.com/anzalks/avialsync/issues>`_
- `Releases and changelog <https://github.com/anzalks/avialsync/releases>`_
- `Package on PyPI <https://pypi.org/project/avialsync/>`_
- `Contributing guide <https://github.com/anzalks/avialsync/blob/main/CONTRIBUTING.md>`_

Every page also carries an "Edit this page" link to its source in the repository.

.. toctree::
   :maxdepth: 2
   :caption: Guides

   install
   quickstart
   user-guide/index
   user-guide/sessions-and-media
   tutorials/first-session
   tutorials/importing-data
   tutorials/synchronization
   tutorials/annotating-and-exporting
   formats
   troubleshooting

.. toctree::
   :maxdepth: 2
   :caption: Extending and internals

   plugin-guide
   technical/index
   licensing

.. Badge definitions. These mirror README.md exactly, so the project state a
   reader sees on GitHub and the state they see here cannot disagree. Every
   target is an absolute URL because this page is served from Read the Docs,
   not from the repository.

.. |PyPI| image:: https://img.shields.io/pypi/v/avialsync.svg
   :target: https://pypi.org/project/avialsync/
   :alt: Latest version on PyPI

.. |Python| image:: https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg
   :target: https://pypi.org/project/avialsync/
   :alt: Supported Python versions

.. |CI| image:: https://github.com/anzalks/avialsync/actions/workflows/ci.yml/badge.svg?branch=main
   :target: https://github.com/anzalks/avialsync/actions/workflows/ci.yml
   :alt: Continuous integration status

.. |Documentation| image:: https://readthedocs.org/projects/avialsync/badge/?version=latest
   :target: https://avialsync.readthedocs.io/en/latest/
   :alt: Documentation build status

.. |Licence| image:: https://img.shields.io/badge/licence-AGPL--3.0-blue.svg
   :target: https://github.com/anzalks/avialsync/blob/main/LICENSE
   :alt: Licensed under AGPL-3.0-or-later

.. |Platforms| image:: https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg
   :target: https://github.com/anzalks/avialsync/releases
   :alt: Runs on Windows, macOS and Linux
