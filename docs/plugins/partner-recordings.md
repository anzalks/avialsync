# Recordings made on two machines

Some rigs write one recording on two machines, such as a microscope's trials and the camera PC's
videos of them. `scan` sees one folder at a time, so there are two hooks for pairing them.

## Dropped together: `scan_together`

```python
def scan_together(self, paths, loaded, registry):
    mine = [path for path in paths if belongs_to_my_rig(path)]
    if len(mine) < 2:
        return None  # leave every path to scan()
    return lay_out_together(mine), mine
```

It is asked once per drop, before any path is scanned alone. It returns the layout and the paths it
used, or `None`. `loaded` lists what is already open as `SessionItem`s, each `source_epoch` being
where that source's zero sits now, so a later drop can be placed against it.

## Searched for: `find_partner`

When the user opens the cameras alone, the partner is somewhere on disk. Offer to find it: declare a
`PairingHint` on the layout, and implement `find_partner`.

```python
from avialsync.core.source import PairingHint, PartnerSearch


class CameraSession(SessionSource):
    def scan(self, path, registry):
        start = read_camera_start(path)  # the camera PC's wall clock
        return SessionLayout(
            items=..., session_epoch=start, pairing=PairingHint(start, CameraSession)
        )

    @classmethod
    def find_partner(cls, epoch):
        folder = cls._microscope_folder  # from a setting, via configure()
        if folder is None:
            return PartnerSearch(None, "Set the microscope folder in Preferences.")
        trial = nearest_trial(folder, epoch, tolerance=10.0)
        if trial is None:
            return PartnerSearch(None, "No trial started within 10 s of the cameras.")
        return PartnerSearch(
            trial.folder,
            f"Found {trial.folder.name}.",
            details=f"Clock residual {trial.residual:+.3f} s.",
            duration=trial.duration,
        )
```

**Align → Find Matching Recording** is then enabled. It runs `find_partner` on a worker thread and
offers to load the match. Once loaded, it shows `details` and asks the user to accept. Accepting puts
the partner's zero on the cameras' first frame, as one undoable step.

Which loaded sources are the partner is decided by `partner_targets(match, loaded)`. By default it
is the source whose id is `match.path`. Override it when the partner loads as something else, such as
an experiment joining several trials: return `(source_id, seconds from the partner's zero to this
source's zero)` for each. `loaders/aol_pairing.py` is a full worked example.
