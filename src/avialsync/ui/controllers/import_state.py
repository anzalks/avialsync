"""Queue state for serial time-series imports.

JobManager owns each worker and thread. This state only records which import
occupies the single import slot and what should start when it completes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread


@dataclass
class ImportState:
    """Pending imports and the thread occupying the import slot."""

    pending: deque[tuple[Path, type, dict[str, Any]]] = field(default_factory=deque)
    active_thread: QThread | None = None
