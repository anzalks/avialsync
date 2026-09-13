# Tutorial: align recordings

Recordings that came off independently-clocked hardware rarely agree. This walks through the ways
AvialSync fixes that, in the order you should try them: a manual offset, a drift correction,
evidence-based alignment from TTL pulses or camera frame triggers, and loading a trigger file so
AvialSync knows what your pulses are evidence of.

**Nothing here rewrites your files.** An alignment changes how AvialSync *reads* a recording onto
the shared timeline. The original stays byte-for-byte as the acquisition system wrote it.

## Before you start

Find an event visible in more than one recording: a flash, a movement, a pulse, a camera frame
trigger. That shared event is what you will judge alignment against.

Load your files first; [the first-session tutorial](first-session.md) covers that.

## 1. A fixed offset, when one recording is simply early or late

Every source carries its own **Offset** and **Drift** in the left panel.

![The per-source offset and drift fields in the left panel](../_static/screenshots/guide_offset_fields.png)

1. **Offset** shifts the whole recording along the shared timeline, in seconds. Positive moves it
   later. Use this when a camera started before or after the others.
2. **Drift** corrects a clock that runs fast or slow, in parts per million. Use it when the
   recordings agree at the start and separate towards the end — a fixed offset cannot fix that,
   because the error grows with time. Cameras have this field too, so a camera that slips against
   the sensor is corrected where the problem is, rather than by drifting the sensor and moving it
   relative to every *other* camera at the same time.

Scrub to your shared event, adjust **Offset** until the views agree, then check a second event near
the *end* of the recording. If the two events need different offsets, the clocks are drifting and
you want **Drift** as well, or better still the evidence-based route below, which measures both.

For the last fraction of a frame, select the source and use **Align → Nudge selected source
earlier** / **later** (`Ctrl+Shift+Left` / `Ctrl+Shift+Right`). It steps the offset of the source
you selected — not whichever camera happens to be first — so you can keep your eyes on the video
while you adjust it.

## 2. Evidence-based alignment from TTL or frame triggers

When a recording carries repeated pulses — a TTL line, a camera exposure trigger, a frame-timestamp
log — AvialSync can fit the alignment from that evidence instead of you eyeballing it. Open
**Align → Synchronize TTL / events…**.

The dialog does not block the window behind it. When a point on the evidence looks wrong, click it
and the master clock seeks there, so you can look at the footage before deciding whether to accept.

### Choose what to compare

![Selecting reference and target evidence in the synchronization wizard](../_static/screenshots/guide_sync_evidence.png)

1. **Reference evidence** — the source you trust. Usually the acquisition system's TTL channel, a
   trigger file, or another camera.
2. **Target video evidence** — the recording being aligned *to* that reference.

A camera can be either. Two cameras that saw the same trigger are evidence about each other, so a
rig with no sensor at all can still align its cameras from their frame timestamps.

### Tell it how to read the reference

![The TTL threshold and the all-samples checkbox](../_static/screenshots/guide_sync_ttl_threshold.png)

1. **TTL high threshold** — the voltage above which a sample counts as a logical high. Set it
   between your line's low and high levels. This is how a continuous analogue trace becomes a list
   of pulse edges.
2. **Use all samples as events** — check this when your reference is *already* a list of event
   times, such as a CSV of frame triggers, rather than a voltage to be thresholded. It disables the
   threshold, because there is nothing to threshold.

Getting this wrong is the most common cause of a poor fit: a threshold outside the signal's range
finds either no edges or every sample.

### Choose the strategy — or let the evidence choose

![The alignment strategy and index offset](../_static/screenshots/guide_sync_strategy.png)

1. **Alignment strategy**
   - **Automatic (from the evidence)** — the default, and the one to use. It picks the strongest
     model this evidence actually supports, which is not a matter of preference: whether the
     recording is long enough to measure a rate, and whether the pulses identify frames, are facts
     about the data rather than choices. See [what it picks between](#what-automatic-picks-between).
   - **Affine fit (offset and drift)** — forces a fitted offset and rate across all matched events.
   - **Exact index (1:1 frame mapping)** — forces mapping video frame *n* to reference event *n*.
     Only correct when the reference genuinely records each exposure that *happened*; if it records
     each exposure that was *requested*, a dropped frame shifts everything after it.
2. **Index Offset** — enabled only for Exact Index. Sets which reference event video frame 0
   corresponds to. Leave it at 0 unless recording started mid-sequence.

### Set the tolerance, if the default is not good enough

**Match tolerance** is how far apart two events may be and still count as the same event. Left
blank it is derived from your pulse rate — a quarter of the interval between events — which is a
rule about telling one pulse from the next, not about the precision your work needs. On a 1 Hz sync
pulse that is 250 ms, and it will accept a 100 ms misalignment without complaint.

If your timing budget is tighter than that, type it. The same evidence is then judged by the
precision you actually need.

### Fit only part of a recording

Tick **Fit only part of the recording** and drag the shaded window on the residual plot. Use it when
the start or end of a recording is unusable — a settling period, a cable knocked mid-session.

A fit over part of a recording claims nothing about the rest, so the window is written into the
record and reported wherever the alignment is shown. Outside it, the alignment is an extension of a
trend measured elsewhere, which may well be right and is a different statement.

### Or set the mapping by hand

![The manual offset and drift fields](../_static/screenshots/guide_sync_manual.png)

If you already know the numbers — from the rig's documentation, or a previous session — enter them
directly instead of fitting.

1. **Manual offset**, in seconds.
2. **Manual drift**, in parts per million.
3. **Use manual mapping** applies them as a proposal, which you still accept explicitly.

A manual mapping is recorded as set by hand, and reported that way everywhere afterwards. It is
never dressed up as a measurement: a number you typed has no residual, no matched events, and no
uncertainty, and the session says so rather than quoting zeros that would read as perfect.

### Read the evidence before accepting

![The preview and accept buttons](../_static/screenshots/guide_sync_preview_accept.png)

1. **Preview alignment** extracts the evidence, matches events, and fits the mapping. Three panels
   show what it found; read them in order, because they answer different questions.
2. **Accept mapping** applies it. Until you press this, nothing has changed. A proposal is never
   applied silently, and it never becomes your data on its own. If Accept is greyed out, the
   summary says which part of the evidence to change.

**The top panel — correspondence.** Reference time against the target time each event was matched
to, with a dashed one-to-one guide behind it. A correct alignment is a dense diagonal lying along
the guide, with clean margins. This is the panel that shows whether the *pairing* is right, and it
is the one to read first.

- Points diverging from the guide mean a rate difference.
- A line parallel to the guide but displaced means the whole train was matched at the wrong lag —
  which happens with uniform pulse trains, and which no residual can reveal.
- Ink along the margins is rejected evidence, drawn where it sits in time. A margin that is mostly
  solid means most of your events found no partner.

**The middle panel — residuals.** How tightly the matched pairs agree, against the tolerance band
that judged them. This measures *precision*, and only means something once the panel above has
established that the pairs are the right ones. A perfect-looking residual is exactly what a
badly-matched fit produces.

**The bottom panel — coverage.** Where each recording has data, where its alignment was actually
measured, and where the recording stops and resumes. The distinction that matters: between the
first and last sync point the alignment is measured, and outside them it is extended. Both may be
right; they are different claims, and a source with no accepted evidence is marked as extended
along its whole length.

### What "Automatic" picks between

In descending order of strength, whichever the evidence supports:

- **Exact** — a camera strobe whose pulse count matches the frames in the file. Each frame takes the
  time its own exposure was measured at. No model is fitted, so there is nothing to be uncertain
  about; the confidence is the count agreement.
- **Interpolated between sync edges** — a shared pulse train. The mapping follows the two clocks at
  every edge, so no single rate has to hold across the whole recording. This is the answer when
  clocks wander unpredictably, as they do when a room warms up.
- **Offset and drift** — a fitted rate, where the recording is long enough for a rate to be
  measurable at all.
- **Offset alone** — where it is not. A drift fitted over a span too short to show it is not a
  measurement of a clock; it is noise in a parameter, and AvialSync declines to quote it.
- **Unvalidated** — two matched events. They determine the offset and leave nothing over to check
  it with, which is a different state from a good fit and is recorded as one.

Accepted mappings are saved with the session, so a colleague can see what was applied and on what
evidence.

## 3. Load a trigger file, and say what its lines are

A TTL file is often separate from the data: a DAQ export with a time column and one or more logical
lines, or a camera's own log with one timestamp per exposure. Open **Align → Open Trigger
Evidence…** and pick it.

AvialSync reads the header, offers every column that looks like a trigger line, and asks the one
question the file cannot answer: **which way the wire ran.**

- **Camera exposure strobe** — the camera emitted a pulse per exposure it actually took. Pulse
  count is frame count, a dropped frame shows as a gap in the train, and each frame can be given
  the time its own exposure was measured at.
- **External frame trigger** — a pulse generator asked the camera for each exposure. This records
  the request, not the result. A frame the camera dropped looks exactly like one it kept, so
  pairing by index would shift everything after the loss. Counts agreeing does not rescue it: a
  drop plus a duplicate agree too.
- **Shared sync pulse train** — a square wave both systems recorded, far sparser than the frame
  rate. Enough to follow the two clocks wherever they wander; not enough to identify a frame.
- **Sparse landmarks** — a start pulse, a stop pulse, a switch thrown by hand. Enough to place a
  recording, rarely enough to check the placing.

**Nothing is pre-selected as a strobe.** Whether those pulses came from frames that happened is a
fact about your wiring, and it decides whether an exact per-frame mapping is allowed — so it is the
one thing AvialSync will not assume on your behalf. Everything is offered as a sync train until you
say otherwise.

One file can carry several lines, each about a different camera. Name the source each one is
evidence about, and it will be offered on the right side of the wizard. What you declared is saved
with the session; the pulses themselves are re-read from the file, so a file corrected on disk is
read as it now is.

If a train skips beats, AvialSync says so when it loads. That gap is the evidence frames were lost,
and the reason an index-paired mapping would be wrong.

### If your rig emits a perfectly uniform train

A uniform pulse train fits at *every* multiple of its period, and no residual can tell those
alignments apart — a fit off by one whole period looks exactly as good as the right one. AvialSync
refuses rather than guessing when two lags fit equally well.

The fix is at the rig: make the pulses distinguishable. Jittered intervals, or a periodically
doubled pulse, give the alignment a single unambiguous answer.

## 4. Check the result

Alignment that looks right at the event you used to align it proves very little.

- Move to several events **across the whole recording**, especially near the beginning and end.
  Drift shows up at the edges.
- **Data Streams** shows when each source has data; the video and plot panes show the aligned
  content itself.
- With an **exact** or **interpolated** mapping accepted, scrubbing, pausing, and frame-stepping all
  land on the accepted trigger timestamps, and every video seeks from the same master trigger while
  keeping its own original presentation timestamps.
- Each source's badge in **Data Streams** says how it is aligned, including when it is not aligned
  at all. Moving a source by hand after accepting a fit supersedes that fit: the record is kept so
  you can see what it was, and marked so nothing reports a residual for a mapping it stopped using.

If a camera has no coverage at the selected time it shows **No Footage** instead of a stale frame.
That is correct behaviour, not a fault.
