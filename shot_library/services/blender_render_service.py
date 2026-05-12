"""
BlenderRenderService - Blender headless render queue management

Handles:
- Extracting render info from .blend files (instant via BAT library)
- Queuing render jobs
- Running Blender in background mode
- Persisting queue to project .meta folder
"""

import json
import logging
import re
import subprocess
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable
from uuid import uuid4

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QMetaObject, Qt, Q_ARG

from ..config import Config

# Try to import blender-asset-tracer for instant .blend parsing
try:
    from blender_asset_tracer import blendfile
    from blender_asset_tracer.blendfile import iterators
    BAT_AVAILABLE = True
except ImportError as e:
    BAT_AVAILABLE = False
    # Log which Python is being used for debugging
    import sys

logger = logging.getLogger(__name__)


@dataclass
class RenderJob:
    """Represents a queued render job."""
    id: str
    shot_uuid: str
    blend_file: Path
    output_dir: Path
    scene_name: str = ""
    camera_name: str = ""
    frame_start: int = 1
    frame_end: int = 250
    render_engine: str = "CYCLES"
    samples: Optional[int] = None
    resolution_x: int = 1920
    resolution_y: int = 1080
    file_format: str = "PNG"
    output_name: str = ""  # Base filename (default: blend file stem)
    output_frame_offset: int = 0  # Offset for output file numbering (multi-camera shots)
    # Additional render settings
    resolution_scale: int = 100  # Resolution percentage (1-100)
    color_mode: str = ""  # BW, RGB, RGBA
    color_depth: str = ""  # 8, 16
    compression: Optional[int] = None  # 0-100 for PNG
    film_transparent: bool = False
    # EXR-specific settings
    exr_color_depth: str = ""  # 16, 32 (float)
    exr_codec: str = ""  # ZIP, PIZ, DWAA, DWAB, NONE
    status: str = "pending"  # pending, rendering, completed, failed, cancelled
    progress: int = 0
    current_frame: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: str = ""


@dataclass
class BlendFileInfo:
    """Information extracted from a .blend file."""
    blend_file: Path
    scenes: List[str] = field(default_factory=list)
    cameras: List[str] = field(default_factory=list)
    frame_start: int = 1
    frame_end: int = 250
    render_engine: str = "CYCLES"
    samples: int = 128
    resolution_x: int = 1920
    resolution_y: int = 1080
    file_format: str = "PNG"
    active_scene: str = ""
    active_camera: str = ""


class BlenderRenderService(QObject):
    """
    Service for Blender headless render queue management.

    Features:
    - Extract render settings from .blend files
    - Queue multiple render jobs
    - Run renders in background with progress tracking
    - Cancel running jobs

    Usage:
        service = BlenderRenderService()
        info = service.extract_blend_info(blend_file)
        job_id = service.queue_render(shot_uuid, blend_file, output_dir)
        service.cancel_job(job_id)
    """

    # Signals
    job_queued = pyqtSignal(str, dict)  # job_id, job_info
    job_started = pyqtSignal(str)  # job_id
    job_progress = pyqtSignal(str, int, int)  # job_id, current_frame, total_frames
    job_completed = pyqtSignal(str, bool)  # job_id, success
    job_cancelled = pyqtSignal(str)  # job_id
    queue_changed = pyqtSignal()
    log_output = pyqtSignal(str)  # log line from Blender output

    # Setting key for persisting Blender path
    BLENDER_PATH_SETTING = "blender_executable_path"

    # Queue persistence filename
    QUEUE_FILENAME = "render_queue.json"

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._jobs: Dict[str, RenderJob] = {}
        self._job_queue: List[str] = []  # Job IDs in queue order
        self._blend_info_cache: Dict[str, BlendFileInfo] = {}  # Cached blend info per job
        self._current_job_id: Optional[str] = None
        self._process: Optional[subprocess.Popen] = None
        self._blender_path: Optional[str] = None
        self._blender_available: Optional[bool] = None
        self._lock = threading.Lock()

        # Load saved Blender path from settings
        self._load_saved_blender_path()

        # Load persisted queue from project .meta folder
        self._load_queue()

    # ==================== Queue Persistence ====================

    def _get_queue_file_path(self) -> Optional[Path]:
        """Get path to the queue persistence file in project .meta folder."""
        try:
            meta_folder = Config.get_meta_folder()
            if meta_folder and meta_folder.exists():
                return meta_folder / self.QUEUE_FILENAME
        except Exception as e:
            logger.debug(f"Could not get queue file path: {e}")
        return None

    def _save_queue(self):
        """Save the current queue to the project .meta folder (runs in background thread)."""
        # Run in background thread to avoid UI freeze
        thread = threading.Thread(target=self._save_queue_sync, daemon=True)
        thread.start()

    def _save_queue_sync(self):
        """Synchronous queue save (called from background thread)."""
        queue_file = self._get_queue_file_path()
        if not queue_file:
            return

        try:
            with self._lock:
                # Convert jobs to serializable format
                jobs_data = []
                for job_id in self._job_queue:
                    if job_id in self._jobs:
                        job = self._jobs[job_id]
                        job_dict = self._job_to_save_dict(job)
                        # Include cached blend info if available
                        if job_id in self._blend_info_cache:
                            job_dict['blend_info'] = self._blend_info_to_dict(self._blend_info_cache[job_id])
                        jobs_data.append(job_dict)

                # Also save completed/failed jobs (for history)
                for job_id, job in self._jobs.items():
                    if job_id not in self._job_queue and job.status in ('completed', 'failed'):
                        job_dict = self._job_to_save_dict(job)
                        if job_id in self._blend_info_cache:
                            job_dict['blend_info'] = self._blend_info_to_dict(self._blend_info_cache[job_id])
                        jobs_data.append(job_dict)

            queue_file.parent.mkdir(parents=True, exist_ok=True)
            with open(queue_file, 'w', encoding='utf-8') as f:
                json.dump({'jobs': jobs_data, 'queue_order': self._job_queue}, f, indent=2)

            logger.debug(f"Saved {len(jobs_data)} jobs to {queue_file}")

        except Exception as e:
            logger.error(f"Failed to save render queue: {e}")

    def _load_queue(self):
        """Load the queue from the project .meta folder."""
        queue_file = self._get_queue_file_path()
        if not queue_file or not queue_file.exists():
            return

        try:
            with open(queue_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            jobs_data = data.get('jobs', [])
            queue_order = data.get('queue_order', [])

            with self._lock:
                self._jobs.clear()
                self._job_queue.clear()

                self._blend_info_cache.clear()

                for job_dict in jobs_data:
                    job = RenderJob(
                        id=job_dict['id'],
                        shot_uuid=job_dict.get('shot_uuid', ''),
                        blend_file=Path(job_dict['blend_file']),
                        output_dir=Path(job_dict['output_dir']),
                        scene_name=job_dict.get('scene_name', ''),
                        camera_name=job_dict.get('camera_name', ''),
                        frame_start=job_dict.get('frame_start', 1),
                        frame_end=job_dict.get('frame_end', 250),
                        render_engine=job_dict.get('render_engine', 'CYCLES'),
                        samples=job_dict.get('samples'),
                        resolution_x=job_dict.get('resolution_x', 1920),
                        resolution_y=job_dict.get('resolution_y', 1080),
                        file_format=job_dict.get('file_format', 'PNG'),
                        output_name=job_dict.get('output_name', ''),
                        output_frame_offset=job_dict.get('output_frame_offset', 0),
                        # Additional render settings
                        resolution_scale=job_dict.get('resolution_scale', 100),
                        color_mode=job_dict.get('color_mode', ''),
                        color_depth=job_dict.get('color_depth', ''),
                        compression=job_dict.get('compression'),
                        film_transparent=job_dict.get('film_transparent', False),
                        # EXR-specific settings
                        exr_color_depth=job_dict.get('exr_color_depth', ''),
                        exr_codec=job_dict.get('exr_codec', ''),
                        status=job_dict.get('status', 'pending'),
                    )
                    self._jobs[job.id] = job

                    # Restore cached blend info if available
                    blend_info_dict = job_dict.get('blend_info')
                    if blend_info_dict:
                        self._blend_info_cache[job.id] = self._dict_to_blend_info(blend_info_dict, job.blend_file)

                # Restore queue order (only pending jobs)
                for job_id in queue_order:
                    if job_id in self._jobs and self._jobs[job_id].status == 'pending':
                        self._job_queue.append(job_id)

            logger.info(f"Loaded {len(self._jobs)} jobs from {queue_file}")

        except Exception as e:
            logger.error(f"Failed to load render queue: {e}")

    def reload_queue(self):
        """
        Reload the queue from the current project's .meta folder.

        Call this when switching projects to load the new project's queue.
        """
        # Clear current queue (except running job)
        with self._lock:
            if self._current_job_id:
                # Keep the running job, clear others
                current_job = self._jobs.get(self._current_job_id)
                current_blend_info = self._blend_info_cache.get(self._current_job_id)
                self._jobs.clear()
                self._job_queue.clear()
                self._blend_info_cache.clear()
                if current_job:
                    self._jobs[self._current_job_id] = current_job
                if current_blend_info:
                    self._blend_info_cache[self._current_job_id] = current_blend_info
            else:
                self._jobs.clear()
                self._job_queue.clear()
                self._blend_info_cache.clear()

        # Load from new project
        self._load_queue()
        self.queue_changed.emit()

    def get_cached_blend_info(self, job_id: str) -> Optional[BlendFileInfo]:
        """Get cached blend info for a job (no Blender subprocess call)."""
        return self._blend_info_cache.get(job_id)

    def cache_blend_info(self, job_id: str, blend_info: BlendFileInfo):
        """Cache blend info for a job."""
        self._blend_info_cache[job_id] = blend_info
        self._save_queue()

    def _job_to_save_dict(self, job: RenderJob) -> Dict:
        """Convert RenderJob to dict for saving to JSON."""
        return {
            'id': job.id,
            'shot_uuid': job.shot_uuid,
            'blend_file': str(job.blend_file),
            'output_dir': str(job.output_dir),
            'scene_name': job.scene_name,
            'camera_name': job.camera_name,
            'frame_start': job.frame_start,
            'frame_end': job.frame_end,
            'render_engine': job.render_engine,
            'samples': job.samples,
            'resolution_x': job.resolution_x,
            'resolution_y': job.resolution_y,
            'file_format': job.file_format,
            'output_name': job.output_name,
            'output_frame_offset': job.output_frame_offset,
            # Additional render settings
            'resolution_scale': job.resolution_scale,
            'color_mode': job.color_mode,
            'color_depth': job.color_depth,
            'compression': job.compression,
            'film_transparent': job.film_transparent,
            # EXR-specific settings
            'exr_color_depth': job.exr_color_depth,
            'exr_codec': job.exr_codec,
            'status': job.status,
        }

    def _blend_info_to_dict(self, info: BlendFileInfo) -> Dict:
        """Convert BlendFileInfo to dict for saving to JSON."""
        return {
            'scenes': info.scenes,
            'cameras': info.cameras,
            'frame_start': info.frame_start,
            'frame_end': info.frame_end,
            'render_engine': info.render_engine,
            'samples': info.samples,
            'resolution_x': info.resolution_x,
            'resolution_y': info.resolution_y,
            'file_format': info.file_format,
            'active_scene': info.active_scene,
            'active_camera': info.active_camera,
        }

    def _dict_to_blend_info(self, data: Dict, blend_file: Path) -> BlendFileInfo:
        """Convert dict back to BlendFileInfo."""
        return BlendFileInfo(
            blend_file=blend_file,
            scenes=data.get('scenes', []),
            cameras=data.get('cameras', []),
            frame_start=data.get('frame_start', 1),
            frame_end=data.get('frame_end', 250),
            render_engine=data.get('render_engine', 'CYCLES'),
            samples=data.get('samples', 128),
            resolution_x=data.get('resolution_x', 1920),
            resolution_y=data.get('resolution_y', 1080),
            file_format=data.get('file_format', 'PNG'),
            active_scene=data.get('active_scene', ''),
            active_camera=data.get('active_camera', ''),
        )

    def _load_saved_blender_path(self):
        """Load Blender path from app settings if available."""
        try:
            from .database_service import get_database_service
            db = get_database_service()
            saved_path = db.get_app_setting(self.BLENDER_PATH_SETTING)
            if saved_path:
                self._blender_path = saved_path
                logger.info(f"Loaded saved Blender path: {saved_path}")
        except Exception as e:
            logger.debug(f"Could not load saved Blender path: {e}")

    # ==================== Blender Detection ====================

    def is_blender_available(self) -> bool:
        """Check if Blender is available."""
        if self._blender_available is None:
            # Only auto-find if no custom path set
            if self._blender_path is None:
                self._blender_path = self._find_blender()
            self._blender_available = self._verify_blender(self._blender_path)
        return self._blender_available

    def _verify_blender(self, path: Optional[str]) -> bool:
        """Verify a Blender path works."""
        if not path:
            return False
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _find_blender(self) -> Optional[str]:
        """Find Blender executable."""
        candidates = [
            "blender",
            "blender.exe",
            # Common Windows paths
            r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 3.5\blender.exe",
        ]

        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return candidate
            except (subprocess.SubprocessError, FileNotFoundError):
                continue

        return None

    def set_blender_path(self, path: str):
        """Set custom Blender path, verify it works, and save to settings."""
        self._blender_path = path
        self._blender_available = self._verify_blender(path)

        # Save to app settings if valid
        if self._blender_available:
            try:
                from .database_service import get_database_service
                db = get_database_service()
                db.set_app_setting(self.BLENDER_PATH_SETTING, path)
                logger.info(f"Saved Blender path to settings: {path}")
            except Exception as e:
                logger.warning(f"Could not save Blender path to settings: {e}")

    # ==================== Blend File Info ====================

    def extract_blend_info_fast(self, blend_file: Path) -> Optional[BlendFileInfo]:
        """
        Extract render settings from a .blend file instantly using BAT.

        This parses the .blend file directly without launching Blender.

        Args:
            blend_file: Path to .blend file

        Returns:
            BlendFileInfo or None on failure
        """
        if not BAT_AVAILABLE:
            logger.warning("blender-asset-tracer not installed, cannot extract blend info fast")
            return None

        if not blend_file.exists():
            logger.error(f"Blend file not found: {blend_file}")
            return None

        try:
            bf = blendfile.open_cached(blend_file)

            # Get scenes
            scene_blocks = bf.find_blocks_from_code(b'SC')
            scenes = []
            active_scene = None
            scene_block = None

            for block in scene_blocks:
                try:
                    name = block[b'id', b'name'].decode('utf8').lstrip('\x00')
                    # Remove 'SC' prefix if present
                    if name.startswith('SC'):
                        name = name[2:]
                    scenes.append(name)
                    if scene_block is None:
                        scene_block = block
                        active_scene = name
                except Exception:
                    continue

            if not scene_block:
                logger.warning(f"No scenes found in {blend_file}")
                blendfile.close_all_cached()
                return BlendFileInfo(blend_file=blend_file)

            # Extract render settings from scene
            try:
                frame_start = scene_block[b'r', b'sfra']
            except Exception:
                frame_start = 1

            try:
                frame_end = scene_block[b'r', b'efra']
            except Exception:
                frame_end = 250

            try:
                engine = scene_block[b'r', b'engine'].decode('utf8').rstrip('\x00')
            except Exception:
                engine = "CYCLES"

            try:
                resolution_x = scene_block[b'r', b'xsch']
            except Exception:
                resolution_x = 1920

            try:
                resolution_y = scene_block[b'r', b'ysch']
            except Exception:
                resolution_y = 1080

            try:
                # Get resolution percentage and apply it
                size_pct = scene_block[b'r', b'size']
                resolution_x = int(resolution_x * size_pct / 100)
                resolution_y = int(resolution_y * size_pct / 100)
            except Exception:
                pass

            # Get file format
            # NOTE: BAT's format reading is unreliable for Blender 5.0+ (struct layout changed)
            # Default to PNG - users can override in Render Manager settings panel
            file_format = 'PNG'

            # Get cameras
            cameras = []
            active_camera = ""
            camera_blocks = bf.find_blocks_from_code(b'OB')
            for block in camera_blocks:
                try:
                    obj_type = block[b'type']
                    # Type 11 = Camera in Blender
                    if obj_type == 11:
                        cam_name = block[b'id', b'name'].decode('utf8').lstrip('\x00')
                        if cam_name.startswith('OB'):
                            cam_name = cam_name[2:]
                        cameras.append(cam_name)
                except Exception:
                    continue

            # Try to get active camera from scene
            try:
                camera_ptr = scene_block.get_pointer(b'camera')
                if camera_ptr:
                    active_camera = camera_ptr[b'id', b'name'].decode('utf8').lstrip('\x00')
                    if active_camera.startswith('OB'):
                        active_camera = active_camera[2:]
            except Exception:
                if cameras:
                    active_camera = cameras[0]

            # Get samples (Cycles)
            samples = 128
            if engine == 'CYCLES':
                try:
                    # Cycles samples are stored in scene.cycles
                    samples = scene_block[b'cycles', b'samples'] or 128
                except Exception:
                    pass

            blendfile.close_all_cached()

            return BlendFileInfo(
                blend_file=blend_file,
                scenes=scenes,
                cameras=cameras,
                frame_start=frame_start,
                frame_end=frame_end,
                render_engine=engine,
                samples=samples,
                resolution_x=resolution_x,
                resolution_y=resolution_y,
                file_format=file_format,
                active_scene=active_scene or (scenes[0] if scenes else ""),
                active_camera=active_camera,
            )

        except Exception as e:
            logger.error(f"Failed to extract blend info with BAT: {e}")
            try:
                blendfile.close_all_cached()
            except Exception:
                pass
            return None

    def extract_blend_info(self, blend_file: Path) -> Optional[BlendFileInfo]:
        """
        Extract render settings from a .blend file using Blender.

        Args:
            blend_file: Path to .blend file

        Returns:
            BlendFileInfo or None on failure
        """
        if not self.is_blender_available():
            logger.error("Blender not available")
            return None

        if not blend_file.exists():
            logger.error(f"Blend file not found: {blend_file}")
            return None

        # Python script to extract info
        script = self._get_extract_script()

        try:
            result = subprocess.run(
                [
                    self._blender_path,
                    "-b", str(blend_file),
                    "--python-expr", script
                ],
                capture_output=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"Blender extract failed: {result.stderr.decode()[:200]}")
                return None

            # Parse JSON output from stdout
            output = result.stdout.decode()
            json_start = output.find("BLEND_INFO_JSON:")
            if json_start < 0:
                logger.error("No JSON output found from Blender")
                return None

            json_str = output[json_start + 16:].strip()
            json_end = json_str.find("\n")
            if json_end > 0:
                json_str = json_str[:json_end]

            data = json.loads(json_str)

            return BlendFileInfo(
                blend_file=blend_file,
                scenes=data.get('scenes', []),
                cameras=data.get('cameras', []),
                frame_start=data.get('frame_start', 1),
                frame_end=data.get('frame_end', 250),
                render_engine=data.get('render_engine', 'CYCLES'),
                samples=data.get('samples', 128),
                resolution_x=data.get('resolution_x', 1920),
                resolution_y=data.get('resolution_y', 1080),
                file_format=data.get('file_format', 'PNG'),
                active_scene=data.get('active_scene', ''),
                active_camera=data.get('active_camera', ''),
            )

        except subprocess.TimeoutExpired:
            logger.error("Blender extract timed out")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Blender output: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to extract blend info: {e}")
            return None

    def _get_extract_script(self) -> str:
        """Get Python script for extracting blend info."""
        return '''
import bpy
import json

scene = bpy.context.scene
render = scene.render

info = {
    "scenes": [s.name for s in bpy.data.scenes],
    "cameras": [o.name for o in bpy.data.objects if o.type == 'CAMERA'],
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "render_engine": render.engine,
    "samples": getattr(scene.cycles, 'samples', 128) if hasattr(scene, 'cycles') else 128,
    "resolution_x": render.resolution_x,
    "resolution_y": render.resolution_y,
    "file_format": render.image_settings.file_format,
    "active_scene": scene.name,
    "active_camera": scene.camera.name if scene.camera else "",
}

print("BLEND_INFO_JSON:" + json.dumps(info))
'''

    # ==================== Job Queue ====================

    def queue_render(
        self,
        shot_uuid: str,
        blend_file: Path,
        output_dir: Path,
        scene_name: str = "",
        camera_name: str = "",
        frame_start: Optional[int] = None,
        frame_end: Optional[int] = None,
        output_name: Optional[str] = None,
        output_frame_offset: int = 0,
        auto_archive: bool = True
    ) -> str:
        """
        Queue a render job instantly using BAT for fast .blend parsing.

        Args:
            shot_uuid: Shot UUID for tracking
            blend_file: Path to .blend file
            output_dir: Output directory (Render/current/)
            scene_name: Scene to render (empty = use default)
            camera_name: Camera to use (empty = use default)
            frame_start: Override start frame (None = use .blend value)
            frame_end: Override end frame (None = use .blend value)
            output_name: Override output filename base (None = use blend file stem)
            output_frame_offset: Offset for output frame numbering (for multi-camera shots)
            auto_archive: Archive existing current/ before render

        Returns:
            Job ID
        """
        # Extract blend info instantly using BAT (no Blender launch)
        info = self.extract_blend_info_fast(blend_file)
        if not info:
            # Fallback to defaults if BAT fails
            info = BlendFileInfo(blend_file=blend_file)

        job_id = str(uuid4())[:8]
        # Default output name to blend file stem without version suffix
        # e.g., "EP01_SQ005_SH010_v001.blend" -> "EP01_SQ005_SH010"
        if output_name:
            base_name = output_name
        else:
            stem = blend_file.stem
            # Strip version suffix like _v001, _v02, _V123, etc.
            base_name = re.sub(r'_[vV]\d+$', '', stem)

        # Create job with extracted info
        job = RenderJob(
            id=job_id,
            shot_uuid=shot_uuid,
            blend_file=blend_file,
            output_dir=output_dir,
            scene_name=scene_name or info.active_scene,
            camera_name=camera_name or info.active_camera,
            frame_start=frame_start if frame_start is not None else info.frame_start,
            frame_end=frame_end if frame_end is not None else info.frame_end,
            render_engine=info.render_engine,
            samples=info.samples,
            resolution_x=info.resolution_x,
            resolution_y=info.resolution_y,
            file_format=info.file_format,
            output_name=base_name,
            output_frame_offset=output_frame_offset,
        )

        with self._lock:
            self._jobs[job_id] = job
            self._job_queue.append(job_id)
            # Cache blend info for later use (e.g., showing in UI)
            self._blend_info_cache[job_id] = info

        self.job_queued.emit(job_id, self._job_to_dict(job))
        self.queue_changed.emit()

        # Persist queue to disk
        self._save_queue()

        # Don't auto-start - user must click "Start Queue" button
        return job_id

    def start_queue(self):
        """
        Start processing the render queue.

        Call this when user clicks "Start Queue" button.
        Does nothing if queue is already processing.
        """
        if self._current_job_id is None:
            self._process_next_job()

    def reorder_queue(self, new_order: List[str]):
        """
        Reorder the job queue.

        Args:
            new_order: List of job IDs in desired order
        """
        with self._lock:
            # Filter to only include valid pending jobs
            valid_order = [
                jid for jid in new_order
                if jid in self._jobs and self._jobs[jid].status == 'pending'
            ]
            self._job_queue = valid_order
            logger.info(f"[SERVICE] Queue reordered: {self._job_queue}")

        self._save_queue()

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a queued or running job.

        Args:
            job_id: Job ID to cancel

        Returns:
            True if cancelled
        """
        import time
        logger.info(f"[SERVICE] cancel_job called for {job_id}")
        t0 = time.perf_counter()

        cancelled = False
        was_rendering = False

        logger.info(f"[SERVICE] Acquiring lock...")
        t_lock = time.perf_counter()
        with self._lock:
            logger.info(f"[SERVICE] Lock acquired in {(time.perf_counter()-t_lock)*1000:.1f}ms")

            if job_id not in self._jobs:
                logger.info(f"[SERVICE] Job {job_id} not found in self._jobs")
                return False

            job = self._jobs[job_id]
            logger.info(f"[SERVICE] Job status: {job.status}")

            if job.status == "pending":
                logger.info(f"[SERVICE] Cancelling pending job...")
                job.status = "cancelled"
                if job_id in self._job_queue:
                    self._job_queue.remove(job_id)
                cancelled = True

            elif job.status == "rendering" and self._current_job_id == job_id:
                logger.info(f"[SERVICE] Cancelling rendering job...")
                if self._process:
                    logger.info(f"[SERVICE] Terminating process...")
                    self._process.terminate()
                job.status = "cancelled"
                self._current_job_id = None
                cancelled = True
                was_rendering = True

        # Emit signals AFTER releasing lock to avoid deadlock
        if cancelled:
            # Clean up temp files if this was a multi-camera job
            if was_rendering and job.output_frame_offset > 0:
                self._cleanup_temp_files(job)

            logger.info(f"[SERVICE] Lock released, emitting signals...")
            t1 = time.perf_counter()
            self.job_cancelled.emit(job_id)
            logger.info(f"[SERVICE] job_cancelled.emit took {(time.perf_counter()-t1)*1000:.1f}ms")

            t2 = time.perf_counter()
            self.queue_changed.emit()
            logger.info(f"[SERVICE] queue_changed.emit took {(time.perf_counter()-t2)*1000:.1f}ms")

            t3 = time.perf_counter()
            self._save_queue()
            logger.info(f"[SERVICE] _save_queue returned in {(time.perf_counter()-t3)*1000:.1f}ms")

            if was_rendering:
                self._process_next_job()

        logger.info(f"[SERVICE] cancel_job total: {(time.perf_counter()-t0)*1000:.1f}ms")
        return cancelled

    def get_job(self, job_id: str) -> Optional[Dict]:
        """Get job info by ID."""
        with self._lock:
            if job_id in self._jobs:
                return self._job_to_dict(self._jobs[job_id])
        return None

    def get_queue(self) -> List[Dict]:
        """Get all jobs in queue."""
        with self._lock:
            return [self._job_to_dict(self._jobs[jid]) for jid in self._job_queue if jid in self._jobs]

    def get_all_jobs(self) -> List[Dict]:
        """Get all jobs (including completed/cancelled)."""
        with self._lock:
            return [self._job_to_dict(job) for job in self._jobs.values()]

    def clear_completed(self):
        """Clear completed/failed/cancelled jobs from history."""
        with self._lock:
            to_remove = [
                jid for jid, job in self._jobs.items()
                if job.status in ("completed", "failed", "cancelled")
            ]
            for jid in to_remove:
                del self._jobs[jid]
        self.queue_changed.emit()
        self._save_queue()

    def remove_job(self, job_id: str) -> bool:
        """
        Completely remove a job from the queue and history.

        Unlike cancel_job which just marks a job as cancelled,
        this fully deletes it from memory and persisted storage.

        Args:
            job_id: Job ID to remove

        Returns:
            True if removed
        """
        removed = False
        was_rendering = False

        with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]

            # If rendering, terminate the process first
            if job.status == "rendering" and self._current_job_id == job_id:
                if self._process:
                    self._process.terminate()
                self._current_job_id = None
                was_rendering = True

            # Remove from queue if present
            if job_id in self._job_queue:
                self._job_queue.remove(job_id)

            # Remove from jobs dict
            del self._jobs[job_id]

            # Remove from blend info cache
            if job_id in self._blend_info_cache:
                del self._blend_info_cache[job_id]

            removed = True

        if removed:
            self.queue_changed.emit()
            self._save_queue()

            if was_rendering:
                self._process_next_job()

        return removed

    def retry_job(self, job_id: str) -> bool:
        """
        Reset a failed/completed job to pending and add it back to the queue.

        Args:
            job_id: Job ID to retry

        Returns:
            True if job was reset
        """
        with self._lock:
            if job_id not in self._jobs:
                return False
            job = self._jobs[job_id]
            if job.status not in ("failed", "completed", "cancelled"):
                return False
            job.status = "pending"
            job.progress = 0
            job.current_frame = 0
            job.error_message = ""
            job.start_time = None
            job.end_time = None
            if job_id not in self._job_queue:
                self._job_queue.append(job_id)
        self.queue_changed.emit()
        self._save_queue()
        return True

    def update_job(self, job_id: str, **kwargs) -> bool:
        """
        Update a pending job's settings.

        Args:
            job_id: Job ID to update
            **kwargs: Settings to update (file_format, resolution_x, resolution_y,
                      samples, frame_start, frame_end, etc.)

        Returns:
            True if updated
        """
        with self._lock:
            if job_id not in self._jobs:
                return False
            job = self._jobs[job_id]
            if job.status != "pending":
                logger.warning(f"Cannot update job {job_id} - status is {job.status}")
                return False

            # Update allowed fields
            allowed_fields = {
                'file_format', 'resolution_x', 'resolution_y', 'samples',
                'frame_start', 'frame_end', 'render_engine', 'scene_name',
                'camera_name', 'output_name',
                # Additional render settings
                'resolution_scale', 'color_mode', 'color_depth', 'compression', 'film_transparent',
                # EXR-specific settings
                'exr_color_depth', 'exr_codec'
            }
            for key, value in kwargs.items():
                if key in allowed_fields and hasattr(job, key):
                    setattr(job, key, value)
                    logger.info(f"Updated job {job_id}: {key} = {value}")

        self._save_queue()
        return True

    # ==================== Job Processing ====================

    def _process_next_job(self):
        """Process the next job in queue."""
        with self._lock:
            if self._current_job_id is not None:
                return  # Already processing

            if not self._job_queue:
                return  # No jobs

            job_id = self._job_queue[0]
            job = self._jobs.get(job_id)
            if not job or job.status != "pending":
                self._job_queue.pop(0)
                self._process_next_job()
                return

            self._current_job_id = job_id
            job.status = "rendering"
            job.start_time = datetime.now()

        self.job_started.emit(job_id)

        # Start render in background thread
        thread = threading.Thread(target=self._run_render, args=(job_id,), daemon=True)
        thread.start()

    def _run_render(self, job_id: str):
        """Run the render (called in background thread)."""
        job = self._jobs.get(job_id)
        if not job:
            return

        try:
            # Ensure output directory exists
            job.output_dir.mkdir(parents=True, exist_ok=True)

            # Build output path pattern
            # For multi-camera shots (offset > 0), use a temp pattern to avoid overwriting
            # previous camera's frames. They'll be renamed after render completes.
            if job.output_frame_offset > 0:
                # Use job ID to make temp files unique
                output_pattern = str(job.output_dir / f"{job.output_name}_tmp{job.id}_####")
            else:
                output_pattern = str(job.output_dir / f"{job.output_name}_####")

            # Map file format to Blender CLI format name
            # BAT uses internal names, CLI uses different names for some formats
            format_cli_map = {
                'OPENEXR': 'OPEN_EXR',
                'OPEN_EXR': 'OPEN_EXR',
                'EXR': 'OPEN_EXR',
                'MULTILAYER': 'OPEN_EXR_MULTILAYER',
            }
            output_format = format_cli_map.get(job.file_format.upper(), job.file_format.upper())

            # Video formats (FFMPEG) output single files, not sequences
            # Render manager needs image sequences for frame tracking, proxy generation, etc.
            video_formats = {'FFMPEG', 'AVI_JPEG', 'AVI_RAW', 'AVIRAW', 'AVIJPEG'}
            if output_format in video_formats:
                logger.warning(f"Video format {output_format} not supported by render manager, using PNG")
                output_format = 'PNG'

            # Build Blender command
            logger.info(f"Render job {job.id}: file_format={job.file_format}, output_format={output_format}")
            cmd = [
                self._blender_path,
                "-b", str(job.blend_file),
                "-E", job.render_engine,  # Render engine
                "-o", output_pattern,
                "-F", output_format,
                "-x", "1",  # Add file extension to output
                "-s", str(job.frame_start),
                "-e", str(job.frame_end),
            ]

            if job.scene_name:
                cmd.extend(["-S", job.scene_name])

            # Build python expression for settings that need override via bpy API
            # This allows overriding settings that don't have CLI flags
            python_overrides = []

            # Resolution (only if explicitly set via override)
            if job.resolution_x and job.resolution_y:
                python_overrides.append(f"s.render.resolution_x={job.resolution_x}")
                python_overrides.append(f"s.render.resolution_y={job.resolution_y}")

            # Resolution scale/percentage
            if job.resolution_scale and job.resolution_scale != 100:
                python_overrides.append(f"s.render.resolution_percentage={job.resolution_scale}")

            # Samples (engine-specific)
            if job.samples:
                if job.render_engine == "CYCLES":
                    python_overrides.append(f"s.cycles.samples={job.samples}")
                elif job.render_engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
                    # BLENDER_EEVEE_NEXT (4.x) was renamed to BLENDER_EEVEE (5.0+)
                    python_overrides.append(f"s.eevee.taa_render_samples={job.samples}")

            # Color mode (BW, RGB, RGBA)
            if job.color_mode:
                python_overrides.append(f"s.render.image_settings.color_mode='{job.color_mode}'")

            # Color depth (8, 16)
            if job.color_depth:
                python_overrides.append(f"s.render.image_settings.color_depth='{job.color_depth}'")

            # Compression (0-100 for PNG)
            if job.compression is not None:
                python_overrides.append(f"s.render.image_settings.compression={job.compression}")

            # Film transparent background
            if job.film_transparent:
                python_overrides.append("s.render.film_transparent=True")

            # EXR-specific settings
            if job.exr_color_depth:
                # Map to Blender exr_codec values: HALF (16-bit) or FULL (32-bit)
                use_half = (job.exr_color_depth == "16")
                python_overrides.append(f"s.render.image_settings.exr_codec={'HALF' if use_half else 'NONE'}")
                # Note: color depth for EXR is controlled by codec in Blender

            if job.exr_codec:
                # Blender EXR codec values: ZIP, PIZ, DWAA, DWAB, NONE, etc.
                python_overrides.append(f"s.render.image_settings.exr_codec='{job.exr_codec}'")

            # Add --python-expr if we have overrides
            if python_overrides:
                expr = "import bpy;s=bpy.context.scene;" + ";".join(python_overrides)
                cmd.extend(["--python-expr", expr])

            # Render animation (must be last)
            cmd.append("-a")

            logger.info(f"Starting render: {' '.join(cmd)}")

            # Run Blender
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )

            # Monitor output for progress
            total_frames = job.frame_end - job.frame_start + 1
            error_lines = []  # Capture error output

            for line in self._process.stdout:
                if job.status == "cancelled":
                    break

                # Log all output for debugging
                line_stripped = line.strip()
                if line_stripped:
                    logger.debug(f"[Blender] {line_stripped}")

                    # Emit log line to UI (thread-safe via invokeMethod)
                    QMetaObject.invokeMethod(
                        self, "_emit_log_output",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, line_stripped)
                    )

                # Capture error-related lines
                if "Error" in line or "error" in line or "Warning" in line:
                    error_lines.append(line_stripped)

                # Parse frame progress using regex for robustness
                # Blender outputs lines like "Fra:1 Mem:..." or "Fra: 1 Mem:..." (format may vary)
                frame_match = re.search(r'Fra:\s*(\d+)', line)
                if frame_match:
                    try:
                        current_frame = int(frame_match.group(1))
                        job.current_frame = current_frame
                        job.progress = int((current_frame - job.frame_start + 1) / total_frames * 100)
                        logger.info(f"[PROGRESS] Frame {current_frame}/{total_frames} = {job.progress}%")
                        # Emit from main thread using invokeMethod
                        QMetaObject.invokeMethod(
                            self, "_emit_job_progress",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, job_id),
                            Q_ARG(int, current_frame),
                            Q_ARG(int, total_frames)
                        )
                    except (ValueError, IndexError) as e:
                        logger.warning(f"[PROGRESS] Failed to parse frame: {e}")

            self._process.wait()
            return_code = self._process.returncode

            if job.status == "cancelled":
                return

            if return_code == 0:
                job.status = "completed"
                job.progress = 100

                # Apply frame offset renaming for multi-camera shots
                if job.output_frame_offset > 0:
                    self._rename_frames_with_offset(job)
            else:
                job.status = "failed"
                error_detail = "; ".join(error_lines[-3:]) if error_lines else "Check Blender output"
                job.error_message = f"Blender exited with code {return_code}: {error_detail}"
                logger.error(f"Render failed: {job.error_message}")
                # Clean up temp files on failure
                if job.output_frame_offset > 0:
                    self._cleanup_temp_files(job)

        except Exception as e:
            logger.error(f"Render failed: {e}")
            job.status = "failed"
            job.error_message = str(e)
            # Clean up temp files on failure
            if job.output_frame_offset > 0:
                self._cleanup_temp_files(job)

        finally:
            job.end_time = datetime.now()
            self._process = None

            with self._lock:
                if job_id in self._job_queue:
                    self._job_queue.remove(job_id)
                self._current_job_id = None

            # Emit signals and process next job from main thread
            QMetaObject.invokeMethod(
                self, "_on_render_finished",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, job_id),
                Q_ARG(bool, job.status == "completed")
            )

    @pyqtSlot(str, int, int)
    def _emit_job_progress(self, job_id: str, current_frame: int, total_frames: int):
        """Emit job_progress signal (called on main thread via invokeMethod)."""
        self.job_progress.emit(job_id, current_frame, total_frames)

    @pyqtSlot(str)
    def _emit_log_output(self, text: str):
        """Emit log_output signal (called on main thread via invokeMethod)."""
        self.log_output.emit(text)

    @pyqtSlot(str, bool)
    def _on_render_finished(self, job_id: str, success: bool):
        """Handle render completion (called on main thread via invokeMethod)."""
        self.job_completed.emit(job_id, success)
        self.queue_changed.emit()

        # Persist updated queue state
        self._save_queue()

        # Process next job
        self._process_next_job()

    def _rename_frames_with_offset(self, job: RenderJob):
        """
        Rename rendered frames to apply the output frame offset.

        For multi-camera shots, each camera renders to temp files to avoid
        overwriting previous cameras' frames. This method renames them to
        final names with offset applied.

        E.g., cam02 renders to shot_tmp{job_id}_0001.exr ... shot_tmp{job_id}_0020.exr
        This renames them to shot_0021.exr ... shot_0040.exr (offset=20).
        """
        if job.output_frame_offset == 0:
            return

        offset = job.output_frame_offset

        # Map file format to extension
        ext_map = {
            'PNG': 'png', 'JPEG': 'jpg', 'BMP': 'bmp',
            'TIFF': 'tif', 'TARGA': 'tga', 'TGA': 'tga',
            'OPEN_EXR': 'exr', 'OPENEXR': 'exr', 'EXR': 'exr',
            'OPEN_EXR_MULTILAYER': 'exr', 'MULTILAYER': 'exr',
            'HDR': 'hdr', 'CINEON': 'cin', 'DPX': 'dpx',
            'WEBP': 'webp', 'JP2': 'jp2',
        }
        ext = ext_map.get(job.file_format.upper(), 'png')

        logger.info(f"Renaming frames with offset {offset} ({job.frame_start}-{job.frame_end}), format={job.file_format}, ext={ext}")

        # Rename temp files to final names with offset
        # Source: {output_name}_tmp{job_id}_{frame}.png
        # Dest: {output_name}_{frame+offset}.png
        renamed_count = 0
        for frame in range(job.frame_start, job.frame_end + 1):
            src = job.output_dir / f"{job.output_name}_tmp{job.id}_{frame:04d}.{ext}"
            dst_frame = frame + offset
            dst = job.output_dir / f"{job.output_name}_{dst_frame:04d}.{ext}"

            if src.exists():
                try:
                    src.rename(dst)
                    logger.debug(f"Renamed {src.name} -> {dst.name}")
                    renamed_count += 1
                except Exception as e:
                    logger.error(f"Failed to rename {src} -> {dst}: {e}")
            else:
                logger.warning(f"Frame file not found for renaming: {src}")

        logger.info(f"Finished renaming {renamed_count} frames")

    def _cleanup_temp_files(self, job: RenderJob):
        """
        Clean up temporary render files for multi-camera jobs.

        Called when a job is cancelled or fails. Removes any temp files
        matching the pattern: {output_name}_tmp{job_id}_####.ext
        """
        if job.output_frame_offset == 0:
            return  # No temp files for first camera

        if not job.output_dir.exists():
            return

        # Find and delete temp files matching this job's pattern
        temp_pattern = f"{job.output_name}_tmp{job.id}_"
        deleted_count = 0

        try:
            for file_path in job.output_dir.iterdir():
                if file_path.is_file() and file_path.name.startswith(temp_pattern):
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        logger.debug(f"Deleted temp file: {file_path.name}")
                    except Exception as e:
                        logger.warning(f"Failed to delete temp file {file_path}: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} temp files for job {job.id}")
        except Exception as e:
            logger.error(f"Error during temp file cleanup: {e}")

    def _job_to_dict(self, job: RenderJob) -> Dict:
        """Convert RenderJob to dict for signals."""
        return {
            'id': job.id,
            'shot_uuid': job.shot_uuid,
            'blend_file': str(job.blend_file),
            'output_dir': str(job.output_dir),
            'output_name': job.output_name,
            'output_frame_offset': job.output_frame_offset,
            'scene_name': job.scene_name,
            'camera_name': job.camera_name,
            'frame_start': job.frame_start,
            'frame_end': job.frame_end,
            'render_engine': job.render_engine,
            'samples': job.samples,
            'resolution_x': job.resolution_x,
            'resolution_y': job.resolution_y,
            'file_format': job.file_format,
            # Additional render settings
            'resolution_scale': job.resolution_scale,
            'color_mode': job.color_mode,
            'color_depth': job.color_depth,
            'compression': job.compression,
            'film_transparent': job.film_transparent,
            # EXR-specific settings
            'exr_color_depth': job.exr_color_depth,
            'exr_codec': job.exr_codec,
            'status': job.status,
            'progress': job.progress,
            'current_frame': job.current_frame,
            'start_time': job.start_time.isoformat() if job.start_time else None,
            'end_time': job.end_time.isoformat() if job.end_time else None,
            'error_message': job.error_message,
        }


# Singleton instance
_blender_service_instance: Optional[BlenderRenderService] = None


def get_blender_render_service() -> BlenderRenderService:
    """Get the singleton BlenderRenderService instance."""
    global _blender_service_instance
    if _blender_service_instance is None:
        _blender_service_instance = BlenderRenderService()
    return _blender_service_instance


__all__ = [
    'BlenderRenderService',
    'BlendFileInfo',
    'RenderJob',
    'get_blender_render_service',
]
