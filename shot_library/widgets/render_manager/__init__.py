"""
Render Queue Manager Widget Package

The core feature for starting and managing Blender headless renders.

Components:
- RenderQueueDialog: Main dialog matching the mockup
- QueueTable: Job queue table with scene/camera/frames columns
- ProgressPanel: Progress tracking with elapsed/remaining time
- SettingsPanel: Per-job settings with override checkboxes
"""

from .dialog import RenderQueueDialog, RenderManagerDialog
from .queue_table import QueueTable
from .progress_panel import ProgressPanel
from .settings_panel import SettingsPanel

__all__ = [
    'RenderQueueDialog',
    'RenderManagerDialog',  # Backwards compatibility alias
    'QueueTable',
    'ProgressPanel',
    'SettingsPanel',
]
