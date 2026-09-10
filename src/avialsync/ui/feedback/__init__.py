"""What the application is doing, what finished, and what went wrong (D-091).

``ui/job_manager.py`` already tracked every background job's state, offered
cooperative cancel, and watched for stalls.  None of it reached the user: a
1 GB import — which the budget allows sixty seconds — ran behind a modal
``QProgressDialog``, so the model was right and the presentation blocked the
whole window for a minute.

This package is the view that was missing.  :class:`ActivityBar` shows the
current job and cancels it, :class:`NotificationStrip` reports outcomes without
taking focus, and :class:`JobsPanel` lists what is running and what recently
finished.  Long work is never modal.
"""

from avialsync.ui.feedback.activity_bar import ActivityBar
from avialsync.ui.feedback.jobs_panel import JobsPanel
from avialsync.ui.feedback.notifications import NotificationStrip
from avialsync.ui.feedback.text_dialog import TextDialog, show_text

__all__ = ["ActivityBar", "JobsPanel", "NotificationStrip", "TextDialog", "show_text"]
