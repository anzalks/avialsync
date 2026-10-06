"""Registered background probe for imaging metadata (D-190)."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import ImagingChoiceRequired
from avialsync.core.source import ImagingMetadata, ImagingSource


class ImagingProbeWorker(QObject):
    """Validate one stack and its timing without touching the UI thread.

    Emits exactly one of ``finished(metadata)``, ``needs_choice(choice,
    message, options)`` -- the file is readable but a scientific choice is
    missing -- or ``error(message)``.
    """

    finished = Signal(object)
    needs_choice = Signal(str, str, object)
    error = Signal(str)

    def __init__(self, path: Path, loader_cls: type[ImagingSource], config: dict[str, Any]) -> None:
        super().__init__()
        self._path = path
        self._loader_cls = loader_cls
        self._config = config

    @Slot()
    def run(self) -> None:
        """Read metadata and close the probe handle before completing."""
        reader = self._loader_cls()
        try:
            metadata: ImagingMetadata = reader.open(self._path, self._config)
        except ImagingChoiceRequired as choice:
            self.needs_choice.emit(choice.choice, str(choice), tuple(choice.options))
        except Exception as error:  # noqa: BLE001 - third-party reader boundary
            self.error.emit(str(error))
        else:
            self.finished.emit(metadata)
        finally:
            reader.close()
