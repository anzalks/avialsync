# Writing a plugin

A plugin teaches AvialSync your rig: what your files are, how a recording folder is laid out, and
where each file's clock starts. Nothing in the application names a format; the built-in support
for AOL, Open Ephys, Vicon and NWB is written against exactly the API described here.

These pages are a tutorial track. Read them in order the first time:

1. [Your first loader](first-loader.md): one file format, as plotted channels.
2. [A folder of trials](folder-of-trials.md): a whole recording, trials placed at their recorded
   starts.
3. [Trigger lines](trigger-lines.md): telling the sync wizard what a TTL channel is evidence of.
4. [Plugin settings](settings.md): folders and tolerances the user sets in Preferences.
5. [Recordings made on two machines](partner-recordings.md): pairing what one folder cannot.
6. [Installing and testing](installing-and-testing.md): drop-in or package, and
   `avialsync plugin-check`.

The [plugin reference](../plugin-guide.md) has the full contract.

## Two kinds of plugin

| Kind | Subclass | Answers |
|---|---|---|
| Loader | `TimeSeriesSource`, `VideoSource`, `ImagingSource` | How do I read this one file? |
| Session scanner | `SessionSource` | What does this folder contain, and when does each file's clock start? |

A loader is enough for a new file format. A session scanner is what a rig needs: it says which
files belong together, which loader reads each, and the one fact the application cannot work out
for itself, the UTC instant each file's `t = 0` is.

## The one question about time

Every file's timestamps count from somewhere. Declare that instant as `SessionItem.source_epoch`,
in Unix seconds, and the application places the file. Never compute an offset.

| Your file's timestamps are… | Declare |
|---|---|
| seconds from its own first frame | that frame's UTC instant |
| seconds since midnight | that midnight |
| Unix seconds already | `0.0` |
| from an instant nothing recorded | nothing (`None`): it keeps its own zero |

## API version

This is plugin API **2**. A plugin may set `api_version = 2` on its class; the default is the
version of the AvialSync running it. A plugin declaring another version is refused, and **Help →
Diagnostics** says why.
