"""Open an NWB file as a session: its time series, its imaging, its videos (D-188).

An NWB file is one session in one file, so it is laid out the way a recording
folder is: a session scanner says what is inside and where each piece sits in
time, and the ordinary loaders read them. Unlike every other session this one is
handed a *file*; the drop scan asks session scanners about files as well as
folders for that reason.

Placement needs no evidence and no fit. Every timestamp in an NWB file counts
from one declared instant, ``timestamps_reference_time`` (by default
``session_start_time``), so that instant is the session's zero and each item
declares it as its own epoch. What a file could not contribute -- a second
imaging plane, a video it names but that is not beside it, a series of a shape
this application does not show -- is reported in the layout's warnings rather
than dropped.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from avialsync.core.errors import FileUnreadableError, SourceOpenError
from avialsync.core.source import SessionItem, SessionLayout, SessionSource, VideoSource
from avialsync.loaders import nwb_format
from avialsync.loaders.nwb_imaging import default_imaging
from avialsync.loaders.nwb_loader import NWBLoader
from avialsync.loaders.nwb_roi_grid import NWBRoiGridSource, find_roi_grids
from avialsync.loaders.nwb_stack import NWBStackSource, channel_groups
from avialsync.loaders.nwb_storage import remote_url, source_label

logger = logging.getLogger(__name__)

#: How many "could not show" reasons a layout lists before summarising the rest.
_MAX_LISTED = 8


class NWBSessionSource(SessionSource):
    """Lay out an NWB 2.x file's series, imaging and external videos."""

    @classmethod
    def display_name(cls) -> str:
        return "NWB File"

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.95 if nwb_format.is_nwb_path(path) or nwb_format.is_zarr_nwb(path) else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        try:
            contents = nwb_format.scan(path)
        except (SourceOpenError, FileUnreadableError) as error:
            # Claimed, so nothing else will lay it out: the reason has to reach
            # the screen, not just the log (D-085).
            return SessionLayout(warnings=[str(error)])

        epoch = contents.reference_epoch
        label = source_label(path)
        warnings: list[str] = []
        items: list[SessionItem] = []

        if (
            contents.of_kind("signal", "interval", "annotation")
            or contents.interval_tables
            or contents.units_tables
        ):
            items.append(
                SessionItem(
                    path=path,
                    loader=NWBLoader,
                    kind=NWBLoader.display_name(),
                    label=label,
                    source_epoch=epoch,
                )
            )

        items.extend(self._imaging_items(path, contents, epoch))
        items.extend(self._external_video_items(path, contents, epoch, registry, warnings))

        if contents.reference_is_naive:
            warnings.append(
                f"{label} records its start time without a time zone; it is read as UTC."
            )
        if contents.declined:
            listed = list(contents.declined[:_MAX_LISTED])
            more = len(contents.declined) - len(listed)
            warnings.extend(listed)
            if more:
                warnings.append(f"…and {more} more objects in {label} that cannot be shown.")
        if not items:
            warnings.append(f"{label} holds nothing AvialSync can show.")

        logger.info(
            "NWB session %s (NWB %s): %d items, %d warnings",
            path.name,
            contents.version,
            len(items),
            len(warnings),
        )
        return SessionLayout(
            items=items,
            anchor_epoch=epoch or 0.0,
            session_epoch=epoch or 0.0,
            warnings=warnings,
        )

    @staticmethod
    def _imaging_items(
        path: Path, contents: nwb_format.FileContents, epoch: float | None
    ) -> list[SessionItem]:
        """One lazy imaging source per acquisition, its series read as channels (D-195).

        Each is named by its own path inside the file
        (:func:`nwb_format.object_path`): the file's path already names its time
        series, and the application tells sources apart by path
        (:func:`avialsync.core.source.container_of`). The series a file is
        usually shown with comes first; the review dialog is where a plane
        nobody wants today is skipped.
        """
        chosen = default_imaging(contents)
        try:
            groups = channel_groups(path, contents)
        except (SourceOpenError, FileUnreadableError, OSError, KeyError, ValueError):
            logger.warning("Could not compare imaging series in %s", path, exc_info=True)
            groups = []
        grouped = {info.path for group in groups for info in group}
        groups += [[info] for info in contents.of_kind("imaging") if info.path not in grouped]
        # Series of one acquisition -- one plane, shape and clock -- are its
        # channels and open as one stack to show alone or overlaid (D-195).
        groups.sort(key=lambda group: chosen not in group)
        items: list[SessionItem] = []
        for group in groups:
            names = " + ".join(info.name for info in group)
            items.append(
                SessionItem(
                    path=nwb_format.object_path(path, group[0].path),
                    loader=NWBStackSource,
                    config={"channels": [info.path for info in group]} if len(group) > 1 else {},
                    label=f"{names} — imaging in {source_label(path)}",
                    kind=NWBStackSource.display_name(),
                    source_epoch=epoch,
                )
            )
        # Every ROI of each plane segmentation, tiled in one picture (D-193):
        # the only way to see more than the one field -- or, for patch-scanned
        # files, the one cell -- that an image series holds.
        try:
            grids = find_roi_grids(path, contents)
        except (SourceOpenError, FileUnreadableError, OSError, KeyError, ValueError):
            logger.warning("Could not look for ROI tables in %s", path, exc_info=True)
            grids = []
        for grid in grids:
            what = "raw crops" if grid.mode == "raw" else "response on masks"
            items.append(
                SessionItem(
                    path=nwb_format.object_path(path, grid.path),
                    loader=NWBRoiGridSource,
                    config={},
                    label=f"{grid.name}: {grid.roi_count} ROIs ({what}) in {source_label(path)}",
                    kind=NWBRoiGridSource.display_name(),
                    source_epoch=epoch,
                )
            )
        return items

    @staticmethod
    def _external_video_items(
        path: Path,
        contents: nwb_format.FileContents,
        epoch: float | None,
        registry: Any,
        warnings: list[str],
    ) -> list[SessionItem]:
        """Videos an ``ImageSeries`` names rather than holds, if they are beside the file.

        Their paths are relative to the NWB file. A video's own first frame is
        its zero, and the series says when that frame was: its ``starting_time``
        or first timestamp.
        """
        items: list[SessionItem] = []
        for info in contents.of_kind("external"):
            if remote_url(path) is not None:
                warnings.append(f"{info.path} names an external video; open it locally to view it.")
                continue
            target = (path.parent / info.external_files[0]).resolve()
            if len(info.external_files) > 1:
                warnings.append(
                    f"{info.path} spans {len(info.external_files)} video files; "
                    f"showing the first, {info.external_files[0]}."
                )
            if not target.is_file():
                warnings.append(
                    f"{info.path} names the video {info.external_files[0]}, "
                    f"which is not beside {path.name}."
                )
                continue
            loader = registry.find_best_loader(target, kind=VideoSource)
            if loader is None:
                warnings.append(f"No video loader can open {target.name}, named by {info.path}.")
                continue
            items.append(
                SessionItem(
                    path=target,
                    loader=loader,
                    label=f"{target.name} — {info.name}",
                    kind="Video",
                    source_epoch=None if epoch is None else epoch + info.start,
                )
            )
        return items
