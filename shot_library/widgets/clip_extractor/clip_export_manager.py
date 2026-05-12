"""Clip Export Manager — FFmpeg trim logic."""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple


class ClipExportManager:
    """Exports video clips using FFmpeg (stream copy with re-encode fallback)."""

    def find_ffmpeg(self) -> Optional[Path]:
        """Locate the ffmpeg binary on the system PATH."""
        found = shutil.which("ffmpeg")
        return Path(found) if found else None

    def _get_reviews_folder(self, source_path: Path) -> Path:
        """Get or create the Reviews output folder next to the source video."""
        try:
            from ...services.annotated_export_service import get_reviews_folder
            return Path(get_reviews_folder(str(source_path)))
        except ImportError:
            reviews = source_path.parent / "Reviews"
            reviews.mkdir(parents=True, exist_ok=True)
            return reviews

    def _next_output_path(self, output_dir: Path, video_name: str) -> Path:
        """Return the next auto-incremented clip path (clip_001, clip_002, ...)."""
        counter = 1
        while True:
            name = f"{video_name}_clip_{counter:03d}.mp4"
            path = output_dir / name
            if not path.exists():
                return path
            counter += 1

    def export_clip(
        self,
        source_path: Path,
        in_frame: int,
        out_frame: int,
        fps: float,
        output_dir: Optional[Path] = None,
        video_name: str = "clip",
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        Export a trimmed clip using FFmpeg.

        Returns:
            (success, message, output_path)
        """
        ffmpeg = self.find_ffmpeg()
        if not ffmpeg:
            return False, "FFmpeg not found on system PATH", None

        if output_dir is None:
            output_dir = self._get_reviews_folder(source_path)

        output_path = self._next_output_path(output_dir, video_name)

        in_seconds = in_frame / fps
        duration = (out_frame - in_frame) / fps

        # Try stream copy first (fast, may be keyframe-inaccurate)
        ok, msg = self._try_export(ffmpeg, source_path, output_path,
                                   in_seconds, duration, copy=True)
        if ok:
            return True, msg, output_path

        # Fallback: re-encode for frame-accurate cut
        ok, msg = self._try_export(ffmpeg, source_path, output_path,
                                   in_seconds, duration, copy=False)
        if ok:
            return True, msg, output_path

        return False, msg, None

    @staticmethod
    def _try_export(
        ffmpeg: Path,
        source: Path,
        output: Path,
        in_seconds: float,
        duration: float,
        copy: bool,
    ) -> Tuple[bool, str]:
        codec_args = ["-c", "copy", "-avoid_negative_ts", "1"] if copy else [
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
        ]
        cmd = [
            str(ffmpeg), "-y",
            "-ss", f"{in_seconds:.4f}",
            "-i", str(source),
            "-t", f"{duration:.4f}",
            *codec_args,
            str(output),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            if result.returncode == 0 and output.exists():
                mode = "stream copy" if copy else "re-encode"
                return True, f"Exported ({mode}): {output.name}"
            return False, result.stderr[-300:] if result.stderr else "Unknown FFmpeg error"
        except subprocess.TimeoutExpired:
            return False, "FFmpeg timed out"
        except Exception as e:
            return False, str(e)
