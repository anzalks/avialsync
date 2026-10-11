# Plugin settings

A plugin that needs something only the user knows, such as a data folder, a tolerance or a naming
pattern, declares it, and the application shows it in **File → Preferences** on a tab named after
the plugin.

```python
from avialsync.core.settings_schema import Setting


class TrialFolderSession(SessionSource):
    _trial_pattern = "trial_*"

    @classmethod
    def plugin_id(cls) -> str:
        return "trial_folder_rig"  # stored as plugins/trial_folder_rig/<key>

    @classmethod
    def settings(cls) -> tuple[Setting, ...]:
        return (
            Setting(
                key="trial_pattern",
                label="Trial folder pattern",
                group="",  # empty: the plugin's own tab
                default="trial_*",
                kind=str,  # bool, int, float or str
                help_text="Folders matching this pattern are the recording's trials.",
            ),
        )

    @classmethod
    def configure(cls, values: dict) -> None:
        cls._trial_pattern = str(values["trial_pattern"])
```

`configure` receives the current values, keyed by your own keys, before every drop scan and whenever
the user changes one. Keep what `scan` needs on the class. Scans run on a worker thread and cannot
read preferences themselves.

`Setting` also takes `choices` (a drop-down), `minimum` and `maximum` (numbers), and `legacy_key`:
the key an earlier version stored the value under, read once so moving a setting keeps what the user
chose. Several classes of one plugin share settings by returning the same `plugin_id`; the AOL
scanners do this.
