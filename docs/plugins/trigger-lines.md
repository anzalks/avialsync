# Trigger lines

A TTL line recorded with your data is already offered to **Align → Align recordings** as
evidence. What the file cannot say is what the pulses *are*, and that decides how they may be used:

| Kind | Meaning | What the wizard may do |
|---|---|---|
| `frame_strobe` | The camera pulsed once per exposure it **took** | pair pulse *i* with frame *i* |
| `frame_trigger` | Something **asked** for each exposure | fit a clock, never pair by index |
| `sync_train` | A shared square wave, sparser than frames | follow two clocks as they drift |
| `sparse_events` | A few landmarks | place a recording |

Your loader knows its rig's wiring, so it declares the kind on the channel:

```{literalinclude} ../../examples/plugin_tutorials/trial_folder.py
:language: python
:start-at: "class RigDaqLoader"
:end-before: "class TrialFolderSession"
```

`trigger_for` names the video a strobe belongs to; it is matched against the loaded videos' file
names. An undeclared channel is offered as `sparse_events`, the weakest kind.

A declaration is only where the wizard starts. The fit is still shown with its matched events and
residuals, and nothing moves until the user accepts it. Declare `frame_strobe` only when the wiring
really is camera to DAQ, one pulse per exposure taken. A frame the camera dropped looks exactly like
one it kept on a `frame_trigger` line.

A trigger file with no data of its own can still be opened with **Align → Open Trigger Evidence**.
There is no separate trigger-plugin kind: a file of trigger lines is a recording like any other.
