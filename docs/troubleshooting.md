# Troubleshooting

## A startup error naming numpy or quantities

A traceback ending in `AttributeError: type object 'numpy.ndarray' has no attribute 'ptp'`, raised
somewhere under `import neo`, means an outdated `quantities` is being imported alongside NumPy 2.
`quantities` before 0.16.3 reads a method NumPy 2 removed. AvialSync now requires a version that
does not, so a fresh install into a clean environment cannot hit this.

It survives on Windows for one reason: a conda environment still reads your **per-user**
site-packages, `%APPDATA%\Python\Python312\site-packages`, ahead of its own. An old copy left there
by an earlier `pip install --user` shadows whatever the environment resolved, and `pip` never
revisits it because it is not what pip was asked to install. Read the paths in your traceback — if
`neo` and `quantities` load from `AppData\Roaming\Python` while AvialSync loads from `.conda\envs`,
this is what happened.

```powershell
conda activate avialsync
setx PYTHONNOUSERSITE 1
python -m pip install --upgrade "quantities>=0.16.3" neo
```

Open a new terminal so `PYTHONNOUSERSITE` takes effect. Deleting `%APPDATA%\Python\Python312`
removes the shadowing copy for every environment on the machine. The command that verifies the
result is under [Windows installation](install.md#windows).

A broken loader no longer stops AvialSync from starting: the format it handles disappears and
**Help → Diagnostics** names the failure under *Plugins that failed to load*. An older release
crashed outright instead.

## Video does not play after `pip install`

This should no longer happen. Video decoding ships inside the Python packages, so `pip install
avialsync` brings its own decoder and there is nothing further to install — the `Missing libmpv`
dialog that earlier versions showed is gone along with the library it asked for.

If video still does not appear, open **Help → Diagnostics**: it names the decoder in use. A failure
there means the install is broken, not merely incomplete, so reinstall with
`python -m pip install --force-reinstall avialsync`.

## A video says “No Footage”

This is usually correct: the selected master time is outside that camera’s recording. Check its span
in **Data Streams** and its offset in the left panel. It is safer than displaying the last frame from
another time.

## The video pane stays blank

The pane draws decoded frames directly, and it does the same thing on Windows, macOS, and Linux —
there is no per-platform render path left to go wrong, and no GPU driver involved in getting a frame
on screen.

A blank pane with a name in the corner usually means the file failed to open; the pane says so in
place of the picture. Check that the file plays elsewhere and that its codec is one FFmpeg supports.
The demo's test-pattern videos (`avialsync demo`) should be visible before you add your own files.

## Videos and traces do not line up

First check that the relevant files overlap in **Data Streams**. Then adjust a visible event manually
or use TTL/event synchronization. Accept a proposed synchronization only after reviewing its match
quality.

## A file does not open

Check its **Properties** or import report for the detected format and error. For a lab-specific
file, install the matching plugin.

For a video, AvialSync accepts anything its bundled decoder can genuinely open — it reads the header
rather than trusting the file name, so an unusual extension is not itself a reason for rejection.
Two cases it will decline on purpose:

- **A still image.** A PNG or TIFF is technically decodable as a one-frame video, and treating one
  as a camera would be wrong more often than useful.
- **A raw format such as `.bin`.** It carries no header saying resolution, pixel format, or rate, so
  nothing can infer how to read it. That needs a [plugin](plugin-guide.md) to declare those.

## An Open Ephys recording will not open, and the error names an event stream

An error reading something like *"… declares an event stream neo cannot read, so none of the
recording can be opened until it is corrected — events/MessageCenter: no timestamps.npy"* means what
it says, and the folder it names is the thing to look at.

The reader AvialSync uses checks every event stream while reading the recording's header, so one
malformed annotation folder stops the whole recording rather than only its notes. Two shapes cause
it: a folder listed in `structure.oebin` that holds no `timestamps.npy`, and a `text.npy` rewritten
as unicode rather than the byte strings the Open Ephys GUI writes — usually the result of a script
that re-saved the file. Restoring that folder from the original recording, or removing it and its
entry from `structure.oebin`, opens the recording again.

A folder listed in `structure.oebin` that is simply *absent* is not this problem and is skipped
harmlessly.

If one recording inside a dropped folder is affected, the others still load — the status line says
which one was left out, so the session never quietly comes up short.

## The Messages tab is empty

Most often the loaded files genuinely carry no prose; not every format stores any.

Two other causes are worth checking. A recording imported before AvialSync read messages keeps its
cached import, and **re-importing that source once** picks them up — nothing else needs rebuilding.
And a recording's sync preamble is deliberately not listed: the line naming the software time or the
first sample number places the clock rather than saying anything a person wrote.

## The import wizard read my timestamps wrong

Everything downstream — alignment, frame numbers, exports — inherits this, so it is worth
correcting properly instead of working around.

The usual cause is the **Numeric unit**: a column of plain numbers is ambiguous between seconds,
milliseconds, microseconds, and nanoseconds, and choosing the wrong one scales the whole recording.
Check the preview's first and last times against the duration you actually recorded.

The second cause is **Timezone**. AvialSync makes you choose rather than defaulting, because a
naive timestamp silently treated as UTC is how comparable tools produced 1–2 hour "corruption"
reports. Re-import with the right zone; the cached parse is keyed on the file's content, so
changing the setting rebuilds it.

See [Import sensor and recording data](tutorials/importing-data.md).

## The plots look slow or too dense

AvialSync draws a compact representation of dense signals while you navigate. Zoom into the part
you need; it will show the available detail without trying to draw every sample at once.

## AvialSync does not follow my system's dark or light appearance

Open **View → Theme**. If **Dark** or **Light** is selected, that is an explicit choice and
AvialSync remembers it across launches — it will keep that appearance on a desktop set to the
other one. Choose **System** and the window follows your desktop again, including a change you
make while AvialSync is running.

The preference is stored per user, so a copy that starts in the "wrong" appearance is usually one
where **Dark** or **Light** was picked at some point, not one that is failing to read your
desktop.
