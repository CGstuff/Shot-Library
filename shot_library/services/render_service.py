"""
RenderService - Service layer for render management

Handles:
- Render discovery and database sync
- Proxy MP4 generation via FFmpeg
- Version management (archive current, restore from archive)
"""

import json
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.render_indexer import DiscoveredRender, RenderIndexer, get_render_indexer
from .database_service import get_database_service

logger = logging.getLogger(__name__)


class RenderService(QObject):
    """
    Service for render image sequence management.

    Features:
    - Discovers renders and syncs to database
    - Generates proxy MP4 videos for preview
    - Manages folder-based versioning (archive/restore)

    Usage:
        service = RenderService()
        service.discover_and_sync(shot_folder, shot_uuid)
        service.generate_proxy(shot_uuid, render_folder)
        version = service.archive_current(shot_uuid)
        service.restore_from_archive(shot_uuid, version)
    """

    # Signals
    render_discovered = pyqtSignal(str, object)  # shot_uuid, DiscoveredRender
    proxy_generation_started = pyqtSignal(str)  # shot_uuid
    proxy_generation_progress = pyqtSignal(str, int, int)  # shot_uuid, current, total
    proxy_generation_complete = pyqtSignal(str, str)  # shot_uuid, proxy_path
    proxy_generation_error = pyqtSignal(str, str)  # shot_uuid, error_message
    version_archived = pyqtSignal(str, int)  # shot_uuid, new_version
    version_restored = pyqtSignal(str, int)  # shot_uuid, restored_version

    # FFmpeg settings
    PROXY_FILENAME = "proxy.mp4"
    FFMPEG_PRESET = "fast"
    FFMPEG_CRF = 23

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._indexer = get_render_indexer()
        self._db = get_database_service()
        self._ffmpeg_path: Optional[str] = None
        self._ffmpeg_available: Optional[bool] = None
        self._blender_path: Optional[str] = None
        self._oiiotool_path: Optional[str] = None

    def set_blender_path(self, path: str):
        """Set the Blender executable path for EXR proxy generation."""
        self._blender_path = path

    # ==================== Discovery ====================

    def discover_and_sync(
        self,
        shot_folder: Path,
        shot_uuid: str
    ) -> List[DiscoveredRender]:
        """
        Discover renders in shot folder and sync to database.

        Args:
            shot_folder: Path to shot folder
            shot_uuid: Shot UUID for database records

        Returns:
            List of discovered renders
        """
        renders = self._indexer.discover_renders(shot_folder)

        for render in renders:
            # Upsert to database
            self._db.renders.upsert(
                shot_id=shot_uuid,
                version=render.version,
                folder_path=str(render.folder_path),
                frame_start=render.frame_start,
                frame_end=render.frame_end,
                frame_count=render.frame_count,
                extension=render.extension,
                file_pattern=render.file_pattern,
                proxy_path=str(render.proxy_path) if render.proxy_path else None,
                render_engine=render.render_engine,
                samples=render.samples,
                render_time_seconds=render.render_time_seconds,
                resolution_x=render.resolution_x,
                resolution_y=render.resolution_y,
                is_current=render.is_current,
            )

            self.render_discovered.emit(shot_uuid, render)

        return renders

    def get_current_render(self, shot_folder: Path) -> Optional[DiscoveredRender]:
        """Get current render for a shot folder."""
        return self._indexer.get_current_render(shot_folder)

    def get_archived_renders(self, shot_folder: Path) -> List[DiscoveredRender]:
        """Get all archived renders for a shot folder."""
        return self._indexer.get_archived_renders(shot_folder)

    # ==================== Proxy Generation ====================

    def is_ffmpeg_available(self) -> bool:
        """Check if FFmpeg is available."""
        if self._ffmpeg_available is None:
            self._ffmpeg_path = self._find_ffmpeg()
            self._ffmpeg_available = self._ffmpeg_path is not None
        return self._ffmpeg_available

    def _find_ffmpeg(self) -> Optional[str]:
        """Find FFmpeg executable."""
        # Try common paths
        candidates = ["ffmpeg", "ffmpeg.exe"]

        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "-version"],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    return candidate
            except (subprocess.SubprocessError, FileNotFoundError):
                continue

        return None

    def is_oiiotool_available(self) -> bool:
        """Check if oiiotool is available."""
        return self._find_oiiotool() is not None

    def _find_oiiotool(self) -> Optional[str]:
        """Find oiiotool executable in assets/bin/ or system PATH."""
        if self._oiiotool_path:
            return self._oiiotool_path

        # Check bundled location: assets/bin/oiiotool.exe
        module_dir = Path(__file__).parent.parent.parent
        bundled = module_dir / "assets" / "bin" / "oiiotool.exe"
        if bundled.exists():
            self._oiiotool_path = str(bundled)
            logger.info(f"Found oiiotool at: {self._oiiotool_path}")
            return self._oiiotool_path

        # Try system PATH
        try:
            result = subprocess.run(['oiiotool', '--version'], capture_output=True, timeout=5)
            if result.returncode == 0:
                self._oiiotool_path = 'oiiotool'
                return self._oiiotool_path
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return None

    def generate_proxy(
        self,
        shot_uuid: str,
        render_folder: Path,
        output_filename: Optional[str] = None
    ) -> Optional[Path]:
        """
        Generate proxy MP4 from image sequence.

        Args:
            shot_uuid: Shot UUID for progress signals
            render_folder: Path to render folder (current/ or _archive/vXXX/)
            output_filename: Optional custom output filename

        Returns:
            Path to generated proxy or None on failure
        """
        if not self.is_ffmpeg_available():
            self.proxy_generation_error.emit(shot_uuid, "FFmpeg not found")
            return None

        # Discover sequence info
        render = self._indexer._discover_in_folder(
            render_folder,
            render_folder.parent.parent,  # shot_folder
            version=0,
            is_current=True
        )

        if not render:
            self.proxy_generation_error.emit(shot_uuid, "No image sequence found")
            return None

        self.proxy_generation_started.emit(shot_uuid)

        # Generate proxy filename: {shot_name}_RD_v001.mp4 (in Render/ folder, not current/)
        # render_folder is Render/current/ or Render/_archive/vXXX/
        render_parent = render_folder.parent  # Render/ folder
        shot_folder = render_parent.parent    # shot folder
        shot_name = shot_folder.name

        if output_filename:
            output_path = render_parent / output_filename
        else:
            # Determine version from folder (current = v001, archive = vXXX)
            if render_folder.name == "current":
                version = 1
            else:
                # Extract version from folder name like "v001"
                try:
                    version = int(render_folder.name[1:])
                except (ValueError, IndexError):
                    version = 1

            proxy_filename = f"{shot_name}_RD_v{version:03d}.mp4"
            output_path = render_parent / proxy_filename

        input_pattern = render_folder / render.file_pattern

        try:
            # For EXR files, use oiiotool or Blender (FFmpeg has LIMITED EXR support - no multilayer)
            is_exr = render.extension.lower() == ".exr"
            success = False

            if is_exr:
                # Method 1: Use oiiotool + FFmpeg (convert EXR→PNG→MP4)
                if self.is_oiiotool_available():
                    logger.info(f"Using oiiotool for EXR proxy: {render_folder}")
                    success = self._generate_proxy_with_oiiotool(
                        render_folder=render_folder,
                        output_path=output_path,
                        frame_start=render.frame_start,
                        frame_end=render.frame_end,
                        file_pattern=render.file_pattern,
                        shot_uuid=shot_uuid
                    )

                # Method 2: Use Blender's VSE for EXR
                if not success and self._blender_path:
                    logger.info(f"Using Blender for EXR proxy: {render_folder}")
                    success = self._generate_proxy_with_blender(
                        render_folder=render_folder,
                        output_path=output_path,
                        frame_start=render.frame_start,
                        frame_end=render.frame_end,
                        file_pattern=render.file_pattern
                    )

                # Method 3: FFmpeg fallback (limited EXR support)
                if not success:
                    logger.info("Trying FFmpeg for EXR (limited support)")
                    cmd = self._build_ffmpeg_command(
                        input_pattern=str(input_pattern),
                        output_path=str(output_path),
                        frame_start=render.frame_start,
                        extension=render.extension
                    )
                    result = subprocess.run(cmd, capture_output=True, timeout=600)
                    success = result.returncode == 0
                    if not success:
                        error_msg = result.stderr.decode()[:500]
                        logger.error(f"FFmpeg error: {error_msg}")
            else:
                # Non-EXR formats - use FFmpeg
                cmd = self._build_ffmpeg_command(
                    input_pattern=str(input_pattern),
                    output_path=str(output_path),
                    frame_start=render.frame_start,
                    extension=render.extension
                )
                logger.info(f"Running FFmpeg: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, timeout=600)
                success = result.returncode == 0
                if not success:
                    error_msg = result.stderr.decode()[:500]
                    logger.error(f"FFmpeg error: {error_msg}")

            if not success:
                self.proxy_generation_error.emit(shot_uuid, "Proxy generation failed")
                return None

            # Create JSON metadata sidecar file
            json_path = self._write_proxy_metadata(
                output_path=output_path,
                render=render,
                shot_name=shot_name,
                version=version if not output_filename else 1
            )

            # Update database
            db_render = self._db.renders.get_by_folder_path(str(render_folder))
            if db_render:
                self._db.renders.update(
                    db_render['id'],
                    proxy_path=str(output_path)
                )

            self.proxy_generation_complete.emit(shot_uuid, str(output_path))
            return output_path

        except subprocess.TimeoutExpired:
            self.proxy_generation_error.emit(shot_uuid, "Proxy generation timed out")
            return None
        except Exception as e:
            logger.error(f"Proxy generation error: {e}")
            self.proxy_generation_error.emit(shot_uuid, str(e))
            return None

    def _build_ffmpeg_command(
        self,
        input_pattern: str,
        output_path: str,
        frame_start: int,
        extension: str
    ) -> List[str]:
        """
        Build FFmpeg command for proxy generation.

        Supports all common render formats: PNG, JPEG, TGA, TIFF, EXR, HDR, DPX.
        For linear/HDR formats (EXR, HDR, DPX), applies gamma correction for proper display.

        Args:
            input_pattern: Input file pattern (e.g., "shot_%04d.exr")
            output_path: Output MP4 path
            frame_start: Starting frame number
            extension: File extension

        Returns:
            FFmpeg command list
        """
        cmd = [self._ffmpeg_path, "-y"]

        # HDR/linear formats need special handling
        hdr_formats = {".exr", ".hdr", ".dpx"}
        is_hdr = extension.lower() in hdr_formats

        # Input options (MUST come before -i)
        if is_hdr:
            # Apply gamma 2.2 transfer characteristic for linear input (EXR is gamma 1.0)
            # -apply_trc is the correct FFmpeg option (not -gamma which is ImageMagick)
            cmd.extend(["-apply_trc", "gamma22"])

        cmd.extend(["-start_number", str(frame_start)])
        cmd.extend(["-framerate", "24"])
        cmd.extend(["-i", input_pattern])

        # Video filter chain
        vf_filters = []

        if is_hdr:
            # Apply inverse gamma (1/2.4 ≈ 0.4167) to convert linear to sRGB
            vf_filters.append("lutrgb=r=gammaval(0.4167):g=gammaval(0.4167):b=gammaval(0.4167)")

        # Always convert to yuv420p for maximum compatibility
        vf_filters.append("format=yuv420p")

        cmd.extend(["-vf", ",".join(vf_filters)])

        # H.264 encoding
        cmd.extend([
            "-c:v", "libx264",
            "-preset", self.FFMPEG_PRESET,
            "-crf", str(self.FFMPEG_CRF),
        ])

        cmd.append(output_path)
        return cmd

    def _build_ffmpeg_command_multilayer(
        self,
        input_pattern: str,
        output_path: str,
        frame_start: int
    ) -> List[str]:
        """
        Build FFmpeg command specifically for Multi-Layer EXR.

        Uses -layer flag to select the Combined pass from Blender's multilayer EXR.

        Args:
            input_pattern: Input file pattern
            output_path: Output MP4 path
            frame_start: Starting frame number

        Returns:
            FFmpeg command list
        """
        # -apply_trc gamma22 applies 2.2 gamma to linear EXR data (MUST come before -i)
        # Note: FFmpeg's EXR decoder will use the first/default layer for multilayer EXR
        return [
            self._ffmpeg_path, "-y",
            "-apply_trc", "gamma22",  # Apply 2.2 gamma to linear input
            "-start_number", str(frame_start),
            "-framerate", "24",
            "-i", input_pattern,
            "-vf", "lutrgb=r=gammaval(0.4167):g=gammaval(0.4167):b=gammaval(0.4167),format=yuv420p",
            "-c:v", "libx264",
            "-preset", self.FFMPEG_PRESET,
            "-crf", str(self.FFMPEG_CRF),
            output_path
        ]

    def _generate_proxy_with_oiiotool(
        self,
        render_folder: Path,
        output_path: Path,
        frame_start: int,
        frame_end: int,
        file_pattern: str,
        shot_uuid: str = "",
        existing_png_dir: Optional[Path] = None
    ) -> bool:
        """
        Generate proxy MP4 from EXR sequence using oiiotool.

        Converts EXR frames to PNG in temp folder, then uses FFmpeg to create MP4.
        Can optionally reuse already-converted PNGs from preview (existing_png_dir).

        Args:
            render_folder: Path to folder containing EXR files
            output_path: Path for output MP4
            frame_start: First frame number
            frame_end: Last frame number
            file_pattern: Frame pattern (e.g., "shot_%04d.exr")
            shot_uuid: Shot UUID for progress signals
            existing_png_dir: Optional path to directory with pre-converted PNGs

        Returns:
            True if successful
        """
        oiiotool = self._find_oiiotool()
        if not oiiotool:
            logger.error("oiiotool not available")
            return False

        temp_dir = None
        cleanup_temp = True

        try:
            # Check if we can reuse existing PNGs from preview
            if existing_png_dir and existing_png_dir.exists():
                temp_dir = existing_png_dir
                cleanup_temp = False  # Don't delete - progress_panel manages it
                logger.info(f"Reusing {len(list(temp_dir.glob('*.png')))} pre-converted PNGs")
            else:
                # Create temp directory for PNG frames
                temp_dir = Path(tempfile.mkdtemp(prefix="exr_proxy_"))
                logger.info(f"Converting {frame_end - frame_start + 1} EXR frames to PNG...")

                # Convert each EXR frame to PNG
                for frame_num in range(frame_start, frame_end + 1):
                    exr_path = render_folder / (file_pattern % frame_num)
                    if not exr_path.exists():
                        continue

                    png_path = temp_dir / f"{exr_path.stem}.png"

                    if not self._convert_exr_to_png(exr_path, png_path):
                        logger.warning(f"Failed to convert frame {frame_num}")
                        continue

                    # Emit progress (first 50% is conversion)
                    progress = int((frame_num - frame_start + 1) / (frame_end - frame_start + 1) * 50)
                    self.proxy_generation_progress.emit(shot_uuid, progress, 100)

            # Find all PNGs and create a numbered sequence for FFmpeg
            png_files = sorted(temp_dir.glob("*.png"))
            if not png_files:
                logger.error("No PNG files found for proxy generation")
                return False

            # Create a temp dir with numbered sequence for FFmpeg
            ffmpeg_temp_dir = Path(tempfile.mkdtemp(prefix="ffmpeg_seq_"))
            try:
                png_pattern = "frame_%04d.png"
                for i, png_file in enumerate(png_files, start=1):
                    dest = ffmpeg_temp_dir / (png_pattern % i)
                    shutil.copy2(png_file, dest)

                # Use FFmpeg to create MP4 from PNG sequence
                png_input = str(ffmpeg_temp_dir / png_pattern)
                cmd = [
                    self._ffmpeg_path, "-y",
                    "-framerate", "24",
                    "-i", png_input,
                    "-c:v", "libx264",
                    "-preset", self.FFMPEG_PRESET,
                    "-crf", str(self.FFMPEG_CRF),
                    "-pix_fmt", "yuv420p",
                    str(output_path)
                ]

                logger.info(f"Creating MP4 from {len(png_files)} PNG frames...")
                result = subprocess.run(cmd, capture_output=True, timeout=600)

                if result.returncode == 0 and output_path.exists():
                    logger.info(f"oiiotool proxy generation successful: {output_path}")
                    return True
                else:
                    stderr = result.stderr.decode()[:500] if result.stderr else "Unknown error"
                    logger.error(f"FFmpeg error creating MP4: {stderr}")
                    return False
            finally:
                # Always clean up ffmpeg temp dir
                shutil.rmtree(ffmpeg_temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"oiiotool proxy generation error: {e}")
            return False
        finally:
            # Cleanup temp directory (only if we created it)
            if cleanup_temp and temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

    def _convert_exr_to_png(self, exr_path: Path, png_path: Path) -> bool:
        """
        Convert single EXR file to PNG using oiiotool.

        Args:
            exr_path: Path to EXR file
            png_path: Path for output PNG

        Returns:
            True if successful
        """
        oiiotool = self._find_oiiotool()
        if not oiiotool:
            return False

        try:
            cmd = [oiiotool, str(exr_path), '--tocolorspace', 'sRGB', '-o', str(png_path)]
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            return result.returncode == 0 and png_path.exists()
        except Exception as e:
            logger.error(f"oiiotool error for {exr_path}: {e}")
            return False

    def _generate_proxy_with_blender(
        self,
        render_folder: Path,
        output_path: Path,
        frame_start: int,
        frame_end: int,
        file_pattern: str
    ) -> bool:
        """
        Generate proxy MP4 from EXR sequence using Blender's VSE.

        Blender has FULL EXR support including multilayer, unlike FFmpeg.

        Args:
            render_folder: Path to folder containing EXR files
            output_path: Path for output MP4
            frame_start: First frame number
            frame_end: Last frame number
            file_pattern: Frame pattern (e.g., "shot_%04d.exr")

        Returns:
            True if successful
        """
        if not self._blender_path:
            return False

        # Build the first frame path to load
        first_frame_path = render_folder / (file_pattern % frame_start)

        # Python script to convert EXR sequence to MP4 using Blender's VSE
        script = f'''
import bpy

# Clear default scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# Setup VSE
scene.sequence_editor_create()
seq_editor = scene.sequence_editor

# Load image sequence
strip = seq_editor.sequences.new_image(
    name="render_sequence",
    filepath=r"{str(first_frame_path)}",
    channel=1,
    frame_start=1
)

# Extend to full sequence
strip.frame_final_duration = {frame_end - frame_start + 1}

# Get image dimensions from first frame
img = bpy.data.images.load(r"{str(first_frame_path)}")
width = img.size[0]
height = img.size[1]
bpy.data.images.remove(img)

# Setup render settings
scene.render.resolution_x = width
scene.render.resolution_y = height
scene.render.resolution_percentage = 100
scene.frame_start = 1
scene.frame_end = {frame_end - frame_start + 1}
scene.render.fps = 24

# Output as MP4
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
scene.render.ffmpeg.ffmpeg_preset = 'GOOD'
scene.render.filepath = r"{str(output_path)}"

# Color management - Standard for proper EXR display
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'

# Render animation
bpy.ops.render.render(animation=True)
'''

        try:
            cmd = [
                self._blender_path,
                '--background',
                '--python-expr', script
            ]
            logger.info(f"Running Blender for EXR proxy generation")
            result = subprocess.run(cmd, capture_output=True, timeout=1800)  # 30 min timeout

            if result.returncode == 0 and output_path.exists():
                logger.info(f"Blender proxy generation successful: {output_path}")
                return True
            else:
                stderr = result.stderr.decode()[:500] if result.stderr else "Unknown error"
                logger.error(f"Blender proxy generation failed: {stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Blender proxy generation timed out")
            return False
        except Exception as e:
            logger.error(f"Blender proxy generation error: {e}")
            return False

    def _write_proxy_metadata(
        self,
        output_path: Path,
        render: 'DiscoveredRender',
        shot_name: str,
        version: int
    ) -> Optional[Path]:
        """
        Write JSON metadata sidecar file for render proxy.

        Args:
            output_path: Path to proxy MP4 file
            render: DiscoveredRender with sequence info
            shot_name: Name of the shot
            version: Render version number

        Returns:
            Path to JSON file or None on failure
        """
        json_path = output_path.with_suffix('.json')

        metadata = {
            'shot_name': shot_name,
            'version': version,
            'proxy_file': output_path.name,
            'source_folder': str(render.folder_path),
            'frame_start': render.frame_start,
            'frame_end': render.frame_end,
            'frame_count': render.frame_count,
            'extension': render.extension,
            'file_pattern': render.file_pattern,
            'resolution_x': render.resolution_x,
            'resolution_y': render.resolution_y,
            'render_engine': render.render_engine,
            'samples': render.samples,
            'render_time_seconds': render.render_time_seconds,
            'proxy_generated_at': datetime.now().isoformat(),
            'ffmpeg_preset': self.FFMPEG_PRESET,
            'ffmpeg_crf': self.FFMPEG_CRF,
        }

        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"Created render metadata: {json_path}")
            return json_path
        except Exception as e:
            logger.error(f"Failed to write render metadata: {e}")
            return None

    # ==================== Version Management ====================

    def archive_current(self, shot_uuid: str) -> Optional[int]:
        """
        Archive the current render to _archive/vXXX/.

        Args:
            shot_uuid: Shot UUID

        Returns:
            New version number, or None if failed
        """
        # Get shot folder from database
        shot = self._db.shots.get_by_id(shot_uuid)
        if not shot:
            logger.error(f"Shot not found: {shot_uuid}")
            return None

        shot_folder = Path(shot['folder_path'])
        render_root = shot_folder / "Render"
        current_dir = render_root / "current"

        if not current_dir.exists():
            logger.warning(f"No current render to archive: {current_dir}")
            return None

        # Determine next version number
        archive_dir = render_root / "_archive"
        next_version = self._get_next_archive_version(archive_dir)

        # Create archive folder
        version_dir = archive_dir / f"v{next_version:03d}"
        version_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Move all files from current/ to archive/vXXX/
            for item in current_dir.iterdir():
                dest = version_dir / item.name
                shutil.move(str(item), str(dest))

            # Update database
            db_render = self._db.renders.get_current_for_shot(shot_uuid)
            if db_render:
                self._db.renders.update(
                    db_render['id'],
                    is_current=False
                )
                # Update folder path
                self._db.renders.upsert(
                    shot_id=shot_uuid,
                    version=next_version,
                    folder_path=str(version_dir),
                    is_current=False
                )

            self.version_archived.emit(shot_uuid, next_version)
            logger.info(f"Archived render to version {next_version}")
            return next_version

        except Exception as e:
            logger.error(f"Failed to archive render: {e}")
            return None

    def restore_from_archive(self, shot_uuid: str, version: int) -> bool:
        """
        Restore a render from archive to current/.

        This will:
        1. Archive current render (if exists)
        2. Copy archived version to current/

        Args:
            shot_uuid: Shot UUID
            version: Version number to restore

        Returns:
            True if successful
        """
        # Get shot folder from database
        shot = self._db.shots.get_by_id(shot_uuid)
        if not shot:
            logger.error(f"Shot not found: {shot_uuid}")
            return False

        shot_folder = Path(shot['folder_path'])
        render_root = shot_folder / "Render"
        current_dir = render_root / "current"
        archive_dir = render_root / "_archive"
        version_dir = archive_dir / f"v{version:03d}"

        if not version_dir.exists():
            logger.error(f"Archive version not found: {version_dir}")
            return False

        try:
            # Archive current if it exists and has files
            if current_dir.exists() and any(current_dir.iterdir()):
                self.archive_current(shot_uuid)

            # Ensure current/ exists
            current_dir.mkdir(parents=True, exist_ok=True)

            # Copy files from archive to current
            for item in version_dir.iterdir():
                dest = current_dir / item.name
                if item.is_file():
                    shutil.copy2(str(item), str(dest))
                elif item.is_dir():
                    shutil.copytree(str(item), str(dest))

            # Update database
            self._db.renders.upsert(
                shot_id=shot_uuid,
                version=0,
                folder_path=str(current_dir),
                is_current=True
            )

            # Re-discover to sync metadata
            self.discover_and_sync(shot_folder, shot_uuid)

            self.version_restored.emit(shot_uuid, version)
            logger.info(f"Restored render from version {version}")
            return True

        except Exception as e:
            logger.error(f"Failed to restore render: {e}")
            return False

    def _get_next_archive_version(self, archive_dir: Path) -> int:
        """Get next available version number for archive."""
        if not archive_dir.exists():
            return 1

        max_version = 0
        for item in archive_dir.iterdir():
            if item.is_dir():
                match = self._indexer.ARCHIVE_VERSION_PATTERN.match(item.name)
                if match:
                    version = int(match.group(1))
                    max_version = max(max_version, version)

        return max_version + 1

    # ==================== Utility Methods ====================

    def get_render_info(self, shot_uuid: str) -> Dict:
        """
        Get summary info about renders for a shot.

        Args:
            shot_uuid: Shot UUID

        Returns:
            Dict with render summary info
        """
        renders = self._db.renders.get_for_shot(shot_uuid)
        current = self._db.renders.get_current_for_shot(shot_uuid)

        has_proxy = False
        total_frames = 0

        if current:
            has_proxy = current.get('proxy_path') is not None
            total_frames = current.get('frame_count') or 0

        return {
            'total_versions': len(renders),
            'has_current': current is not None,
            'has_proxy': has_proxy,
            'current_frame_count': total_frames,
            'current_render': current,
            'archived_versions': [r for r in renders if not r.get('is_current')]
        }

    def delete_render_version(self, shot_uuid: str, version: int) -> bool:
        """
        Delete a specific render version (files and database record).

        Args:
            shot_uuid: Shot UUID
            version: Version to delete (cannot delete version 0/current)

        Returns:
            True if deleted
        """
        if version == 0:
            logger.error("Cannot delete current render version")
            return False

        shot = self._db.shots.get_by_id(shot_uuid)
        if not shot:
            return False

        shot_folder = Path(shot['folder_path'])
        version_dir = shot_folder / "Render" / "_archive" / f"v{version:03d}"

        if not version_dir.exists():
            logger.warning(f"Version folder not found: {version_dir}")
            return False

        try:
            # Remove files
            shutil.rmtree(str(version_dir))

            # Remove from database
            db_render = self._db.renders.get_version(shot_uuid, version)
            if db_render:
                self._db.renders.delete(db_render['id'])

            logger.info(f"Deleted render version {version}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete render version: {e}")
            return False


# Singleton instance
_render_service_instance: Optional[RenderService] = None


def get_render_service() -> RenderService:
    """Get the singleton RenderService instance."""
    global _render_service_instance
    if _render_service_instance is None:
        _render_service_instance = RenderService()
    return _render_service_instance


__all__ = [
    'RenderService',
    'get_render_service',
]
