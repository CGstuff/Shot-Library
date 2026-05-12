"""
Sequence Export Manager

Handles export functionality for sequence review:
- Export current shot as MP4
- Export full sequence (concatenated) via FFmpeg
"""

import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable

from ...utils.video_resolver import ShotVideoResolver
from ...exceptions import FFmpegNotFoundError, ExportFailedError

logger = logging.getLogger(__name__)


class SequenceExportManager:
    """
    Manages video export for sequence review.

    Supports exporting individual shots or concatenating
    all shots into a single MP4 file.
    """

    def __init__(self):
        self._ffmpeg_path: Optional[Path] = None

    def find_ffmpeg(self) -> Optional[Path]:
        """
        Find FFmpeg executable.

        Returns:
            Path to FFmpeg or None if not found
        """
        if self._ffmpeg_path and self._ffmpeg_path.exists():
            return self._ffmpeg_path

        # Try to import from annotated_export_service
        try:
            from ...services.annotated_export_service import find_ffmpeg
            path = find_ffmpeg()
            if path:
                self._ffmpeg_path = Path(path)
                return self._ffmpeg_path
        except ImportError:
            pass

        # Fallback: check common locations
        import shutil as sh
        ffmpeg = sh.which('ffmpeg')
        if ffmpeg:
            self._ffmpeg_path = Path(ffmpeg)
            return self._ffmpeg_path

        return None

    def get_reviews_folder(self, source_path: str) -> Path:
        """
        Get the reviews output folder for exports.

        Args:
            source_path: Path to source video

        Returns:
            Path to reviews folder
        """
        try:
            from ...services.annotated_export_service import get_reviews_folder
            return Path(get_reviews_folder(source_path))
        except ImportError:
            # Fallback: create Reviews folder next to source
            return Path(source_path).parent / 'Reviews'

    def export_current_shot(
        self,
        shot: Dict,
        output_dir: Optional[Path] = None
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        Export a single shot's video file.

        Args:
            shot: Shot dictionary with video paths
            output_dir: Optional output directory (default: Reviews folder)

        Returns:
            Tuple of (success, message, output_path)
        """
        # Get video path
        video_path = ShotVideoResolver.get_existing_video_path(shot)
        if not video_path:
            return False, "No video file available for this shot", None

        # Determine output path
        if output_dir is None:
            output_dir = self.get_reviews_folder(str(video_path))

        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate output filename
        shot_name = shot.get('shot_name', shot.get('name', 'shot'))
        safe_name = self._sanitize_filename(shot_name)
        output_path = output_dir / f"{safe_name}_export.mp4"

        # Handle existing file
        if output_path.exists():
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = output_dir / f"{safe_name}_export_{timestamp}.mp4"

        try:
            # Simple copy (no re-encoding needed for single shot)
            shutil.copy2(video_path, output_path)
            logger.info(f"Exported shot to: {output_path}")
            return True, f"Exported to {output_path}", output_path

        except Exception as e:
            logger.error(f"Export failed: {e}")
            return False, f"Export failed: {e}", None

    def export_sequence(
        self,
        shots: List[Dict],
        output_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        Export all shots concatenated into a single MP4.

        Uses FFmpeg concat demuxer for stream copy (fast, no re-encoding).
        Falls back to re-encoding if stream copy fails.

        Args:
            shots: List of shot dictionaries
            output_path: Optional output path (default: auto-generated)
            progress_callback: Optional callback(current, total, message)

        Returns:
            Tuple of (success, message, output_path)
        """
        # Check for FFmpeg
        ffmpeg_path = self.find_ffmpeg()
        if not ffmpeg_path:
            return False, "FFmpeg not found. Please install FFmpeg.", None

        # Collect video paths
        video_paths = []
        for shot in shots:
            path = ShotVideoResolver.get_existing_video_path(shot)
            if path:
                video_paths.append(path)

        if not video_paths:
            return False, "No video files found for any shots", None

        # Warn about missing videos
        if len(video_paths) < len(shots):
            logger.warning(
                f"Only {len(video_paths)} of {len(shots)} shots have video files"
            )

        # Determine output path
        if output_path is None:
            reviews_folder = self.get_reviews_folder(str(video_paths[0]))
            reviews_folder.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = reviews_folder / f"sequence_export_{timestamp}.mp4"

        if progress_callback:
            progress_callback(0, 100, "Preparing sequence export...")

        try:
            # Try stream copy first (fast)
            success, message = self._concat_with_stream_copy(
                ffmpeg_path, video_paths, output_path, progress_callback
            )

            if success:
                return True, message, output_path

            # Fallback to re-encoding
            logger.info("Stream copy failed, trying re-encoding...")
            if progress_callback:
                progress_callback(50, 100, "Re-encoding sequence...")

            success, message = self._concat_with_reencode(
                ffmpeg_path, video_paths, output_path, progress_callback
            )

            if success:
                return True, message, output_path

            return False, message, None

        except subprocess.TimeoutExpired:
            return False, "Export timed out. Sequence may be too long.", None
        except Exception as e:
            logger.error(f"Sequence export failed: {e}")
            return False, f"Export failed: {e}", None

    def _concat_with_stream_copy(
        self,
        ffmpeg_path: Path,
        video_paths: List[Path],
        output_path: Path,
        progress_callback: Optional[Callable] = None
    ) -> Tuple[bool, str]:
        """
        Concatenate videos using stream copy (no re-encoding).

        Args:
            ffmpeg_path: Path to FFmpeg executable
            video_paths: List of video paths to concatenate
            output_path: Output file path
            progress_callback: Optional progress callback

        Returns:
            Tuple of (success, message)
        """
        temp_dir = Path(tempfile.mkdtemp(prefix='sequence_export_'))

        try:
            # Create concat list file
            concat_file = self._create_concat_file(video_paths, temp_dir)

            if progress_callback:
                progress_callback(25, 100, "Concatenating videos...")

            # Run FFmpeg
            cmd = [
                str(ffmpeg_path),
                '-y',  # Overwrite
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c', 'copy',  # Stream copy
                str(output_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode == 0:
                logger.info(f"Sequence exported to: {output_path}")
                return True, f"Exported {len(video_paths)} shots to {output_path}"

            logger.warning(f"Stream copy failed: {result.stderr[-500:]}")
            return False, "Stream copy failed"

        finally:
            # Cleanup temp files
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

    def _concat_with_reencode(
        self,
        ffmpeg_path: Path,
        video_paths: List[Path],
        output_path: Path,
        progress_callback: Optional[Callable] = None
    ) -> Tuple[bool, str]:
        """
        Concatenate videos with re-encoding (slower but more compatible).

        Args:
            ffmpeg_path: Path to FFmpeg executable
            video_paths: List of video paths to concatenate
            output_path: Output file path
            progress_callback: Optional progress callback

        Returns:
            Tuple of (success, message)
        """
        temp_dir = Path(tempfile.mkdtemp(prefix='sequence_export_'))

        try:
            concat_file = self._create_concat_file(video_paths, temp_dir)

            if progress_callback:
                progress_callback(60, 100, "Re-encoding sequence...")

            cmd = [
                str(ffmpeg_path),
                '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-crf', '23',
                '-movflags', '+faststart',
                str(output_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800  # 30 min for re-encoding
            )

            if result.returncode == 0:
                logger.info(f"Sequence exported (re-encoded) to: {output_path}")
                return True, f"Exported {len(video_paths)} shots to {output_path}"

            error_msg = result.stderr[-500:] if result.stderr else "Unknown encoding error"
            logger.error(f"Re-encoding failed: {error_msg}")
            return False, f"Encoding failed: {error_msg}"

        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

    def _create_concat_file(self, video_paths: List[Path], temp_dir: Path) -> Path:
        """
        Create FFmpeg concat demuxer input file.

        Args:
            video_paths: List of video paths
            temp_dir: Temporary directory

        Returns:
            Path to concat file
        """
        concat_file = temp_dir / 'concat.txt'

        with open(concat_file, 'w', encoding='utf-8') as f:
            for vp in video_paths:
                # FFmpeg concat requires forward slashes and escaped quotes
                escaped_path = str(vp).replace('\\', '/').replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        return concat_file

    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize string for use as filename.

        Args:
            name: Original name

        Returns:
            Safe filename string
        """
        return "".join(c if c.isalnum() or c in '-_' else '_' for c in name)

    def open_in_explorer(self, file_path: str) -> None:
        """
        Open file location in system file explorer.

        Args:
            file_path: Path to file
        """
        if sys.platform == 'win32':
            subprocess.run(['explorer', '/select,', file_path], check=False)
        elif sys.platform == 'darwin':
            subprocess.run(['open', '-R', file_path], check=False)
        else:
            folder = str(Path(file_path).parent)
            subprocess.run(['xdg-open', folder], check=False)


__all__ = ['SequenceExportManager']
