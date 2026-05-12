"""
Video Resolver

Centralized logic for resolving which video file to use for a shot.
Replaces duplicated preview_mode resolution code in 5+ places:
- sequence_review_dialog.py (_load_shot, _init_sequence_timeline, etc.)
- video_preview_panel.py
- shot_card.py
- main_window.py
"""

from pathlib import Path
from typing import Dict, Optional, Union, List


class ShotVideoResolver:
    """
    Resolves the appropriate video path for a shot based on its preview mode.

    A shot can have multiple video sources:
    - latest_playblast_path: Latest playblast render
    - latest_lookdev_path: Latest lookdev render
    - render_proxy_path: Render proxy MP4
    - preview_path: Generic preview path

    The preview_mode setting ('playblast', 'lookdev', or 'render') determines priority.
    """

    @staticmethod
    def get_video_path(shot: Dict, fallback_to_any: bool = True) -> Optional[Path]:
        """
        Get the appropriate video path for a shot.

        Resolution order depends on shot's preview_mode:
        - 'render': render_proxy_path -> latest_playblast_path -> latest_lookdev_path -> preview_path
        - 'lookdev': latest_lookdev_path -> latest_playblast_path -> preview_path
        - 'playblast' (default): latest_playblast_path -> latest_lookdev_path -> preview_path

        Args:
            shot: Shot dictionary with video paths and preview_mode
            fallback_to_any: If True, return any available video; if False, return None
                            when preferred type is unavailable

        Returns:
            Path to video file, or None if no video available

        Example:
            path = ShotVideoResolver.get_video_path(shot)
            if path and path.exists():
                media_engine.open_video(path)
        """
        preview_mode = shot.get('preview_mode', 'playblast')

        if preview_mode == 'render':
            # Render mode: prefer render proxy, fallback to playblast/lookdev
            candidates = [
                shot.get('render_proxy_path'),
                shot.get('latest_playblast_path') if fallback_to_any else None,
                shot.get('latest_lookdev_path') if fallback_to_any else None,
                shot.get('preview_path') if fallback_to_any else None,
            ]
        elif preview_mode == 'lookdev':
            # Lookdev mode: prefer lookdev, fallback to playblast
            candidates = [
                shot.get('latest_lookdev_path'),
                shot.get('latest_playblast_path') if fallback_to_any else None,
                shot.get('preview_path') if fallback_to_any else None,
            ]
        else:
            # Playblast mode (default): prefer playblast, fallback to lookdev
            candidates = [
                shot.get('latest_playblast_path'),
                shot.get('latest_lookdev_path') if fallback_to_any else None,
                shot.get('preview_path') if fallback_to_any else None,
            ]

        # Return first valid path
        for path in candidates:
            if path:
                p = Path(path) if isinstance(path, str) else path
                return p

        return None

    @staticmethod
    def get_video_path_str(shot: Dict, fallback_to_any: bool = True) -> Optional[str]:
        """
        Get video path as string (convenience method).

        Args:
            shot: Shot dictionary
            fallback_to_any: Whether to fallback to any available video

        Returns:
            String path to video, or None
        """
        path = ShotVideoResolver.get_video_path(shot, fallback_to_any)
        return str(path) if path else None

    @staticmethod
    def get_existing_video_path(shot: Dict) -> Optional[Path]:
        """
        Get video path only if the file actually exists.

        Args:
            shot: Shot dictionary

        Returns:
            Path to existing video file, or None
        """
        path = ShotVideoResolver.get_video_path(shot)
        if path and path.exists():
            return path
        return None

    @staticmethod
    def has_video(shot: Dict) -> bool:
        """
        Check if shot has any video available.

        Args:
            shot: Shot dictionary

        Returns:
            True if shot has at least one video path
        """
        return ShotVideoResolver.get_video_path(shot) is not None

    @staticmethod
    def has_existing_video(shot: Dict) -> bool:
        """
        Check if shot has an existing video file.

        Args:
            shot: Shot dictionary

        Returns:
            True if shot has a video file that exists on disk
        """
        return ShotVideoResolver.get_existing_video_path(shot) is not None

    @staticmethod
    def get_all_video_paths(shot: Dict) -> List[Path]:
        """
        Get all available video paths for a shot.

        Args:
            shot: Shot dictionary

        Returns:
            List of all available video paths
        """
        paths = []
        for key in ('latest_playblast_path', 'latest_lookdev_path', 'render_proxy_path', 'preview_path'):
            path = shot.get(key)
            if path:
                p = Path(path) if isinstance(path, str) else path
                if p not in paths:
                    paths.append(p)
        return paths

    @staticmethod
    def get_video_type(shot: Dict) -> Optional[str]:
        """
        Determine the type of video that would be returned.

        Args:
            shot: Shot dictionary

        Returns:
            'playblast', 'lookdev', 'render', 'preview', or None
        """
        preview_mode = shot.get('preview_mode', 'playblast')

        if preview_mode == 'render':
            if shot.get('render_proxy_path'):
                return 'render'
            elif shot.get('latest_playblast_path'):
                return 'playblast'
            elif shot.get('latest_lookdev_path'):
                return 'lookdev'
        elif preview_mode == 'lookdev':
            if shot.get('latest_lookdev_path'):
                return 'lookdev'
            elif shot.get('latest_playblast_path'):
                return 'playblast'
        else:
            if shot.get('latest_playblast_path'):
                return 'playblast'
            elif shot.get('latest_lookdev_path'):
                return 'lookdev'

        if shot.get('preview_path'):
            return 'preview'

        return None

    @staticmethod
    def resolve_for_batch(shots: List[Dict]) -> List[Optional[Path]]:
        """
        Resolve video paths for multiple shots.

        Args:
            shots: List of shot dictionaries

        Returns:
            List of video paths (same order as input, None for missing)
        """
        return [ShotVideoResolver.get_existing_video_path(shot) for shot in shots]


# Convenience function for quick access
def resolve_video_path(shot: Dict) -> Optional[Path]:
    """
    Convenience function to resolve video path for a shot.

    Args:
        shot: Shot dictionary

    Returns:
        Path to video file, or None

    Example:
        from shot_library.utils.video_resolver import resolve_video_path

        path = resolve_video_path(shot)
        if path and path.exists():
            play_video(path)
    """
    return ShotVideoResolver.get_existing_video_path(shot)


__all__ = [
    'ShotVideoResolver',
    'resolve_video_path',
]
