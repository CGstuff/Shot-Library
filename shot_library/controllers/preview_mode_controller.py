"""
PreviewModeController - Manages preview mode (playblast/lookdev/render) state

This controller centralizes preview mode management and handles:
- Global preview mode (affects all shots)
- Per-shot preview mode (overrides global)
- Persistence to database

Usage:
    from shot_library.controllers import PreviewModeController

    controller = PreviewModeController(db_service=db_service)

    # Connect to signals
    controller.global_mode_changed.connect(on_global_mode_changed)
    controller.shot_mode_changed.connect(on_shot_mode_changed)

    # Set global mode
    controller.set_global_mode('lookdev')

    # Set per-shot mode
    controller.set_shot_mode('uuid', 'playblast')
"""

from typing import Optional, Set, Dict, Any

from PyQt6.QtCore import QObject, pyqtSignal

from ..events.event_bus import get_event_bus


class PreviewModeController(QObject):
    """
    Controller for managing preview mode (playblast/lookdev).

    This controller:
    - Manages global preview mode
    - Manages per-shot preview mode overrides
    - Persists per-shot mode to database
    - Emits signals for UI updates

    Signals:
        global_mode_changed: Emitted when global mode changes (str)
        shot_mode_changed: Emitted when a shot's mode changes (shot_uuid, mode)
        bulk_mode_changed: Emitted when multiple shots change (count, mode)
    """

    # Valid preview modes
    PLAYBLAST = 'playblast'
    LOOKDEV = 'lookdev'
    RENDER = 'render'
    VALID_MODES = {PLAYBLAST, LOOKDEV, RENDER}

    # Controller signals
    global_mode_changed = pyqtSignal(str)  # mode
    shot_mode_changed = pyqtSignal(str, str)  # shot_uuid, mode
    bulk_mode_changed = pyqtSignal(int, str)  # count, mode

    def __init__(self, db_service=None, event_bus=None, parent=None):
        """
        Initialize preview mode controller.

        Args:
            db_service: Database service for persistence (uses singleton if None)
            event_bus: EventBus instance (uses singleton if None)
            parent: Qt parent object
        """
        super().__init__(parent)

        if db_service is None:
            from ..services.database_service import get_database_service
            db_service = get_database_service()
        self._db_service = db_service

        self._event_bus = event_bus or get_event_bus()

        # State
        self._global_mode: str = self.PLAYBLAST

    @property
    def global_mode(self) -> str:
        """Return the current global preview mode."""
        return self._global_mode

    def set_global_mode(self, mode: str) -> bool:
        """
        Set the global preview mode.

        Args:
            mode: 'playblast', 'lookdev', or 'render'

        Returns:
            True if mode was changed, False if invalid mode
        """
        if mode not in self.VALID_MODES:
            return False

        if mode != self._global_mode:
            self._global_mode = mode
            self.global_mode_changed.emit(mode)
            self._event_bus.preview_mode_changed.emit(mode)

        return True

    def toggle_global_mode(self) -> str:
        """
        Toggle between playblast and lookdev mode.

        Returns:
            The new mode
        """
        new_mode = self.LOOKDEV if self._global_mode == self.PLAYBLAST else self.PLAYBLAST
        self.set_global_mode(new_mode)
        return new_mode

    def set_shot_mode(self, shot_uuid: str, mode: str) -> bool:
        """
        Set preview mode for a specific shot.

        Args:
            shot_uuid: UUID of the shot
            mode: 'playblast', 'lookdev', or 'render'

        Returns:
            True if successful, False otherwise
        """
        if mode not in self.VALID_MODES:
            return False

        if not shot_uuid:
            return False

        try:
            # Update in database
            success = self._db_service.shots.update(shot_uuid, display_mode=mode)

            if success:
                self.shot_mode_changed.emit(shot_uuid, mode)
                self._event_bus.shot_preview_mode_changed.emit(shot_uuid, mode)
                self._event_bus.animation_updated.emit(shot_uuid)

            return success

        except Exception as e:
            return False

    def set_selected_shots_mode(
        self,
        shot_uuids: Set[str],
        mode: str
    ) -> int:
        """
        Set preview mode for multiple selected shots.

        Args:
            shot_uuids: Set of shot UUIDs
            mode: 'playblast', 'lookdev', or 'render'

        Returns:
            Number of shots successfully updated
        """
        if mode not in self.VALID_MODES:
            return 0

        count = 0
        for uuid in shot_uuids:
            if self.set_shot_mode(uuid, mode):
                count += 1

        if count > 0:
            self.bulk_mode_changed.emit(count, mode)

        return count

    def get_shot_mode(self, shot_uuid: str) -> str:
        """
        Get the effective preview mode for a shot.

        This returns the shot's specific mode if set, otherwise the global mode.

        Args:
            shot_uuid: UUID of the shot

        Returns:
            Effective preview mode ('playblast' or 'lookdev')
        """
        if not shot_uuid:
            return self._global_mode

        try:
            shot = self._db_service.shots.get_by_id(shot_uuid)
            if shot:
                return shot.get('display_mode', self._global_mode)
        except Exception:
            pass

        return self._global_mode

    def get_effective_mode(self, shot_data: Dict[str, Any]) -> str:
        """
        Get the effective preview mode from shot data.

        Uses shot's display_mode if set, falls back to preview_mode,
        then to global mode.

        Args:
            shot_data: Shot data dict

        Returns:
            Effective preview mode
        """
        return (
            shot_data.get('display_mode') or
            shot_data.get('preview_mode') or
            self._global_mode
        )


__all__ = ['PreviewModeController']
