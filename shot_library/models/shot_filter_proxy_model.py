"""
ShotFilterProxyModel - Filtering for shots (no sorting)

Pattern: Proxy pattern with QSortFilterProxyModel
Adapted from: AnimationFilterProxyModel for shot domain

CRITICAL: Storyboard Law - Shots display in editorial order ONLY.
This proxy model provides filtering but NEVER reorders shots.
The lessThan() method always maintains source order.
"""

from typing import Optional, Set
from PyQt6.QtCore import QSortFilterProxyModel, QModelIndex, Qt

from .shot_list_model import ShotRole


class ShotFilterProxyModel(QSortFilterProxyModel):
    """
    Proxy model for filtering shots (no sorting).

    Features:
    - Instant text search (name, sequence, shot number)
    - Status filtering (WIP, Review, Approved, Blocked)
    - Sequence filtering
    - Episode filtering
    - Case-insensitive search
    - Performance: Uses Qt's built-in caching

    CRITICAL: No sorting is ever applied.
    - lessThan() always returns left.row() < right.row()
    - This preserves editorial order from the source model
    - The Storyboard Law (FR-017, FR-018) requires shots to ALWAYS
      display in editorial order. Filtering hides shots but never reorders them.

    Usage:
        proxy = ShotFilterProxyModel()
        proxy.setSourceModel(shot_list_model)
        proxy.set_search_text("SQ010")
        proxy.set_status_filter({"WIP", "Review"})
        view.setModel(proxy)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Filter criteria
        self._search_text: str = ""
        self._filter_statuses: Set[str] = set()  # Empty = all statuses
        self._filter_episodes: Set[int] = set()  # Empty = all episodes
        self._filter_sequences: Set[int] = set()  # Empty = all sequences
        self._with_playblast_only: bool = False
        self._with_warnings_only: bool = False
        self._filter_folder_path: str = ""

        # Shot version filtering - show only latest by default
        self._show_latest_only: bool = True

        # File type filters (default: show all that have these)
        self._require_mp4: bool = True  # Show shots with playblasts
        self._require_blend: bool = True  # Show shots with .blend files

        # Multi-camera reference file filtering
        # Default: Hide view shots, show only standalone and masters
        self._hide_view_shots: bool = True

        # Configure filtering (but NOT sorting!)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setDynamicSortFilter(True)  # Auto-refilter on data changes

        # CRITICAL: Disable sorting entirely
        # We never want the proxy to reorder items
        self.setSortRole(Qt.ItemDataRole.DisplayRole)

    # ==================== FILTER SETTERS ====================

    def set_search_text(self, text: str):
        """
        Set search text filter.

        Searches in:
        - Shot name
        - Sequence number (as string)
        - Episode number (as string)
        - Shot number (as string)

        Args:
            text: Search query
        """
        if self._search_text != text:
            self._search_text = text.strip().lower()
            self.invalidateFilter()

    def set_status_filter(self, statuses: Set[str]):
        """
        Set status filter.

        Args:
            statuses: Set of status strings (e.g., {"WIP", "Review"})
                     Empty set = show all statuses
        """
        if self._filter_statuses != statuses:
            self._filter_statuses = statuses
            self.invalidateFilter()

    def add_status_filter(self, status: str):
        """Add single status to filter"""
        self._filter_statuses.add(status)
        self.invalidateFilter()

    def remove_status_filter(self, status: str):
        """Remove single status from filter"""
        self._filter_statuses.discard(status)
        self.invalidateFilter()

    def clear_status_filter(self):
        """Clear all status filters (show all)"""
        if self._filter_statuses:
            self._filter_statuses.clear()
            self.invalidateFilter()

    def set_episode_filter(self, episodes: Set[int]):
        """
        Set episode filter.

        Args:
            episodes: Set of episode numbers to show
                     Empty set = show all episodes
        """
        if self._filter_episodes != episodes:
            self._filter_episodes = episodes
            self.invalidateFilter()

    def set_sequence_filter(self, sequences: Set[int]):
        """
        Set sequence filter.

        Args:
            sequences: Set of sequence numbers to show
                      Empty set = show all sequences
        """
        if self._filter_sequences != sequences:
            self._filter_sequences = sequences
            self.invalidateFilter()

    def set_with_playblast_only(self, enabled: bool):
        """
        Filter to show only shots with playblasts.

        Args:
            enabled: True to show only shots with playblasts
        """
        if self._with_playblast_only != enabled:
            self._with_playblast_only = enabled
            self.invalidateFilter()

    def set_with_warnings_only(self, enabled: bool):
        """
        Filter to show only shots with parse warnings.

        Args:
            enabled: True to show only shots with warnings
        """
        if self._with_warnings_only != enabled:
            self._with_warnings_only = enabled
            self.invalidateFilter()

    def set_folder_filter(self, folder_path: str):
        """Filter shots to only those under the given folder path."""
        if self._filter_folder_path != folder_path:
            self._filter_folder_path = folder_path
            self.invalidateFilter()

    def clear_folder_filter(self):
        """Clear folder filter (show all shots)."""
        if self._filter_folder_path:
            self._filter_folder_path = ""
            self.invalidateFilter()

    def set_show_latest_only(self, enabled: bool):
        """
        Filter to show only latest shot versions.

        When enabled (default), only shows the latest version of each shot
        in a version group. When disabled, shows all versions.

        This respects the Storyboard Law: filtering hides rows but never
        changes their editorial order.

        Args:
            enabled: True to show only latest versions (default ON)
        """
        if self._show_latest_only != enabled:
            self._show_latest_only = enabled
            self.invalidateFilter()

    def get_show_latest_only(self) -> bool:
        """Get current show_latest_only setting."""
        return self._show_latest_only

    def set_require_mp4(self, enabled: bool):
        """
        Filter to show/hide shots based on having playblasts (MP4).

        Args:
            enabled: True to show only shots with playblasts
        """
        if self._require_mp4 != enabled:
            self._require_mp4 = enabled
            self.invalidateFilter()

    def get_require_mp4(self) -> bool:
        """Get current require_mp4 setting."""
        return self._require_mp4

    def set_require_blend(self, enabled: bool):
        """
        Filter to show/hide shots based on having .blend files.

        Args:
            enabled: True to show only shots with .blend files
        """
        if self._require_blend != enabled:
            self._require_blend = enabled
            self.invalidateFilter()

    def get_require_blend(self) -> bool:
        """Get current require_blend setting."""
        return self._require_blend

    def set_hide_view_shots(self, enabled: bool):
        """
        Filter to hide view shots from the grid (show only standalone/masters).

        When enabled (default), only shows standalone shots and master shots.
        View shots are accessed through the metadata panel of their master.

        Args:
            enabled: True to hide view shots (default ON)
        """
        if self._hide_view_shots != enabled:
            self._hide_view_shots = enabled
            self.invalidateFilter()

    def get_hide_view_shots(self) -> bool:
        """Get current hide_view_shots setting."""
        return self._hide_view_shots

    def clear_all_filters(self):
        """Clear all filters (but keep show_latest_only at its default True)"""
        changed = False

        if self._search_text:
            self._search_text = ""
            changed = True

        if self._filter_statuses:
            self._filter_statuses.clear()
            changed = True

        if self._filter_episodes:
            self._filter_episodes.clear()
            changed = True

        if self._filter_sequences:
            self._filter_sequences.clear()
            changed = True

        if self._with_playblast_only:
            self._with_playblast_only = False
            changed = True

        if self._with_warnings_only:
            self._with_warnings_only = False
            changed = True

        if self._filter_folder_path:
            self._filter_folder_path = ""
            changed = True

        # Note: show_latest_only is not cleared here as it's a view preference,
        # not a search/filter criterion. Use set_show_latest_only(False) explicitly.

        if changed:
            self.invalidateFilter()

    # ==================== CORE PROXY METHODS ====================

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        """
        Determine if row should be shown.

        FILTERING VISIBILITY LOGIC (T067):
        This method determines which shots are visible based on active filters.
        Filtering ONLY hides shots - it NEVER changes their order.

        The editorial order is preserved because:
        1. Source model rows stay in their original order
        2. This method only returns True/False for visibility
        3. lessThan() maintains source row ordering
        4. Hidden shots don't affect the positions of visible shots

        Args:
            source_row: Row in source model
            source_parent: Parent index

        Returns:
            True if row matches filters (visible), False otherwise (hidden)
        """
        source_model = self.sourceModel()
        if not source_model:
            return True

        index = source_model.index(source_row, 0, source_parent)

        # Multi-camera view filter (checked first - hide view shots from grid)
        if self._hide_view_shots:
            shot_role = source_model.data(index, ShotRole.ShotRoleRole)
            if shot_role == 'view':
                return False

        # Latest version filter (checked early - fast boolean check)
        if self._show_latest_only:
            is_latest = source_model.data(index, ShotRole.IsLatestShotVersionRole)
            # Default to True for backwards compatibility (non-versioned shots)
            if is_latest is False:  # Explicitly False, not None
                return False

        # Status filter
        if self._filter_statuses:
            status = source_model.data(index, ShotRole.StatusRole)
            if status not in self._filter_statuses:
                return False

        # Episode filter
        if self._filter_episodes:
            episode_num = source_model.data(index, ShotRole.EpisodeNumRole)
            if episode_num is None or episode_num not in self._filter_episodes:
                return False

        # Sequence filter
        if self._filter_sequences:
            sequence_num = source_model.data(index, ShotRole.SequenceNumRole)
            if sequence_num is None or sequence_num not in self._filter_sequences:
                return False

        # Folder path filter
        if self._filter_folder_path:
            shot_folder = source_model.data(index, ShotRole.FolderPathRole)
            if not shot_folder or not shot_folder.startswith(self._filter_folder_path):
                return False

        # With playblast only filter (legacy)
        if self._with_playblast_only:
            has_playblast = source_model.data(index, ShotRole.HasPlayblastRole)
            if not has_playblast:
                return False

        # MP4 filter - show only shots with playblasts
        # Exception: Master shots with views that have playblasts should show
        if self._require_mp4:
            has_playblast = source_model.data(index, ShotRole.HasPlayblastRole)
            if not has_playblast:
                # Check if this is a master with views that have playblasts
                shot_role = source_model.data(index, ShotRole.ShotRoleRole)
                has_views = source_model.data(index, ShotRole.HasViewsRole)
                if shot_role == 'master' and has_views:
                    # Master with views - allow through, views may have playblasts
                    pass
                else:
                    return False

        # Blend filter - show only shots with .blend files
        if self._require_blend:
            blend_file = source_model.data(index, ShotRole.BlendFileRole)
            if not blend_file:
                return False

        # With warnings only filter
        if self._with_warnings_only:
            parse_warning = source_model.data(index, ShotRole.ParseWarningRole)
            if not parse_warning:
                return False

        # Search text filter (last, as it's most expensive)
        if self._search_text:
            # Search in shot name
            name = source_model.data(index, ShotRole.NameRole)
            if name and self._search_text in name.lower():
                return True

            # Search in episode number
            episode_num = source_model.data(index, ShotRole.EpisodeNumRole)
            if episode_num is not None and self._search_text in str(episode_num):
                return True

            # Search in sequence number
            sequence_num = source_model.data(index, ShotRole.SequenceNumRole)
            if sequence_num is not None and self._search_text in str(sequence_num):
                return True

            # Search in shot number
            shot_num = source_model.data(index, ShotRole.ShotNumRole)
            if shot_num is not None and self._search_text in str(shot_num):
                return True

            # Search in editorial order string
            editorial_order = source_model.data(index, ShotRole.EditorialOrderRole)
            if editorial_order and self._search_text in editorial_order.lower():
                return True

            # Search in status
            status = source_model.data(index, ShotRole.StatusRole)
            if status and self._search_text in status.lower():
                return True

            # Not found in any searchable field
            return False

        # No filters active or all filters passed
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """
        Compare items for sorting.

        CRITICAL IMPLEMENTATION NOTE (T067):
        This method ALWAYS maintains source order by comparing row indices.
        No sorting is ever applied - the Storyboard Law (FR-017, FR-018)
        requires shots to display in editorial order only.

        How filtering + editorial order works:
        1. ShotListModel stores shots pre-sorted by editorial_order
        2. filterAcceptsRow() hides shots that don't match filters
        3. This lessThan() preserves source row ordering
        4. Result: Visible shots maintain their editorial order positions

        Example:
            Source: [Shot1, Shot2, Shot3, Shot4, Shot5] (editorial order)
            Filter: Hide Shot2 and Shot4
            Result: [Shot1, Shot3, Shot5] (still in editorial order)

        The filtered shots "hold their place" - Shot3 still appears after
        Shot1 and before Shot5, maintaining the storyboard sequence.

        Args:
            left: Left index
            right: Right index

        Returns:
            True if left's source row < right's source row
        """
        # FORBIDDEN: Never reorder based on any field
        # Always maintain source model order (which is editorial order)
        return left.row() < right.row()

    # ==================== GETTERS FOR CURRENT FILTERS ====================

    def get_search_text(self) -> str:
        """Get current search text"""
        return self._search_text

    def get_status_filter(self) -> Set[str]:
        """Get current status filter"""
        return self._filter_statuses.copy()

    def get_episode_filter(self) -> Set[int]:
        """Get current episode filter"""
        return self._filter_episodes.copy()

    def get_sequence_filter(self) -> Set[int]:
        """Get current sequence filter"""
        return self._filter_sequences.copy()

    def has_active_filters(self) -> bool:
        """Check if any filters are active (excluding show_latest_only default)"""
        return bool(
            self._search_text or
            self._filter_statuses or
            self._filter_episodes or
            self._filter_sequences or
            self._filter_folder_path or
            self._with_playblast_only or
            self._with_warnings_only
        )

    def has_version_filter_active(self) -> bool:
        """Check if show_latest_only filter is hiding versions"""
        return self._show_latest_only


__all__ = ['ShotFilterProxyModel']
