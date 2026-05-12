"""
DrawoverStorage - File storage management for frame annotations

Handles saving/loading drawover JSON files and PNG cache generation.
"""

import json
import logging
import threading
import uuid as uuid_lib
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime, timezone
from collections import OrderedDict

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool
from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QPainterPath, QFont, QBrush, QPolygonF
from PyQt6.QtCore import Qt, QPointF, QRectF, QLineF

from ..config import Config
from ..utils.file_utils import atomic_write, file_lock

logger = logging.getLogger(__name__)


class DrawoverStorage:
    """
    Manages drawover file storage on disk.

    File structure:
        storage/.meta/drawovers/{uuid}/{version}/
        ├── f0125.json       # Frame 125 vector data
        ├── f0125.png        # Frame 125 PNG cache
        └── manifest.json    # Index of all drawovers
    """

    JSON_VERSION = "1.0"

    def __init__(self, base_path: Optional[Path] = None):
        if base_path is None:
            base_path = Path(Config.get_database_folder())
        self._base = base_path / 'drawovers'
        self._base.mkdir(parents=True, exist_ok=True)

    def get_drawover_dir(self, animation_uuid: str, version: str) -> Path:
        """Get directory for a version's drawovers."""
        return self._base / animation_uuid / version

    def get_drawover_path(self, animation_uuid: str, version: str, frame: int) -> Path:
        """Get path for a frame's drawover JSON."""
        return self.get_drawover_dir(animation_uuid, version) / f'f{frame:04d}.json'

    def get_png_cache_path(self, animation_uuid: str, version: str, frame: int) -> Path:
        """Get path for a frame's PNG cache."""
        return self.get_drawover_dir(animation_uuid, version) / f'f{frame:04d}.png'

    def get_manifest_path(self, animation_uuid: str, version: str) -> Path:
        """Get path for manifest file."""
        return self.get_drawover_dir(animation_uuid, version) / 'manifest.json'

    # ==================== Save/Load ====================

    def save_drawover(
        self,
        animation_uuid: str,
        version: str,
        frame: int,
        strokes: List[Dict],
        author: str = '',
        canvas_size: Tuple[int, int] = (1920, 1080)
    ) -> bool:
        """
        Save drawover data for a frame.

        Uses atomic writes with file locking to prevent data corruption
        from concurrent access.

        Args:
            animation_uuid: Animation UUID
            version: Version label (e.g., 'v001')
            frame: Frame number
            strokes: List of stroke dictionaries
            author: Current user (for new strokes)
            canvas_size: Video dimensions

        Returns:
            True if saved successfully
        """
        try:
            path = self.get_drawover_path(animation_uuid, version, frame)
            path.parent.mkdir(parents=True, exist_ok=True)

            # Use file lock to prevent concurrent modification
            with file_lock(path):
                # Load existing data or create new
                existing = self.load_drawover(animation_uuid, version, frame)
                now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'

                if existing:
                    data = existing
                    data['modified_at'] = now
                    data['strokes'] = strokes
                else:
                    data = {
                        'version': self.JSON_VERSION,
                        'frame': frame,
                        'canvas_size': list(canvas_size),
                        'created_at': now,
                        'modified_at': now,
                        'author': author,
                        'strokes': strokes,
                        'deleted_strokes': []
                    }

                # Use atomic write to prevent partial writes
                with atomic_write(path) as tmp_path:
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)

            # Invalidate PNG cache
            png_path = self.get_png_cache_path(animation_uuid, version, frame)
            if png_path.exists():
                try:
                    png_path.unlink()
                except Exception:
                    pass  # Non-critical

            # Update manifest
            self._update_manifest(animation_uuid, version)

            return True

        except Exception as e:
            logger.error(f"Error saving drawover: {e}")
            return False

    def load_drawover(self, animation_uuid: str, version: str, frame: int) -> Optional[Dict]:
        """Load drawover data for a frame."""
        path = self.get_drawover_path(animation_uuid, version, frame)
        if not path.exists():
            return None

        try:
            with file_lock(path, timeout=2.0):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading drawover: {e}")
            return None

    def delete_drawover(self, animation_uuid: str, version: str, frame: int) -> bool:
        """Delete a frame's drawover files (hard delete)."""
        try:
            json_path = self.get_drawover_path(animation_uuid, version, frame)
            png_path = self.get_png_cache_path(animation_uuid, version, frame)

            if json_path.exists():
                json_path.unlink()
            if png_path.exists():
                png_path.unlink()

            self._update_manifest(animation_uuid, version)
            return True

        except Exception as e:
            logger.error(f"Error deleting drawover: {e}")
            return False

    def delete_all_for_version(self, animation_uuid: str, version: str) -> bool:
        """Delete ALL drawover files for a version."""
        try:
            drawover_dir = self.get_drawover_dir(animation_uuid, version)
            if not drawover_dir.exists():
                return True  # Nothing to delete

            import shutil
            shutil.rmtree(drawover_dir)
            return True

        except Exception as e:
            logger.error(f"Error deleting all drawovers for version: {e}")
            return False

    def has_drawover(self, animation_uuid: str, version: str, frame: int) -> bool:
        """Check if a frame has drawover data with actual strokes."""
        path = self.get_drawover_path(animation_uuid, version, frame)
        if not path.exists():
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return bool(data.get('strokes'))
        except (json.JSONDecodeError, IOError):
            return False

    def list_frames_with_drawovers(self, animation_uuid: str, version: str) -> List[int]:
        """Get list of frames that have drawovers with actual strokes."""
        drawover_dir = self.get_drawover_dir(animation_uuid, version)
        if not drawover_dir.exists():
            return []

        frames = []
        for path in drawover_dir.glob('f*.json'):
            try:
                # Extract frame number from filename (f0125.json -> 125)
                frame_str = path.stem[1:]  # Remove 'f' prefix
                frame_num = int(frame_str)

                # Check if file actually has strokes (not just cleared/empty)
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get('strokes'):  # Only include if has strokes
                        frames.append(frame_num)
            except (ValueError, json.JSONDecodeError, IOError):
                continue

        return sorted(frames)

    # ==================== Stroke Management ====================

    def add_stroke(
        self,
        animation_uuid: str,
        version: str,
        frame: int,
        stroke: Dict,
        author: str = '',
        canvas_size: Tuple[int, int] = (1920, 1080)
    ) -> Optional[str]:
        """
        Add a single stroke to a frame's drawover.

        Returns:
            Stroke ID if successful, None otherwise
        """
        # Generate stroke ID if not present
        if 'id' not in stroke:
            stroke['id'] = f"stroke_{uuid_lib.uuid4().hex[:8]}"

        stroke['created_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
        stroke['author'] = author

        # Hold the file lock across load+save so concurrent add_stroke calls on
        # the same frame can't lose strokes via the load-modify-write race.
        path = self.get_drawover_path(animation_uuid, version, frame)
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path):
            existing = self.load_drawover(animation_uuid, version, frame)
            if existing:
                existing['strokes'].append(stroke)
                strokes = existing['strokes']
            else:
                strokes = [stroke]

            if self.save_drawover(animation_uuid, version, frame, strokes, author, canvas_size):
                return stroke['id']
        return None

    def remove_stroke(
        self,
        animation_uuid: str,
        version: str,
        frame: int,
        stroke_id: str,
        soft_delete: bool = True,
        deleted_by: str = ''
    ) -> bool:
        """
        Remove a stroke from a frame's drawover.

        Args:
            soft_delete: If True, move to deleted_strokes array (Studio Mode)
                        If False, permanently remove (Solo Mode)
        """
        data = self.load_drawover(animation_uuid, version, frame)
        if not data:
            return False

        # Find stroke
        stroke_to_remove = None
        for i, stroke in enumerate(data['strokes']):
            if stroke.get('id') == stroke_id:
                stroke_to_remove = data['strokes'].pop(i)
                break

        if not stroke_to_remove:
            return False

        if soft_delete:
            # Move to deleted_strokes
            if 'deleted_strokes' not in data:
                data['deleted_strokes'] = []

            deleted_entry = {
                'id': stroke_id,
                'deleted_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z',
                'deleted_by': deleted_by,
                'original_data': stroke_to_remove
            }
            data['deleted_strokes'].append(deleted_entry)

        # Save updated data with atomic write
        path = self.get_drawover_path(animation_uuid, version, frame)
        try:
            with file_lock(path):
                with atomic_write(path) as tmp_path:
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)

            # Invalidate PNG cache
            png_path = self.get_png_cache_path(animation_uuid, version, frame)
            if png_path.exists():
                try:
                    png_path.unlink()
                except Exception:
                    pass

            self._update_manifest(animation_uuid, version)
            return True

        except Exception as e:
            logger.error(f"Error removing stroke: {e}")
            return False

    def restore_stroke(
        self,
        animation_uuid: str,
        version: str,
        frame: int,
        stroke_id: str,
        restored_by: str = ''
    ) -> bool:
        """Restore a soft-deleted stroke."""
        data = self.load_drawover(animation_uuid, version, frame)
        if not data or 'deleted_strokes' not in data:
            return False

        # Find deleted stroke
        for i, deleted in enumerate(data['deleted_strokes']):
            if deleted.get('id') == stroke_id:
                # Restore original data
                original = deleted['original_data']
                data['strokes'].append(original)
                data['deleted_strokes'].pop(i)

                # Save with atomic write
                path = self.get_drawover_path(animation_uuid, version, frame)
                try:
                    with file_lock(path):
                        with atomic_write(path) as tmp_path:
                            with open(tmp_path, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2)
                except Exception:
                    logger.warning(
                        "Failed to restore stroke %s on %s frame %d",
                        stroke_id, version, frame, exc_info=True,
                    )
                    return False

                # Keep manifest in sync — the stroke count just changed.
                self._update_manifest(animation_uuid, version)

                # Invalidate cache
                png_path = self.get_png_cache_path(animation_uuid, version, frame)
                if png_path.exists():
                    try:
                        png_path.unlink()
                    except Exception:
                        logger.warning(
                            "Failed to remove PNG cache for %s frame %d after restore_stroke",
                            version, frame, exc_info=True,
                        )

                return True

        return False

    def clear_frame(
        self,
        animation_uuid: str,
        version: str,
        frame: int,
        soft_delete: bool = True,
        deleted_by: str = ''
    ) -> bool:
        """Clear all strokes on a frame."""
        data = self.load_drawover(animation_uuid, version, frame)
        if not data:
            return True  # Nothing to clear

        if soft_delete:
            # Move all to deleted
            if 'deleted_strokes' not in data:
                data['deleted_strokes'] = []

            now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
            for stroke in data['strokes']:
                deleted_entry = {
                    'id': stroke.get('id', ''),
                    'deleted_at': now,
                    'deleted_by': deleted_by,
                    'original_data': stroke
                }
                data['deleted_strokes'].append(deleted_entry)

        data['strokes'] = []

        # Save with atomic write
        path = self.get_drawover_path(animation_uuid, version, frame)
        try:
            with file_lock(path):
                with atomic_write(path) as tmp_path:
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)

            # Invalidate cache
            png_path = self.get_png_cache_path(animation_uuid, version, frame)
            if png_path.exists():
                try:
                    png_path.unlink()
                except Exception:
                    pass

            self._update_manifest(animation_uuid, version)
            return True

        except Exception as e:
            logger.error(f"Error clearing frame: {e}")
            return False

    # ==================== PNG Rendering ====================

    def render_to_png(
        self,
        animation_uuid: str,
        version: str,
        frame: int,
        size: Tuple[int, int]
    ) -> Optional[Path]:
        """
        Render drawover to PNG, using cache if valid.

        Cache is considered valid if:
        1. PNG file exists
        2. PNG mtime is greater than JSON mtime (with 1 second tolerance for filesystem precision)

        Returns:
            Path to PNG file, or None if no drawover exists
        """
        json_path = self.get_drawover_path(animation_uuid, version, frame)
        png_path = self.get_png_cache_path(animation_uuid, version, frame)

        if not json_path.exists():
            return None

        # Check if cache is valid with robust timestamp comparison
        try:
            if png_path.exists():
                json_mtime = json_path.stat().st_mtime
                png_mtime = png_path.stat().st_mtime
                # Add 1 second tolerance for filesystem timestamp precision issues
                if png_mtime >= json_mtime - 1.0:
                    return png_path
        except OSError as e:
            logger.warning(f"Error checking cache validity: {e}")
            # Continue to re-render

        # Load and render
        data = self.load_drawover(animation_uuid, version, frame)
        if not data:
            return None

        try:
            self._render_strokes_to_png(data, png_path, size)
            return png_path
        except Exception as e:
            logger.error(f"Error rendering PNG: {e}")
            return None

    def _render_strokes_to_png(
        self,
        data: Dict,
        output_path: Path,
        size: Tuple[int, int]
    ):
        """Render strokes to PNG file with transparency."""
        width, height = size
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))  # Transparent

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for stroke in data.get('strokes', []):
            self._render_stroke(painter, stroke, width, height)

        painter.end()
        image.save(str(output_path), 'PNG')

    def _render_stroke(
        self,
        painter: QPainter,
        stroke: Dict,
        output_width: int,
        output_height: int
    ):
        """Render a single stroke. Handles UV format (0-1 normalized coordinates)."""
        stroke_type = stroke.get('type', 'path')
        stroke_tool = stroke.get('tool', '')
        color = QColor(stroke.get('color', '#FF5722'))
        opacity = stroke.get('opacity', 1.0)
        color.setAlphaF(opacity)

        # Handle stroke width based on tool
        # PEN: fixed 2px, BRUSH: uses stored width, others (LINE, ARROW, RECT, CIRCLE): fixed 3px
        if stroke_tool == 'pen':
            stroke_width = 2  # Fixed width for pen tool
        elif stroke_tool == 'brush':
            stroke_width = stroke.get('width_px', None)
            if stroke_width is None:
                normalized_width = stroke.get('width', 0.01)
                stroke_width = normalized_width * min(output_width, output_height)
        elif stroke_tool in ('line', 'arrow', 'rect', 'circle', 'ellipse'):
            stroke_width = 3  # Fixed width for shape tools
        else:
            # Fallback for any other tools
            stroke_width = stroke.get('width_px', 3)

        pen = QPen(color, stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        # UV coordinates are 0-1 normalized, multiply by output dimensions
        if stroke_type == 'path':
            points = stroke.get('points', [])
            if len(points) >= 2:
                path = QPainterPath()
                path.moveTo(points[0][0] * output_width, points[0][1] * output_height)
                for point in points[1:]:
                    path.lineTo(point[0] * output_width, point[1] * output_height)
                painter.drawPath(path)

        elif stroke_type == 'line':
            start = stroke.get('start', [0, 0])
            end = stroke.get('end', [0, 0])
            painter.drawLine(
                QPointF(start[0] * output_width, start[1] * output_height),
                QPointF(end[0] * output_width, end[1] * output_height)
            )

        elif stroke_type == 'arrow':
            start = stroke.get('start', [0, 0])
            end = stroke.get('end', [0, 0])
            # Head size is stored as normalized, scale to pixels
            head_size_norm = stroke.get('head_size', 0.02)
            head_size = head_size_norm * min(output_width, output_height)

            # Draw line
            start_pt = QPointF(start[0] * output_width, start[1] * output_height)
            end_pt = QPointF(end[0] * output_width, end[1] * output_height)
            painter.drawLine(start_pt, end_pt)

            # Draw arrow head
            import math
            line = QLineF(start_pt, end_pt)
            angle = math.atan2(-line.dy(), line.dx())

            p1 = end_pt + QPointF(
                math.cos(angle + math.pi * 0.8) * head_size,
                -math.sin(angle + math.pi * 0.8) * head_size
            )
            p2 = end_pt + QPointF(
                math.cos(angle - math.pi * 0.8) * head_size,
                -math.sin(angle - math.pi * 0.8) * head_size
            )

            painter.drawLine(end_pt, p1)
            painter.drawLine(end_pt, p2)

        elif stroke_type == 'rect':
            bounds = stroke.get('bounds', [0, 0, 0.1, 0.1])
            fill = stroke.get('fill', False)
            rect = QRectF(
                bounds[0] * output_width,
                bounds[1] * output_height,
                bounds[2] * output_width,
                bounds[3] * output_height
            )
            if fill:
                painter.setBrush(QBrush(color))
                painter.drawRect(rect)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)  # No fill, outline only
                painter.drawRect(rect)

        elif stroke_type == 'ellipse':
            bounds = stroke.get('bounds', [0, 0, 0.1, 0.1])
            fill = stroke.get('fill', False)
            rect = QRectF(
                bounds[0] * output_width,
                bounds[1] * output_height,
                bounds[2] * output_width,
                bounds[3] * output_height
            )
            if fill:
                painter.setBrush(QBrush(color))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)  # No fill, outline only
            painter.drawEllipse(rect)

        elif stroke_type == 'text':
            position = stroke.get('position', [0, 0])
            text = stroke.get('text', '')
            # Font size stored as normalized, scale to output
            font_size_norm = stroke.get('font_size', 0.02)
            font_size = int(font_size_norm * min(output_width, output_height))
            font_size = max(font_size, 8)  # Minimum readable size
            bg_color = stroke.get('background', None)

            font = QFont('Arial', font_size)
            painter.setFont(font)

            pos = QPointF(position[0] * output_width, position[1] * output_height)

            if bg_color:
                bg = QColor(bg_color)
                bg.setAlphaF(stroke.get('opacity', 0.8))
                metrics = painter.fontMetrics()
                text_rect = metrics.boundingRect(text)
                text_rect.moveTopLeft(pos.toPoint())
                text_rect.adjust(-4, -2, 4, 2)
                painter.fillRect(text_rect, bg)

            painter.setPen(color)
            painter.drawText(pos, text)

        elif stroke_type == 'brush_path':
            # Pressure-sensitive brush stroke - render as circle stamps
            points_with_pressure = stroke.get('points_with_pressure', [])
            if not points_with_pressure:
                # Fallback to regular points if no pressure data
                points_with_pressure = [[p[0], p[1], 1.0] for p in stroke.get('points', [])]

            if len(points_with_pressure) >= 1:
                # Get base brush size
                base_size = stroke.get('width_px', None)
                if base_size is None:
                    normalized_width = stroke.get('width', 0.01)
                    base_size = normalized_width * min(output_width, output_height)

                base_opacity = stroke.get('opacity', 1.0)
                painter.setPen(QPen(Qt.PenStyle.NoPen))  # No outline for stamps

                for i, point_data in enumerate(points_with_pressure):
                    x = point_data[0] * output_width
                    y = point_data[1] * output_height
                    pressure = point_data[2] if len(point_data) > 2 else 1.0

                    # Diameter and opacity scale with pressure
                    diameter = max(1.0, base_size * pressure)
                    radius = diameter / 2.0

                    stamp_color = QColor(color)
                    pressure_opacity = base_opacity * pressure
                    stamp_color.setAlphaF(max(0.05, pressure_opacity))

                    painter.setBrush(QBrush(stamp_color))
                    painter.drawEllipse(QPointF(x, y), radius, radius)

                    # Interpolate circles between points for smooth strokes
                    if i < len(points_with_pressure) - 1:
                        next_point = points_with_pressure[i + 1]
                        x2 = next_point[0] * output_width
                        y2 = next_point[1] * output_height
                        pressure2 = next_point[2] if len(next_point) > 2 else 1.0

                        dx = x2 - x
                        dy = y2 - y
                        import math
                        distance = math.sqrt(dx * dx + dy * dy)

                        avg_pressure = (pressure + pressure2) / 2.0
                        avg_diameter = max(1.0, base_size * avg_pressure)
                        spacing = max(1.0, avg_diameter * 0.25)

                        if distance > spacing:
                            num_stamps = int(distance / spacing)
                            for j in range(1, num_stamps):
                                t = j / num_stamps
                                ix = x + dx * t
                                iy = y + dy * t
                                ip = pressure + (pressure2 - pressure) * t

                                i_diameter = max(1.0, base_size * ip)
                                i_radius = i_diameter / 2.0

                                i_color = QColor(color)
                                i_color.setAlphaF(max(0.05, base_opacity * ip))
                                painter.setBrush(QBrush(i_color))
                                painter.drawEllipse(QPointF(ix, iy), i_radius, i_radius)

        elif stroke_type == 'diamond':
            position = stroke.get('position', [0.5, 0.5])
            size_norm = stroke.get('size', 0.03)
            size = size_norm * min(output_width, output_height)
            fill = stroke.get('fill', True)
            cx = position[0] * output_width
            cy = position[1] * output_height
            half = size / 2

            # Diamond points centered on position
            polygon = QPolygonF([
                QPointF(cx, cy - half),
                QPointF(cx + half, cy),
                QPointF(cx, cy + half),
                QPointF(cx - half, cy)
            ])
            if fill:
                painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(polygon)

    # ==================== Manifest ====================

    def _update_manifest(self, animation_uuid: str, version: str):
        """Update manifest file for a version."""
        drawover_dir = self.get_drawover_dir(animation_uuid, version)
        if not drawover_dir.exists():
            return

        manifest_path = self.get_manifest_path(animation_uuid, version)

        frames = {}
        total_strokes = 0

        for json_path in drawover_dir.glob('f*.json'):
            try:
                frame_str = json_path.stem[1:]
                frame = int(frame_str)

                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                stroke_count = len(data.get('strokes', []))
                total_strokes += stroke_count

                frames[str(frame)] = {
                    'json': json_path.name,
                    'png': f'f{frame:04d}.png',
                    'modified_at': data.get('modified_at', ''),
                    'stroke_count': stroke_count
                }

            except Exception:
                logger.warning(
                    "Skipping unreadable drawover JSON in manifest scan: %s",
                    json_path, exc_info=True,
                )
                continue

        manifest = {
            'version': '1.0',
            'animation_uuid': animation_uuid,
            'version_label': version,
            'frames': frames,
            'total_frames': len(frames),
            'total_strokes': total_strokes
        }

        # Use atomic write for manifest
        try:
            with file_lock(manifest_path):
                with atomic_write(manifest_path) as tmp_path:
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(manifest, f, indent=2)
        except Exception as e:
            logger.error(f"Error updating manifest: {e}")

    def get_manifest(self, animation_uuid: str, version: str) -> Optional[Dict]:
        """Get manifest data for a version."""
        path = self.get_manifest_path(animation_uuid, version)
        if not path.exists():
            return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None


# ==================== Cache ====================

class DrawoverCache:
    """LRU cache for loaded drawover data. Thread-safe."""

    def __init__(self, max_size: int = 50):
        self._cache: OrderedDict[str, Dict] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()

    def _make_key(self, animation_uuid: str, version: str, frame: int) -> str:
        return f"{animation_uuid}:{version}:{frame}"

    def get(self, animation_uuid: str, version: str, frame: int) -> Optional[Dict]:
        key = self._make_key(animation_uuid, version, frame)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, animation_uuid: str, version: str, frame: int, data: Dict):
        key = self._make_key(animation_uuid, version, frame)
        with self._lock:
            self._cache[key] = data
            self._cache.move_to_end(key)

            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, animation_uuid: str, version: str, frame: int):
        key = self._make_key(animation_uuid, version, frame)
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_version(self, animation_uuid: str, version: str):
        """Invalidate all cached data for a version."""
        prefix = f"{animation_uuid}:{version}:"
        with self._lock:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
            for key in keys_to_remove:
                self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()


# ==================== Singleton (Thread-Safe) ====================

_storage_instance: Optional[DrawoverStorage] = None
_storage_lock = threading.Lock()
_cache_instance: Optional[DrawoverCache] = None
_cache_lock = threading.Lock()


def get_drawover_storage() -> DrawoverStorage:
    """Get singleton DrawoverStorage instance (thread-safe)."""
    global _storage_instance
    if _storage_instance is None:
        with _storage_lock:
            # Double-check after acquiring lock
            if _storage_instance is None:
                _storage_instance = DrawoverStorage()
    return _storage_instance


def get_drawover_cache() -> DrawoverCache:
    """Get singleton DrawoverCache instance (thread-safe)."""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            # Double-check after acquiring lock
            if _cache_instance is None:
                _cache_instance = DrawoverCache()
    return _cache_instance


__all__ = [
    'DrawoverStorage',
    'DrawoverCache',
    'get_drawover_storage',
    'get_drawover_cache'
]
