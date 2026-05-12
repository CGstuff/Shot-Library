"""
ThumbnailLoader - Async thumbnail loading with QThreadPool

Pattern: Background loading with QRunnable workers
Inspired by: Maya Studio Library + Hybrid plan optimizations

Shot Library additions (T087-T088):
- Video frame extraction for playblast thumbnails
- Integration with PlayblastIndexer for automatic playblast discovery
"""

import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Set, Dict, Any
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, QThreadPool
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QPixmapCache, QImage

from ..config import Config
from ..utils.gradient_utils import composite_image_on_gradient_colors
from ..utils.image_utils import load_image_as_qimage, scale_image


class ThumbnailLoadSignals(QObject):
    """Signals for ThumbnailLoadTask"""

    load_complete = pyqtSignal(str, str, QImage, float)  # uuid, cache_key, image, elapsed_ms
    load_failed = pyqtSignal(str, str)  # uuid, error_message


class ThumbnailLoadTask(QRunnable):
    """
    Background task for loading and compositing thumbnails

    Features:
    - Loads image from disk
    - Composites on gradient background
    - DPI scaling support
    - Performance timing

    Usage:
        task = ThumbnailLoadTask(uuid, thumbnail_path, gradient_colors, cache_key)
        threadpool.start(task)
    """

    def __init__(
        self,
        animation_uuid: str,
        thumbnail_path: Path,
        gradient_top: Tuple[float, float, float],
        gradient_bottom: Tuple[float, float, float],
        cache_key: str,
        canvas_size: int = 300
    ):
        super().__init__()
        self.animation_uuid = animation_uuid
        self.thumbnail_path = thumbnail_path
        self.gradient_top = gradient_top
        self.gradient_bottom = gradient_bottom
        self.cache_key = cache_key
        self.canvas_size = canvas_size
        self.signals = ThumbnailLoadSignals()
        self.start_time = time.time()

    def run(self):
        """Execute thumbnail loading task"""
        try:
            # Load source image
            source_image = load_image_as_qimage(self.thumbnail_path)
            if source_image is None:
                self.signals.load_failed.emit(
                    self.animation_uuid,
                    f"Failed to load image: {self.thumbnail_path}"
                )
                return

            # Scale to fit canvas
            source_image = scale_image(source_image, self.canvas_size, smooth=True)

            # Composite on gradient
            composited_image = composite_image_on_gradient_colors(
                source_image,
                self.gradient_top,
                self.gradient_bottom,
                self.canvas_size
            )

            # Apply DPI scaling (Maya-inspired)
            if QApplication.instance():
                screen = QApplication.primaryScreen()
                if screen:
                    device_ratio = screen.devicePixelRatio()
                    composited_image.setDevicePixelRatio(device_ratio)

            # Calculate elapsed time
            elapsed_ms = (time.time() - self.start_time) * 1000

            # Emit success signal
            self.signals.load_complete.emit(
                self.animation_uuid,
                self.cache_key,
                composited_image,
                elapsed_ms
            )

        except Exception as e:
            self.signals.load_failed.emit(
                self.animation_uuid,
                f"Thumbnail load error: {e}"
            )


class ThumbnailLoader(QObject):
    """
    Manages async thumbnail loading with QThreadPool

    Implements T166-T167:
    - T166: Configure QPixmapCache size (512MB) for large shot counts
    - T167: Load deduplication via pending_requests set

    Features:
    - Background loading with worker threads
    - Load deduplication (prevents duplicate requests)
    - Performance monitoring (cache hit rates, load times)
    - QPixmapCache integration with 512MB limit
    - DPI scaling support

    Usage:
        loader = ThumbnailLoader()
        loader.thumbnail_loaded.connect(on_thumbnail_ready)
        pixmap = loader.load_thumbnail(uuid, path, gradient_colors)
    """

    # Signals
    thumbnail_loaded = pyqtSignal(str, QPixmap)  # uuid, pixmap
    thumbnail_failed = pyqtSignal(str, str)  # uuid, error_message

    # Class-level flag to track if cache size has been configured
    _cache_configured = False

    def __init__(self, parent=None):
        super().__init__(parent)

        # T166: Configure QPixmapCache size (512MB) once at startup
        # This must be done before any cache operations
        if not ThumbnailLoader._cache_configured:
            QPixmapCache.setCacheLimit(Config.PIXMAP_CACHE_SIZE_KB)
            ThumbnailLoader._cache_configured = True

        # Thread pool for background loading
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(Config.THUMBNAIL_THREAD_COUNT)

        # T167: Load deduplication via pending_requests set
        # Prevents duplicate requests for same thumbnail
        self.pending_requests: Set[str] = set()

        # Performance monitoring (Maya-inspired)
        self.load_times: list[float] = []
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.total_requests: int = 0


    def load_thumbnail(
        self,
        animation_uuid: str,
        thumbnail_path: Path,
        gradient_top: Tuple[float, float, float],
        gradient_bottom: Tuple[float, float, float],
        use_custom_gradient: bool = False
    ) -> Optional[QPixmap]:
        """
        Load thumbnail (from cache or async)

        Args:
            animation_uuid: Animation UUID
            thumbnail_path: Path to thumbnail image
            gradient_top: Top gradient color (R, G, B) 0-1
            gradient_bottom: Bottom gradient color (R, G, B) 0-1
            use_custom_gradient: Whether using custom gradient

        Returns:
            QPixmap if in cache, None if loading in background
        """
        self.total_requests += 1

        # Generate cache key
        cache_key = self._generate_cache_key(
            animation_uuid,
            gradient_top,
            gradient_bottom
        )

        # Check cache first
        pixmap = QPixmapCache.find(cache_key)
        if pixmap:
            self.cache_hits += 1
            self._log_performance()
            return pixmap

        self.cache_misses += 1

        # T167: Check if already loading (deduplication via pending_requests)
        # This prevents duplicate background tasks for the same thumbnail
        if cache_key in self.pending_requests:
            # Already loading, don't start duplicate request
            return None

        # T167: Not in cache - start background load and track in pending set
        self.pending_requests.add(cache_key)

        task = ThumbnailLoadTask(
            animation_uuid,
            thumbnail_path,
            gradient_top,
            gradient_bottom,
            cache_key,
            canvas_size=Config.THUMBNAIL_SIZE
        )

        # Connect signals
        task.signals.load_complete.connect(self._on_load_complete)
        task.signals.load_failed.connect(self._on_load_failed)

        # Start task
        self.thread_pool.start(task)

        return None

    def _on_load_complete(self, uuid: str, cache_key: str, image: QImage, elapsed_ms: float):
        """Handle successful thumbnail load"""

        # Remove from pending
        self.pending_requests.discard(cache_key)

        # Track load time
        self.load_times.append(elapsed_ms)

        # Convert to pixmap
        pixmap = QPixmap.fromImage(image)

        # Store in cache
        QPixmapCache.insert(cache_key, pixmap)

        # Emit signal
        self.thumbnail_loaded.emit(uuid, pixmap)

        self._log_performance()

    def _on_load_failed(self, uuid: str, error_message: str):
        """Handle failed thumbnail load"""

        # Remove from pending (use cache key pattern)
        # Since we don't have cache_key here, remove by UUID pattern
        to_remove = [key for key in self.pending_requests if uuid in key]
        for key in to_remove:
            self.pending_requests.discard(key)

        # Emit failure signal
        self.thumbnail_failed.emit(uuid, error_message)

    def _generate_cache_key(
        self,
        animation_uuid: str,
        gradient_top: Tuple[float, float, float],
        gradient_bottom: Tuple[float, float, float]
    ) -> str:
        """
        Generate cache key for thumbnail.

        Uses hash to avoid collision from float string representation.

        Args:
            animation_uuid: Animation UUID
            gradient_top: Top gradient color
            gradient_bottom: Bottom gradient color

        Returns:
            Unique cache key string
        """
        import hashlib

        # Use hash to avoid collision from float precision issues
        # Format floats to fixed precision to ensure consistent hashing
        top_str = f"{gradient_top[0]:.4f},{gradient_top[1]:.4f},{gradient_top[2]:.4f}"
        bottom_str = f"{gradient_bottom[0]:.4f},{gradient_bottom[1]:.4f},{gradient_bottom[2]:.4f}"
        combined = f"{animation_uuid}:{top_str}:{bottom_str}"

        # Use short hash for cache key
        key_hash = hashlib.md5(combined.encode()).hexdigest()[:12]
        return f"thumb_{animation_uuid[:8]}_{key_hash}"

    def _log_performance(self):
        """Log performance statistics periodically"""
        pass  # Performance logging disabled

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics (Maya-inspired)

        Returns:
            Dict with cache statistics
        """
        hit_rate = (self.cache_hits / self.total_requests * 100) if self.total_requests > 0 else 0
        avg_load_time = (sum(self.load_times) / len(self.load_times)) if self.load_times else 0

        return {
            'total_requests': self.total_requests,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': hit_rate,
            'avg_load_time_ms': avg_load_time,
            'pending_count': len(self.pending_requests),
            'thread_count': self.thread_pool.maxThreadCount(),
        }

    def clear_cache(self):
        """Clear QPixmapCache"""
        QPixmapCache.clear()

    def invalidate_shot(self, shot_uuid: str):
        """
        Invalidate cached thumbnails for a specific shot.

        Since QPixmapCache doesn't support wildcard removal, this clears
        the entire cache. The thumbnails will be reloaded on demand.

        Args:
            shot_uuid: UUID of the shot to invalidate
        """
        # QPixmapCache.remove() requires exact key, but we don't track
        # which gradient combinations were used. Clear all for safety.
        QPixmapCache.clear()

        # Also remove from pending requests if any
        keys_to_remove = [k for k in self.pending_requests if k.startswith(shot_uuid)]
        for key in keys_to_remove:
            self.pending_requests.discard(key)

    def reset_stats(self):
        """Reset performance statistics"""
        self.load_times.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_requests = 0


# Singleton instance with thread safety
_thumbnail_loader_instance: Optional[ThumbnailLoader] = None
_thumbnail_loader_lock = threading.Lock()


def get_thumbnail_loader() -> ThumbnailLoader:
    """
    Get global ThumbnailLoader singleton (thread-safe).

    Returns:
        Global ThumbnailLoader instance
    """
    global _thumbnail_loader_instance
    if _thumbnail_loader_instance is None:
        with _thumbnail_loader_lock:
            # Double-check after acquiring lock
            if _thumbnail_loader_instance is None:
                _thumbnail_loader_instance = ThumbnailLoader()
    return _thumbnail_loader_instance


class VideoThumbnailLoadSignals(QObject):
    """Signals for VideoThumbnailLoadTask"""
    load_complete = pyqtSignal(str, str, QImage, float)  # shot_id, cache_key, image, elapsed_ms
    load_failed = pyqtSignal(str, str)  # shot_id, error_message


class VideoThumbnailLoadTask(QRunnable):
    """
    Background task for extracting video thumbnail from playblast.

    Implements T087: Adapt ThumbnailLoader for video frame extraction.

    Features:
    - Extracts frame from MP4 playblast using OpenCV
    - Supports first frame or middle frame extraction
    - Scales to 16:9 thumbnail size
    - DPI scaling support

    Usage:
        task = VideoThumbnailLoadTask(shot_id, playblast_path, cache_key)
        threadpool.start(task)
    """

    def __init__(
        self,
        shot_id: str,
        playblast_path: Path,
        cache_key: str,
        frame_number: int = 0,
        size: Tuple[int, int] = None
    ):
        super().__init__()
        self.shot_id = shot_id
        self.playblast_path = playblast_path
        self.cache_key = cache_key
        self.frame_number = frame_number
        self.size = size or Config.MEDIA_ENGINE_THUMBNAIL_SIZE
        self.signals = VideoThumbnailLoadSignals()
        self.start_time = time.time()

    def run(self):
        """Execute video thumbnail extraction task."""
        try:
            import cv2

            # Open video
            cap = cv2.VideoCapture(str(self.playblast_path))
            if not cap.isOpened():
                self.signals.load_failed.emit(
                    self.shot_id,
                    f"Failed to open video: {self.playblast_path}"
                )
                return

            # Get total frames for middle frame extraction
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Use middle frame if frame_number is -1
            target_frame = self.frame_number
            if target_frame < 0 or target_frame >= total_frames:
                target_frame = total_frames // 2 if total_frames > 0 else 0

            # Seek to target frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            # Read frame
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                self.signals.load_failed.emit(
                    self.shot_id,
                    f"Failed to read frame {target_frame} from: {self.playblast_path}"
                )
                return

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Scale to target size (16:9)
            h, w = frame_rgb.shape[:2]
            target_w, target_h = self.size

            # Resize maintaining aspect ratio
            frame_resized = cv2.resize(
                frame_rgb,
                (target_w, target_h),
                interpolation=cv2.INTER_AREA
            )

            # Convert to QImage
            h_new, w_new, ch = frame_resized.shape
            bytes_per_line = ch * w_new
            qimage = QImage(
                frame_resized.data.tobytes(),
                w_new, h_new,
                bytes_per_line,
                QImage.Format.Format_RGB888
            ).copy()  # Copy to own the data

            # Note: Do NOT apply DPI scaling here - the delegate will scale
            # the pixmap to fill the card rect, and DPI ratio would cause
            # the logical size to be smaller than pixel size, creating gaps.

            # Calculate elapsed time
            elapsed_ms = (time.time() - self.start_time) * 1000

            # Emit success
            self.signals.load_complete.emit(
                self.shot_id,
                self.cache_key,
                qimage,
                elapsed_ms
            )

        except ImportError:
            self.signals.load_failed.emit(
                self.shot_id,
                "OpenCV (cv2) not available for video thumbnail extraction"
            )
        except Exception as e:
            self.signals.load_failed.emit(
                self.shot_id,
                f"Video thumbnail extraction error: {e}"
            )


class ShotThumbnailLoader(QObject):
    """
    Manages async thumbnail loading for shots from playblast videos.

    Implements T087-T088:
    - T087: Adapt ThumbnailLoader for video frame extraction
    - T088: Integrate playblast discovery with thumbnail loading

    Features:
    - Extracts thumbnails from playblast MP4 files
    - Integrates with PlayblastIndexer to find latest playblast
    - Background loading with worker threads
    - Load deduplication
    - QPixmapCache integration

    Usage:
        loader = ShotThumbnailLoader()
        loader.thumbnail_loaded.connect(on_thumbnail_ready)
        pixmap = loader.load_shot_thumbnail(shot_id, shot_folder)
    """

    # Signals
    thumbnail_loaded = pyqtSignal(str, QPixmap)  # shot_id, pixmap
    thumbnail_failed = pyqtSignal(str, str)  # shot_id, error_message

    def __init__(self, parent=None):
        super().__init__(parent)

        # Thread pool
        self.thread_pool = QThreadPool.globalInstance()

        # Playblast indexer for discovering playblasts
        self._playblast_indexer = None

        # Load deduplication
        self.pending_requests: Set[str] = set()

        # Performance stats
        self.load_times: list[float] = []
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.total_requests: int = 0

    def _get_playblast_indexer(self):
        """Lazy-load playblast indexer."""
        if self._playblast_indexer is None:
            from ..core.playblast_indexer import PlayblastIndexer
            self._playblast_indexer = PlayblastIndexer(
                playblast_folder_name=Config.PLAYBLAST_FOLDER_NAME
            )
        return self._playblast_indexer

    def load_shot_thumbnail(
        self,
        shot_id: str,
        shot_folder: Path,
        playblast_path: Optional[Path] = None,
        use_middle_frame: bool = True
    ) -> Optional[QPixmap]:
        """
        Load thumbnail for a shot from its playblast.

        Implements T088: Integrate playblast discovery with thumbnail loading.

        Args:
            shot_id: Unique shot identifier
            shot_folder: Path to shot folder
            playblast_path: Direct path to playblast (optional, will auto-discover if None)
            use_middle_frame: If True, extract middle frame instead of first frame

        Returns:
            QPixmap if in cache, None if loading in background
        """
        self.total_requests += 1

        # Generate cache key
        cache_key = f"shot_thumb_{shot_id}"

        # Check cache first
        pixmap = QPixmapCache.find(cache_key)
        if pixmap:
            self.cache_hits += 1
            return pixmap

        self.cache_misses += 1

        # Check if already loading
        if cache_key in self.pending_requests:
            return None

        # Determine playblast path
        if playblast_path is None or not playblast_path.exists():
            # Use PlayblastIndexer to find latest playblast
            indexer = self._get_playblast_indexer()
            try:
                latest = indexer.get_latest_playblast(shot_folder)
                if latest:
                    playblast_path = latest.file_path
            except FileNotFoundError:
                # Shot folder doesn't exist
                self.thumbnail_failed.emit(shot_id, "Shot folder not found")
                return None

        if playblast_path is None or not playblast_path.exists():
            # No playblast available
            self.thumbnail_failed.emit(shot_id, "No playblast found")
            return None

        # Start background load
        self.pending_requests.add(cache_key)

        frame_number = -1 if use_middle_frame else 0  # -1 = middle frame

        task = VideoThumbnailLoadTask(
            shot_id=shot_id,
            playblast_path=playblast_path,
            cache_key=cache_key,
            frame_number=frame_number,
            size=Config.MEDIA_ENGINE_THUMBNAIL_SIZE
        )

        task.signals.load_complete.connect(self._on_load_complete)
        task.signals.load_failed.connect(self._on_load_failed)

        self.thread_pool.start(task)

        return None

    def load_thumbnail_from_playblast(
        self,
        shot_id: str,
        playblast_path: Path,
        frame_number: int = 0
    ) -> Optional[QPixmap]:
        """
        Load thumbnail directly from a specific playblast/lookdev path.

        Args:
            shot_id: Unique shot identifier
            playblast_path: Path to playblast or lookdev MP4 file
            frame_number: Frame to extract (0 = first, -1 = middle)

        Returns:
            QPixmap if in cache, None if loading in background
        """
        # Include path name in cache key to differentiate playblast vs lookdev
        path_hash = hash(str(playblast_path))
        cache_key = f"shot_thumb_{shot_id}_{path_hash}_{frame_number}"

        # Check cache
        pixmap = QPixmapCache.find(cache_key)
        if pixmap:
            return pixmap

        # Check if loading
        if cache_key in self.pending_requests:
            return None

        if not playblast_path.exists():
            self.thumbnail_failed.emit(shot_id, "Playblast file not found")
            return None

        # Start background load
        self.pending_requests.add(cache_key)

        task = VideoThumbnailLoadTask(
            shot_id=shot_id,
            playblast_path=playblast_path,
            cache_key=cache_key,
            frame_number=frame_number,
            size=Config.MEDIA_ENGINE_THUMBNAIL_SIZE
        )

        task.signals.load_complete.connect(self._on_load_complete)
        task.signals.load_failed.connect(self._on_load_failed)

        self.thread_pool.start(task)

        return None

    def _on_load_complete(self, shot_id: str, cache_key: str, image: QImage, elapsed_ms: float):
        """Handle successful thumbnail load."""
        self.pending_requests.discard(cache_key)
        self.load_times.append(elapsed_ms)

        pixmap = QPixmap.fromImage(image)
        QPixmapCache.insert(cache_key, pixmap)

        self.thumbnail_loaded.emit(shot_id, pixmap)

    def _on_load_failed(self, shot_id: str, error_message: str):
        """Handle failed thumbnail load."""
        # Remove from pending
        to_remove = [k for k in self.pending_requests if shot_id in k]
        for key in to_remove:
            self.pending_requests.discard(key)

        self.thumbnail_failed.emit(shot_id, error_message)

    def invalidate_shot(self, shot_id: str):
        """Invalidate cached thumbnail for a shot."""
        # Since QPixmapCache doesn't support pattern removal,
        # we need to try specific keys
        keys_to_try = [
            f"shot_thumb_{shot_id}",
            f"shot_thumb_{shot_id}_0",
            f"shot_thumb_{shot_id}_-1",
        ]
        for key in keys_to_try:
            QPixmapCache.remove(key)

        # Remove from pending
        to_remove = [k for k in self.pending_requests if shot_id in k]
        for key in to_remove:
            self.pending_requests.discard(key)

    def clear_cache(self):
        """Clear all cached thumbnails."""
        QPixmapCache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        hit_rate = (self.cache_hits / self.total_requests * 100) if self.total_requests > 0 else 0
        avg_load_time = (sum(self.load_times) / len(self.load_times)) if self.load_times else 0

        return {
            'total_requests': self.total_requests,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': hit_rate,
            'avg_load_time_ms': avg_load_time,
            'pending_count': len(self.pending_requests),
        }


# Singleton instance for shot thumbnails with thread safety
_shot_thumbnail_loader_instance: Optional[ShotThumbnailLoader] = None
_shot_thumbnail_loader_lock = threading.Lock()


def get_shot_thumbnail_loader() -> ShotThumbnailLoader:
    """
    Get global ShotThumbnailLoader singleton (thread-safe).

    Returns:
        Global ShotThumbnailLoader instance
    """
    global _shot_thumbnail_loader_instance
    if _shot_thumbnail_loader_instance is None:
        with _shot_thumbnail_loader_lock:
            # Double-check after acquiring lock
            if _shot_thumbnail_loader_instance is None:
                _shot_thumbnail_loader_instance = ShotThumbnailLoader()
    return _shot_thumbnail_loader_instance


__all__ = [
    'ThumbnailLoader',
    'ThumbnailLoadTask',
    'get_thumbnail_loader',
    'ShotThumbnailLoader',
    'VideoThumbnailLoadTask',
    'get_shot_thumbnail_loader',
]
