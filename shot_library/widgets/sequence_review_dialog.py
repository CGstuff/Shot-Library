"""
SequenceReviewDialog - Fullscreen dialog for reviewing all shots in sequence

This module re-exports from the refactored package for backwards compatibility.
The implementation has been decomposed into focused modules:

- shot_library/widgets/sequence_review/dialog.py - Main dialog
- shot_library/widgets/sequence_review/state.py - State dataclasses
- shot_library/widgets/sequence_review/timeline_manager.py - Timeline logic
- shot_library/widgets/sequence_review/export_manager.py - Export functionality
- shot_library/widgets/sequence_review/shot_list_panel.py - Shot list panel
- shot_library/widgets/sequence_review/preload_worker.py - Background preloading

For new code, import directly from the package:
    from shot_library.widgets.sequence_review import SequenceReviewDialog
"""

# Re-export for backwards compatibility
from .sequence_review import (
    SequenceReviewDialog,
    ShotListPanel,
    PreloadWorker,
    PlaybackState,
    TimelineState,
    PreloadState,
    SequenceTimelineManager,
    SequenceExportManager,
)

__all__ = ['SequenceReviewDialog', 'ShotListPanel']
