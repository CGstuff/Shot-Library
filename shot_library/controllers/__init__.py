"""
Controllers Module - Business logic orchestration layer

This module provides controllers that coordinate workflows between
UI components and services. Controllers own business logic that
was previously embedded in MainWindow.

Pattern:
- Controllers emit signals, don't call UI directly
- Controllers use services for data access
- UI components connect to controller signals

Controllers:
- ShotScanController: Orchestrates shot discovery and sync workflow
- SelectionController: Manages selection state
- PreviewModeController: Manages preview mode (playblast/lookdev) state
"""

from .shot_scan_controller import ShotScanController
from .selection_controller import SelectionController
from .preview_mode_controller import PreviewModeController

__all__ = [
    'ShotScanController',
    'SelectionController',
    'PreviewModeController',
]
