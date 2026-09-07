"""Every graphic drawn over video, and the switch that turns it off (D-090).

Law 2 of Phase 7: nothing is composited on a video frame that the user cannot
turn off.  Before this module the situation had drifted in both directions at
once.  ``PaintCanvas`` carried ``set_point_labels_visible`` and
``set_legend_visible`` that no production code ever called — the toggles
existed, the control surface did not — while the camera name and the timecode
readout were drawn with no toggle at all.  Adding the next overlay without a
registry adds the next unreachable method.

So there is one declaration of what exists.  :data:`OVERLAY_LAYERS` is the
inventory; the **View → Overlays** menu is generated from it, per-camera
overrides use the same labels in the pane context menu, and
``tests/test_overlay_registry.py`` enumerates it against what the panes
actually draw, so drawing something new without registering it fails CI rather
than review.

A plugin contributing an overlay registers a layer here and gets its checkbox
automatically — the registry is the extension point, not a fixed list.
"""

from __future__ import annotations

import dataclasses

__all__ = [
    "OverlayLayer",
    "OVERLAY_LAYERS",
    "OverlayState",
    "layer_for",
]


@dataclasses.dataclass(frozen=True)
class OverlayLayer:
    """One switchable graphic drawn over a video frame."""

    overlay_id: str
    label: str
    group: str
    default_visible: bool = True
    #: A layer the user may not hide, because hiding it would make the pane
    #: misleading rather than merely plainer. It is still registered and still
    #: appears in the menu -- greyed, with the reason in its tooltip -- so the
    #: inventory stays complete and the exception is visible rather than
    #: folklore.
    locked: bool = False
    #: Whether a single camera can override the global setting.
    per_camera: bool = True
    #: Shown as the menu entry's tooltip.
    description: str = ""


#: The complete inventory. Anything painted over a frame belongs here.
OVERLAY_LAYERS: tuple[OverlayLayer, ...] = (
    OverlayLayer(
        overlay_id="tracking.points",
        label="Tracking points",
        group="Tracking",
        default_visible=True,
        description="Predicted body-part positions drawn over the footage.",
    ),
    OverlayLayer(
        overlay_id="tracking.point_labels",
        label="Body-part names",
        group="Tracking",
        # Off by default: with nine tracked points the names cover the animal,
        # which is the state the reference session ships in.
        default_visible=False,
        description="The name of each tracked point, drawn beside its marker.",
    ),
    OverlayLayer(
        overlay_id="tracking.legend",
        label="Track legend",
        group="Tracking",
        default_visible=True,
        description="Key naming each prediction source, when more than one is drawn.",
    ),
    OverlayLayer(
        overlay_id="tracking.corrections",
        label="Hand-corrected marks",
        group="Tracking",
        default_visible=True,
        description=(
            "A ring around every point you moved with Fix Tracker, so a "
            "correction is never mistaken for the model's own output."
        ),
    ),
    OverlayLayer(
        overlay_id="tracking.edit_handles",
        label="Fix Tracker handles",
        group="Tracking",
        default_visible=True,
        locked=True,
        per_camera=False,
        description=(
            "Shown only while Fix Tracker is on, and not switchable then: "
            "hiding the handles would leave the mode nothing to grab."
        ),
    ),
    OverlayLayer(
        overlay_id="camera.name",
        label="Camera name",
        group="Camera chrome",
        default_visible=True,
        description="The file name, drawn in the corner of the pane.",
    ),
    OverlayLayer(
        overlay_id="camera.osd",
        label="Timecode and format readout",
        group="Camera chrome",
        default_visible=True,
        description="Time, frame number, declared and measured rate, codec, and size.",
    ),
    OverlayLayer(
        overlay_id="camera.no_footage",
        label="“No Footage” placeholder",
        group="Camera chrome",
        default_visible=True,
        locked=True,
        per_camera=False,
        description=(
            "Always shown. Hiding it would let a blank pane be mistaken for black "
            "footage, which is the misreading D-010 exists to prevent."
        ),
    ),
)

_BY_ID = {layer.overlay_id: layer for layer in OVERLAY_LAYERS}


def layer_for(overlay_id: str) -> OverlayLayer | None:
    """Return the registered layer with *overlay_id*, if any."""
    return _BY_ID.get(overlay_id)


class OverlayState:
    """Which layers are shown, globally and per camera.

    Global settings are the default for every pane; a per-camera entry
    overrides one.  Kept out of ``core/`` because it is presentation, but kept
    out of the panes too: a four-camera rig must be able to set a layer once.
    """

    def __init__(self) -> None:
        self._global: dict[str, bool] = {
            layer.overlay_id: layer.default_visible for layer in OVERLAY_LAYERS
        }
        self._per_camera: dict[str, dict[str, bool]] = {}

    # ── reading ──────────────────────────────────────────────────────

    def is_visible(self, overlay_id: str, camera: str | None = None) -> bool:
        """Whether *overlay_id* shows, for *camera* or globally."""
        layer = _BY_ID.get(overlay_id)
        if layer is not None and layer.locked:
            return True
        if camera is not None:
            override = self._per_camera.get(camera, {}).get(overlay_id)
            if override is not None:
                return override
        return self._global.get(overlay_id, True)

    def visibility_for(self, camera: str) -> dict[str, bool]:
        """The resolved visibility of every layer for one camera."""
        return {
            layer.overlay_id: self.is_visible(layer.overlay_id, camera) for layer in OVERLAY_LAYERS
        }

    def has_override(self, overlay_id: str, camera: str) -> bool:
        """Whether *camera* differs from the global setting for this layer."""
        return overlay_id in self._per_camera.get(camera, {})

    # ── writing ──────────────────────────────────────────────────────

    def set_visible(self, overlay_id: str, visible: bool, camera: str | None = None) -> bool:
        """Set a layer's visibility. Returns whether anything changed.

        A locked layer never changes, and says so by returning False rather
        than raising: the menu entry is disabled, so reaching here at all means
        a caller bypassed the UI, and refusing quietly is better than crashing
        the pane it was drawn on.
        """
        layer = _BY_ID.get(overlay_id)
        if layer is None or layer.locked:
            return False
        if camera is not None and not layer.per_camera:
            return False

        if camera is None:
            if self._global.get(overlay_id) == visible:
                return False
            self._global[overlay_id] = visible
            return True

        overrides = self._per_camera.setdefault(camera, {})
        if overrides.get(overlay_id) == visible:
            return False
        overrides[overlay_id] = visible
        return True

    def clear_override(self, overlay_id: str, camera: str) -> None:
        """Drop a per-camera override so the camera follows the global setting."""
        self._per_camera.get(camera, {}).pop(overlay_id, None)

    def forget_camera(self, camera: str) -> None:
        """Drop every override for a camera that is no longer loaded."""
        self._per_camera.pop(camera, None)

    # ── persistence (schema v7) ──────────────────────────────────────

    def to_dict(self) -> dict[str, object]:
        """Serialise for the session file, omitting anything at its default.

        Writing only differences keeps a v7 file honest about what the user
        actually chose, and lets a later change of default reach sessions that
        never expressed a preference.
        """
        globals_ = {
            overlay_id: visible
            for overlay_id, visible in self._global.items()
            if _BY_ID[overlay_id].default_visible != visible
        }
        cameras = {
            camera: dict(overrides) for camera, overrides in self._per_camera.items() if overrides
        }
        payload: dict[str, object] = {}
        if globals_:
            payload["global"] = globals_
        if cameras:
            payload["per_camera"] = cameras
        return payload

    def load(self, payload: dict[str, object] | None) -> None:
        """Restore from a session file, ignoring layers this build lacks.

        A session written by a build with a plugin overlay must still open
        without it; the unknown id is skipped rather than resurrected as a
        layer nothing draws.
        """
        self.__init__()  # type: ignore[misc]
        if not payload:
            return
        stored_global = payload.get("global")
        if isinstance(stored_global, dict):
            for overlay_id, visible in stored_global.items():
                if overlay_id in _BY_ID and not _BY_ID[overlay_id].locked:
                    self._global[overlay_id] = bool(visible)
        stored_cameras = payload.get("per_camera")
        if isinstance(stored_cameras, dict):
            for camera, overrides in stored_cameras.items():
                if not isinstance(overrides, dict):
                    continue
                clean = {
                    overlay_id: bool(visible)
                    for overlay_id, visible in overrides.items()
                    if overlay_id in _BY_ID and not _BY_ID[overlay_id].locked
                }
                if clean:
                    self._per_camera[str(camera)] = clean
