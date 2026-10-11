# A folder of trials

Most rigs do not record one file: they record trials, each its own folder, with a DAQ file and a
camera in each. A session scanner turns that folder into one recording, with every trial at the
instant it was recorded and the time between trials kept as a gap.

The complete plugin is below, and it is tested with every release
(`tests/test_plugin_api_v2.py`). The folder it reads:

```text
my_recording/
    rig.json                 marks the folder as this rig's recording
    trial_001/
        trial.json           {"start_unix": 1700000000.0, "duration_s": 10.0}
        daq.csv              time (s from the trial's start), cam_strobe, wheel
        camera.mp4           optional
    trial_002/ ...
```

```{literalinclude} ../../examples/plugin_tutorials/trial_folder.py
:language: python
:start-at: "class TrialFolderSession"
```

## What each part does

**`can_open`** is asked about every dropped path before anything is read, so it checks for a marker
file and nothing more.

**`place(parts)`** puts each trial at its recorded start and returns a plan: `kept` (which trials
it placed), `starts` (seconds from the first kept trial), `epoch` (that first start as Unix time),
`segments()` (the trial lane drawn on the timeline) and `warnings`. A trial with no recorded start,
or one that starts inside the trial before it, is left out and named, never moved. Pass
`Placement.BACK_TO_BACK` only if your format defines its trials that way.

**Joined streams.** The DAQ file of every trial is one stream, so it is declared once, as a
`JoinedTimeSeriesSource` whose config lists the parts (`{"path", "start"}`, `start` in seconds from
the item's `source_epoch`) and the loader that reads one part (`part_loader`, as `module:Class`,
which `loader_name()` writes for you). The camera is a `JoinedVideoSource`, so it is one pane,
not one per trial. Between trials each stream shows nothing, and **View → Collapse Gaps Without
Data** hides the empty time.

**`source_epoch`** is the one timing fact: here, the first trial's start, which is where each joined
stream's own zero sits.

**`warnings`** reach the user. A trial that could not be read must not fail the folder; it is
reported, and the rest still load.

The user sees every item in the import review before anything is imported.
