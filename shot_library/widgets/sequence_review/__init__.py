"""
Sequence Review Package

Components for the fullscreen sequence review dialog.

This package decomposes the original SequenceReviewDialog (~1500 lines)
into focused, maintainable modules:

- dialog.py: Main SequenceReviewDialog (orchestration only)
- state.py: State dataclasses (PlaybackState, TimelineState, PreloadState)
- export_manager.py: Export functionality (single shot and sequence)
- timeline_manager.py: Global timeline logic across all shots
- shot_list_panel.py: Collapsible left panel for shot navigation
- preload_worker.py: Background preloading worker
"""

from .state import PlaybackState, TimelineState, PreloadState
from .timeline_manager import SequenceTimelineManager
from .export_manager import SequenceExportManager
from .shot_list_panel import ShotListPanel
from .preload_worker import PreloadWorker
from .dialog import SequenceReviewDialog

__all__ = [
    'SequenceReviewDialog',
    'PlaybackState',
    'TimelineState',
    'PreloadState',
    'SequenceTimelineManager',
    'SequenceExportManager',
    'ShotListPanel',
    'PreloadWorker',
]
