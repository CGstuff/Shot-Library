"""
PlayblastStitcher - Combined playblast generation for multi-camera shots

Combines view playblasts into a single stitched video for master shots.
Uses ffmpeg for video concatenation.

Features:
- Auto-stitches view playblasts when they change
- Creates versioned combined playblasts
- Orders views alphabetically (cam01 before ref01)
- Skips views without playblasts (incremental stitching)
"""

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class ViewPlayblast:
    """Information about a view's playblast."""
    view_name: str  # e.g., "cam01", "ref02"
    playblast_path: Path
    version: int
    is_latest: bool = True


@dataclass
class ViewSegment:
    """Information about a view's segment in the combined playblast."""
    view_name: str
    start_time_ms: int  # Start time in milliseconds
    duration_ms: int  # Duration in milliseconds
    source_path: str  # Original playblast path


@dataclass
class CombinedPlayblast:
    """Information about a combined (stitched) playblast."""
    output_path: Path
    version: int
    source_views: List[str]  # View names included in this stitch
    segments: List[ViewSegment]  # Timing info for each view
    created_at: datetime


class PlayblastStitcher:
    """
    Stitches view playblasts into combined videos for master shots.

    Usage:
        stitcher = PlayblastStitcher()
        result = stitcher.create_combined_playblast(
            master_folder=Path("EP01_SQ005_SH005"),
            view_playblasts=[
                ViewPlayblast("cam01", Path("cam01_PB_v002.mp4"), 2),
                ViewPlayblast("ref01", Path("ref01_PB_v001.mp4"), 1),
            ]
        )
    """

    # Naming patterns for combined videos
    COMBINED_PB_PATTERN = "{shot_name}_combined_v{version:03d}.mp4"
    COMBINED_LD_PATTERN = "{shot_name}_combined_LD_v{version:03d}.mp4"

    def __init__(self, ffmpeg_path: Optional[str] = None):
        """
        Initialize the stitcher.

        Args:
            ffmpeg_path: Path to ffmpeg executable (uses PATH if not specified)
        """
        self._ffmpeg_path = ffmpeg_path or "ffmpeg"
        self._ffmpeg_available = None  # Lazy check

    def is_ffmpeg_available(self) -> bool:
        """Check if ffmpeg is available in the system."""
        if self._ffmpeg_available is None:
            try:
                result = subprocess.run(
                    [self._ffmpeg_path, "-version"],
                    capture_output=True,
                    timeout=5
                )
                self._ffmpeg_available = result.returncode == 0
            except (subprocess.SubprocessError, FileNotFoundError):
                self._ffmpeg_available = False
                logger.warning("ffmpeg not found - combined playblasts will not be available")
        return self._ffmpeg_available

    def get_combined_folder(self, master_folder: Path, media_type: str = "playblast") -> Path:
        """
        Get the folder for combined videos.

        Args:
            master_folder: Path to master shot folder
            media_type: "playblast" or "lookdev"

        Returns:
            Path to combined video storage location
        """
        folder_name = "PlayBlast" if media_type == "playblast" else "Lookdev"
        return master_folder / folder_name

    def get_combined_playblast_folder(self, master_folder: Path) -> Path:
        """Get the folder for combined playblasts (backward compat)."""
        return self.get_combined_folder(master_folder, "playblast")

    def get_combined_lookdev_folder(self, master_folder: Path) -> Path:
        """Get the folder for combined lookdevs."""
        return self.get_combined_folder(master_folder, "lookdev")

    def get_next_combined_version(self, master_folder: Path, shot_name: str, media_type: str = "playblast") -> int:
        """
        Get the next version number for combined video.

        Args:
            master_folder: Path to master shot folder
            shot_name: Shot name for filename pattern
            media_type: "playblast" or "lookdev"

        Returns:
            Next version number (starts at 1)
        """
        combined_folder = self.get_combined_folder(master_folder, media_type)
        if not combined_folder.exists():
            return 1

        # Find existing combined videos
        if media_type == "lookdev":
            pattern = f"{shot_name}_combined_LD_v*.mp4"
        else:
            pattern = f"{shot_name}_combined_v*.mp4"
        existing = list(combined_folder.glob(pattern))

        if not existing:
            return 1

        # Extract version numbers
        versions = []
        for path in existing:
            try:
                stem = path.stem
                version_str = stem.split("_v")[-1]
                versions.append(int(version_str))
            except (ValueError, IndexError):
                continue

        return max(versions) + 1 if versions else 1

    def create_combined_video(
        self,
        master_folder: Path,
        shot_name: str,
        view_videos: List[ViewPlayblast],
        media_type: str = "playblast",
    ) -> Optional[CombinedPlayblast]:
        """
        Create a combined video from view videos.

        Args:
            master_folder: Path to master shot folder
            shot_name: Shot name (e.g., "EP01_SQ005_SH005")
            view_videos: List of view videos to combine
            media_type: "playblast" or "lookdev"

        Returns:
            CombinedPlayblast info or None if failed
        """
        type_label = "lookdev" if media_type == "lookdev" else "playblast"

        if not self.is_ffmpeg_available():
            logger.error(f"ffmpeg not available - cannot create combined {type_label}")
            return None

        if not view_videos:
            logger.warning(f"No view {type_label}s provided")
            return None

        # Filter to only include existing files
        valid_videos = [
            vp for vp in view_videos
            if vp.playblast_path.exists()
        ]

        if not valid_videos:
            logger.warning(f"No valid {type_label} files found")
            return None

        # Sort alphabetically by view name (cam01 before ref01, etc.)
        valid_videos.sort(key=lambda vp: vp.view_name)

        # Get durations for each video
        segments = []
        current_time_ms = 0
        for vp in valid_videos:
            duration_ms = self._get_video_duration_ms(vp.playblast_path)
            segments.append(ViewSegment(
                view_name=vp.view_name,
                start_time_ms=current_time_ms,
                duration_ms=duration_ms,
                source_path=str(vp.playblast_path)
            ))
            current_time_ms += duration_ms

        # Get next version
        version = self.get_next_combined_version(master_folder, shot_name, media_type)

        # Prepare output path
        combined_folder = self.get_combined_folder(master_folder, media_type)
        combined_folder.mkdir(parents=True, exist_ok=True)

        if media_type == "lookdev":
            output_filename = self.COMBINED_LD_PATTERN.format(shot_name=shot_name, version=version)
        else:
            output_filename = self.COMBINED_PB_PATTERN.format(shot_name=shot_name, version=version)
        output_path = combined_folder / output_filename

        # Create concat file for ffmpeg
        success = self._concatenate_videos(
            [vp.playblast_path for vp in valid_videos],
            output_path
        )

        if not success:
            return None

        # Save JSON sidecar with segment info
        self._save_segments_json(output_path, segments, version)

        logger.info(f"Created combined {type_label}: {output_path}")

        return CombinedPlayblast(
            output_path=output_path,
            version=version,
            source_views=[vp.view_name for vp in valid_videos],
            segments=segments,
            created_at=datetime.now()
        )

    def create_combined_playblast(
        self,
        master_folder: Path,
        shot_name: str,
        view_playblasts: List[ViewPlayblast],
    ) -> Optional[CombinedPlayblast]:
        """Create a combined playblast (backward compat wrapper)."""
        return self.create_combined_video(master_folder, shot_name, view_playblasts, "playblast")

    def create_combined_lookdev(
        self,
        master_folder: Path,
        shot_name: str,
        view_lookdevs: List[ViewPlayblast],
    ) -> Optional[CombinedPlayblast]:
        """Create a combined lookdev video."""
        return self.create_combined_video(master_folder, shot_name, view_lookdevs, "lookdev")

    def _get_video_duration_ms(self, video_path: Path) -> int:
        """
        Get video duration in milliseconds using ffprobe.

        Args:
            video_path: Path to video file

        Returns:
            Duration in milliseconds, or 0 if failed
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0:
                duration_sec = float(result.stdout.decode().strip())
                return int(duration_sec * 1000)
        except Exception as e:
            logger.warning(f"Failed to get duration for {video_path}: {e}")
        return 0

    def _save_segments_json(self, output_path: Path, segments: List[ViewSegment], version: int):
        """
        Save segment timing info to JSON sidecar file.

        Args:
            output_path: Path to combined playblast
            segments: List of ViewSegment with timing info
            version: Combined playblast version
        """
        import json

        json_path = output_path.with_suffix('.json')
        data = {
            "version": version,
            "combined_file": output_path.name,
            "created_at": datetime.now().isoformat(),
            "segments": [
                {
                    "view_name": seg.view_name,
                    "start_time_ms": seg.start_time_ms,
                    "duration_ms": seg.duration_ms,
                    "source_path": seg.source_path
                }
                for seg in segments
            ]
        }

        try:
            with open(json_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved segments JSON: {json_path}")
        except Exception as e:
            logger.error(f"Failed to save segments JSON: {e}")

    def _concatenate_videos(
        self,
        input_paths: List[Path],
        output_path: Path
    ) -> bool:
        """
        Concatenate videos using ffmpeg concat demuxer.

        Args:
            input_paths: List of video file paths to concatenate
            output_path: Output file path

        Returns:
            True if successful
        """
        if len(input_paths) == 1:
            # Single video - just copy it
            return self._copy_video(input_paths[0], output_path)

        # Create temporary concat file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            delete=False,
            encoding='utf-8'
        ) as f:
            concat_file = Path(f.name)
            for path in input_paths:
                # Escape single quotes in paths
                escaped_path = str(path).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        try:
            # Run ffmpeg concat
            cmd = [
                self._ffmpeg_path,
                "-y",  # Overwrite output
                "-f", "concat",
                "-safe", "0",  # Allow absolute paths
                "-i", str(concat_file),
                "-c", "copy",  # Stream copy (fast, no re-encoding)
                str(output_path)
            ]

            logger.debug(f"Running ffmpeg: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                logger.error(f"ffmpeg failed: {result.stderr.decode()}")
                return False

            return True

        except subprocess.SubprocessError as e:
            logger.error(f"ffmpeg subprocess error: {e}")
            return False
        finally:
            # Clean up concat file
            try:
                concat_file.unlink()
            except Exception:
                pass

    def _copy_video(self, input_path: Path, output_path: Path) -> bool:
        """
        Copy a single video file (when only one view has playblast).

        Uses ffmpeg to ensure format compatibility.

        Args:
            input_path: Source video
            output_path: Destination

        Returns:
            True if successful
        """
        try:
            cmd = [
                self._ffmpeg_path,
                "-y",
                "-i", str(input_path),
                "-c", "copy",
                str(output_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60
            )

            return result.returncode == 0

        except subprocess.SubprocessError as e:
            logger.error(f"Video copy failed: {e}")
            return False

    def get_latest_combined_video(
        self,
        master_folder: Path,
        shot_name: str,
        media_type: str = "playblast"
    ) -> Optional[Path]:
        """
        Get the latest combined video for a master shot.

        Args:
            master_folder: Path to master shot folder
            shot_name: Shot name for filename pattern
            media_type: "playblast" or "lookdev"

        Returns:
            Path to latest combined video or None
        """
        combined_folder = self.get_combined_folder(master_folder, media_type)
        if not combined_folder.exists():
            return None

        if media_type == "lookdev":
            pattern = f"{shot_name}_combined_LD_v*.mp4"
        else:
            pattern = f"{shot_name}_combined_v*.mp4"
        existing = list(combined_folder.glob(pattern))

        if not existing:
            return None

        # Find highest version
        latest = None
        latest_version = 0

        for path in existing:
            try:
                stem = path.stem
                version_str = stem.split("_v")[-1]
                version = int(version_str)
                if version > latest_version:
                    latest_version = version
                    latest = path
            except (ValueError, IndexError):
                continue

        return latest

    def get_latest_combined_playblast(
        self,
        master_folder: Path,
        shot_name: str
    ) -> Optional[Path]:
        """Get the latest combined playblast (backward compat)."""
        return self.get_latest_combined_video(master_folder, shot_name, "playblast")

    def get_latest_combined_lookdev(
        self,
        master_folder: Path,
        shot_name: str
    ) -> Optional[Path]:
        """Get the latest combined lookdev."""
        return self.get_latest_combined_video(master_folder, shot_name, "lookdev")

    def list_combined_playblasts(
        self,
        master_folder: Path,
        shot_name: str
    ) -> List[Dict[str, Any]]:
        """
        List all combined playblasts for a master shot.

        Args:
            master_folder: Path to master shot folder
            shot_name: Shot name for filename pattern

        Returns:
            List of dicts with path, version, is_latest
        """
        combined_folder = self.get_combined_playblast_folder(master_folder)
        if not combined_folder.exists():
            return []

        pattern = f"{shot_name}_combined_v*.mp4"
        existing = list(combined_folder.glob(pattern))

        if not existing:
            return []

        results = []
        highest_version = 0

        for path in existing:
            try:
                stem = path.stem
                version_str = stem.split("_v")[-1]
                version = int(version_str)
                highest_version = max(highest_version, version)
                results.append({
                    'path': path,
                    'version': version,
                    'is_latest': False,  # Will be updated
                })
            except (ValueError, IndexError):
                continue

        # Mark latest
        for item in results:
            item['is_latest'] = item['version'] == highest_version

        # Sort by version descending
        results.sort(key=lambda x: x['version'], reverse=True)

        return results

    def load_segments_json(self, combined_playblast_path: Path) -> Optional[List[Dict[str, Any]]]:
        """
        Load segment timing info from JSON sidecar file.

        Args:
            combined_playblast_path: Path to combined playblast

        Returns:
            List of segment dicts with view_name, start_time_ms, duration_ms
        """
        import json

        json_path = combined_playblast_path.with_suffix('.json')
        if not json_path.exists():
            logger.warning(f"Segments JSON not found: {json_path}")
            return None

        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            return data.get('segments', [])
        except Exception as e:
            logger.error(f"Failed to load segments JSON: {e}")
            return None

    def get_view_start_time(self, combined_playblast_path: Path, view_name: str) -> Optional[int]:
        """
        Get the start time in milliseconds for a specific view in the combined playblast.

        Args:
            combined_playblast_path: Path to combined playblast
            view_name: View name to find (e.g., "cam01", "ref02")

        Returns:
            Start time in milliseconds, or None if not found
        """
        segments = self.load_segments_json(combined_playblast_path)
        if not segments:
            logger.warning(f"No segments found for {combined_playblast_path}")
            return None

        # Try exact match first
        for seg in segments:
            if seg.get('view_name') == view_name:
                return seg.get('start_time_ms', 0)

        # Try suffix match (e.g., "cam01" matches "EP01_SQ005_SH005_cam01")
        for seg in segments:
            seg_view = seg.get('view_name', '')
            if seg_view.endswith(view_name) or view_name.endswith(seg_view):
                return seg.get('start_time_ms', 0)

        logger.warning(f"View '{view_name}' not found in segments: {[s.get('view_name') for s in segments]}")
        return None


# Singleton instance
_stitcher_instance: Optional[PlayblastStitcher] = None


def get_playblast_stitcher() -> PlayblastStitcher:
    """Get the singleton PlayblastStitcher instance."""
    global _stitcher_instance
    if _stitcher_instance is None:
        _stitcher_instance = PlayblastStitcher()
    return _stitcher_instance


__all__ = [
    'PlayblastStitcher',
    'ViewPlayblast',
    'ViewSegment',
    'CombinedPlayblast',
    'get_playblast_stitcher',
]
