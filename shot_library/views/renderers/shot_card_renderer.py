"""
ShotCardRenderer - Drawing utilities for shot cards with 16:9 aspect ratio

Handles drawing of:
- Shot thumbnails (16:9 video-native aspect ratio)
- Shot status badges
- Editorial order info
- Playblast version indicators
"""

from PyQt6.QtCore import QRect, Qt, QRectF
from PyQt6.QtGui import QPainter, QPixmap, QColor, QFont, QPen, QBrush

from ...config import Config


class ShotCardRenderer:
    """Static methods for drawing shot cards with 16:9 aspect ratio"""

    # Aspect ratio constant
    ASPECT_RATIO = 16 / 9  # 1.777...

    @staticmethod
    def calculate_card_height(card_width: int, include_text: bool = True) -> int:
        """
        Calculate card height for 16:9 aspect ratio.

        Args:
            card_width: Card width in pixels
            include_text: Whether to include text area height

        Returns:
            Total card height in pixels
        """
        # Thumbnail area is 16:9
        thumbnail_height = int(card_width / ShotCardRenderer.ASPECT_RATIO)

        if include_text:
            # Add space for shot name and metadata
            text_height = 28  # Consistent with AnimationCardDelegate
            return thumbnail_height + text_height

        return thumbnail_height

    @staticmethod
    def get_thumbnail_rect(card_rect: QRect, card_width: int) -> QRect:
        """
        Get the thumbnail rectangle within a card (16:9 area).

        Args:
            card_rect: Full card rectangle
            card_width: Card width in pixels

        Returns:
            Rectangle for thumbnail area (16:9)
        """
        thumbnail_height = int(card_width / ShotCardRenderer.ASPECT_RATIO)
        return QRect(card_rect.x(), card_rect.y(), card_width, thumbnail_height)

    @staticmethod
    def draw_shot_thumbnail(
        painter: QPainter,
        rect: QRect,
        pixmap: QPixmap = None,
        placeholder_text: str = "No Playblast",
        theme_manager=None
    ) -> None:
        """
        Draw shot thumbnail maintaining 16:9 aspect ratio.

        Args:
            painter: QPainter instance
            rect: Rectangle for thumbnail (should be 16:9)
            pixmap: Thumbnail pixmap (optional)
            placeholder_text: Text to show if no thumbnail
            theme_manager: ThemeManager for colors
        """
        if pixmap and not pixmap.isNull():
            # Scale to fill entire rect (source is 16:9, rect is 16:9)
            scaled = pixmap.scaled(
                rect.width(),
                rect.height(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            # Draw at rect origin - no centering offsets needed
            painter.drawPixmap(rect.x(), rect.y(), scaled)
        else:
            # Draw placeholder
            ShotCardRenderer.draw_placeholder(painter, rect, placeholder_text, theme_manager)

    @staticmethod
    def draw_placeholder(
        painter: QPainter,
        rect: QRect,
        text: str = "No Playblast",
        theme_manager=None
    ) -> None:
        """
        Draw placeholder when no thumbnail/playblast exists.

        Args:
            painter: QPainter instance
            rect: Rectangle for placeholder
            text: Placeholder text
            theme_manager: ThemeManager for colors
        """
        # Get theme colors
        bg_color = QColor("#2a2a2a")  # Dark background
        text_color = QColor("#808080")  # Gray text

        if theme_manager:
            theme = theme_manager.get_current_theme()
            if theme:
                bg_color = QColor(theme.palette.background_secondary)
                text_color = QColor(theme.palette.text_secondary)

        # Draw background
        painter.fillRect(rect, bg_color)

        # Draw text
        painter.setPen(text_color)
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def draw_shot_status_badge(
        painter: QPainter,
        rect: QRect,
        status: str
    ) -> None:
        """
        Draw shot status badge (WIP, Review, Approved, Blocked).

        Args:
            painter: QPainter instance
            rect: Badge rectangle
            status: Shot status string
        """
        # Status colors (must match Pipeline Control)
        status_colors = {
            Config.SHOT_STATUS_WIP: "#FF9800",        # Orange
            Config.SHOT_STATUS_IN_REVIEW: "#2196F3",  # Blue
            Config.SHOT_STATUS_APPROVED: "#4CAF50",   # Green
            Config.SHOT_STATUS_FINAL: "#9C27B0",      # Purple
            Config.SHOT_STATUS_BLOCKED: "#F44336",    # Red
        }

        color = status_colors.get(status, "#9E9E9E")  # Default gray

        # Draw badge background
        painter.fillRect(rect, QColor(color))

        # Draw text
        painter.setPen(QColor("#FFFFFF"))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, status)

    @staticmethod
    def draw_editorial_order_badge(
        painter: QPainter,
        rect: QRect,
        episode: int = None,
        sequence: int = None,
        scene: int = None,
        shot: int = None,
        condensed: bool = True
    ) -> None:
        """
        Draw editorial order badge (EP/SQ/SC/SH numbers).

        Args:
            painter: QPainter instance
            rect: Badge rectangle
            episode: Episode number
            sequence: Sequence number
            scene: Scene number
            shot: Shot number
            condensed: If True, show abbreviated format
        """
        # Build label
        parts = []
        if episode is not None and episode > 0:
            parts.append(f"EP{episode:02d}")
        if sequence is not None and sequence > 0:
            parts.append(f"SQ{sequence:03d}")
        if scene is not None and scene > 0:
            parts.append(f"SC{scene:02d}")
        if shot is not None and shot > 0:
            parts.append(f"SH{shot:03d}")

        if not parts:
            return  # Nothing to draw

        if condensed and len(parts) > 2:
            # Show only sequence and shot for brevity
            label = " ".join(parts[-2:])
        else:
            label = " ".join(parts)

        # Draw semi-transparent background
        painter.fillRect(rect, QColor(0, 0, 0, 180))

        # Draw text
        painter.setPen(QColor("#FFFFFF"))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    @staticmethod
    def draw_playblast_version_badge(
        painter: QPainter,
        rect: QRect,
        version: int,
        is_latest: bool = True
    ) -> None:
        """
        Draw playblast version badge.

        Args:
            painter: QPainter instance
            rect: Badge rectangle
            version: Version number
            is_latest: Whether this is the latest version
        """
        # Background color based on latest status
        if is_latest:
            bg_color = QColor("#4CAF50")  # Green for latest
        else:
            bg_color = QColor(0, 0, 0, 180)  # Semi-transparent for older

        painter.fillRect(rect, bg_color)

        # Draw text
        painter.setPen(QColor("#FFFFFF"))
        font = QFont()
        font.setPointSize(8)
        font.setBold(is_latest)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"v{version:03d}")

    @staticmethod
    def draw_parse_warning_indicator(
        painter: QPainter,
        x: int,
        y: int,
        size: int = 16
    ) -> None:
        """
        Draw warning indicator for unparseable shot names.

        T172: Display parse warnings as badges on shot cards.

        Args:
            painter: QPainter instance
            x: X position
            y: Y position
            size: Indicator size
        """
        # Draw warning triangle
        rect = QRect(x, y, size, size)

        # Yellow background
        painter.setBrush(QBrush(QColor("#FFC107")))
        painter.setPen(Qt.PenStyle.NoPen)

        # Draw triangle
        from PyQt6.QtGui import QPolygon
        from PyQt6.QtCore import QPoint

        points = QPolygon([
            QPoint(x + size // 2, y + 2),
            QPoint(x + size - 2, y + size - 2),
            QPoint(x + 2, y + size - 2)
        ])
        painter.drawPolygon(points)

        # Draw exclamation mark
        painter.setPen(QColor("#000000"))
        font = QFont()
        font.setPointSize(int(size * 0.6))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "!")

    @staticmethod
    def draw_error_indicator(
        painter: QPainter,
        rect: QRect,
        error_text: str = "Error",
        theme_manager=None
    ) -> None:
        """
        Draw error indicator for corrupted/unreadable video files.

        T170: Add error state display for corrupted video files on cards.

        Args:
            painter: QPainter instance
            rect: Rectangle for the error indicator
            error_text: Error message to display
            theme_manager: ThemeManager for colors
        """
        # Draw red-tinted background
        error_bg = QColor("#3a1a1a")  # Dark red
        painter.fillRect(rect, error_bg)

        # Draw error icon (X in circle)
        icon_size = min(rect.width(), rect.height()) // 3
        icon_x = rect.x() + (rect.width() - icon_size) // 2
        icon_y = rect.y() + (rect.height() - icon_size) // 2 - 10

        # Circle
        painter.setPen(QPen(QColor("#F44336"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        icon_rect = QRect(icon_x, icon_y, icon_size, icon_size)
        painter.drawEllipse(icon_rect)

        # X inside circle
        margin = icon_size // 4
        painter.drawLine(
            icon_x + margin, icon_y + margin,
            icon_x + icon_size - margin, icon_y + icon_size - margin
        )
        painter.drawLine(
            icon_x + icon_size - margin, icon_y + margin,
            icon_x + margin, icon_y + icon_size - margin
        )

        # Draw error text below
        text_rect = QRect(
            rect.x(), icon_y + icon_size + 5,
            rect.width(), 20
        )
        painter.setPen(QColor("#F44336"))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, error_text)

    @staticmethod
    def draw_incomplete_shot_indicator(
        painter: QPainter,
        x: int,
        y: int,
        size: int = 16
    ) -> None:
        """
        Draw indicator for incomplete shot (no .blend file).

        T173: Show incomplete shot indicator.

        Args:
            painter: QPainter instance
            x: X position
            y: Y position
            size: Indicator size
        """
        rect = QRect(x, y, size, size)

        # Gray background circle
        painter.setBrush(QBrush(QColor("#616161")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)

        # Question mark
        painter.setPen(QColor("#FFFFFF"))
        font = QFont()
        font.setPointSize(int(size * 0.7))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")

    @staticmethod
    def draw_shot_name(
        painter: QPainter,
        rect: QRect,
        name: str,
        palette,
        is_selected: bool = False
    ) -> None:
        """
        Draw shot name text below thumbnail.

        Args:
            painter: QPainter instance
            rect: Text rectangle
            name: Shot name
            palette: Theme palette for colors
            is_selected: Whether the card is selected
        """
        # Text color based on selection
        if is_selected:
            text_color = QColor("#FFFFFF")
        else:
            text_color = QColor(palette.text_primary)

        painter.setPen(text_color)

        # Font
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)

        # Draw centered, elided if needed
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(name, Qt.TextElideMode.ElideRight, rect.width() - 8)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, elided)

    @staticmethod
    def draw_assignment_badge(
        painter: QPainter,
        rect: QRect,
        assignee_name: str = None,
        priority: str = None,
        is_overdue: bool = False
    ) -> None:
        """
        Draw assignment badge showing assignee initials and priority indicator.

        Args:
            painter: QPainter instance
            rect: Badge rectangle (bottom-right corner of thumbnail)
            assignee_name: Display name of assignee (for initials)
            priority: Priority level (low, medium, high, urgent)
            is_overdue: Whether the task is overdue
        """
        if not assignee_name and not priority:
            return

        # Priority colors
        priority_colors = {
            'low': '#95A5A6',      # Gray
            'medium': '#3498DB',   # Blue
            'high': '#F39C12',     # Orange
            'urgent': '#E74C3C',   # Red
        }

        # Determine badge color
        if is_overdue:
            bg_color = QColor('#E74C3C')  # Red for overdue
        elif priority and priority in priority_colors:
            bg_color = QColor(priority_colors[priority])
        else:
            bg_color = QColor('#3498DB')  # Default blue

        # Draw badge background (pill shape)
        badge_height = 18
        badge_y = rect.y() + rect.height() - badge_height - 4
        
        # Calculate badge width based on content
        badge_text = ""
        if assignee_name:
            # Get initials
            parts = assignee_name.split()
            if len(parts) >= 2:
                initials = f"{parts[0][0]}{parts[1][0]}".upper()
            else:
                initials = assignee_name[:2].upper()
            badge_text = initials
        
        if priority and priority != 'medium':
            if badge_text:
                badge_text += f" {priority[0].upper()}"
            else:
                badge_text = priority[0].upper()

        if not badge_text:
            return

        # Calculate badge width
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(badge_text)
        badge_width = text_width + 12  # Padding
        
        badge_x = rect.x() + rect.width() - badge_width - 4
        badge_rect = QRect(badge_x, badge_y, badge_width, badge_height)

        # Draw rounded rect
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 4, 4)

        # Draw text
        painter.setPen(QColor('#FFFFFF'))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

    @staticmethod
    def draw_view_count_badge(
        painter: QPainter,
        rect: QRect,
        view_count: int
    ) -> None:
        """
        Draw view count badge for master shots showing number of camera views.

        Args:
            painter: QPainter instance
            rect: Thumbnail rectangle (badge drawn in top-left corner)
            view_count: Number of attached camera views
        """
        if view_count <= 0:
            return

        # Badge text
        badge_text = f"[{view_count} view{'s' if view_count > 1 else ''}]"

        # Calculate badge size
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(badge_text)
        badge_width = text_width + 10
        badge_height = 18

        # Position in top-left corner of thumbnail
        badge_x = rect.x() + 4
        badge_y = rect.y() + 4
        badge_rect = QRect(badge_x, badge_y, badge_width, badge_height)

        # Draw badge background (blue for multi-camera)
        painter.setBrush(QBrush(QColor("#2196F3")))  # Blue
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 4, 4)

        # Draw text
        painter.setPen(QColor('#FFFFFF'))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

    @staticmethod
    def draw_orphan_warning_badge(
        painter: QPainter,
        rect: QRect
    ) -> None:
        """
        Draw warning badge for orphaned view shots (master was deleted).

        Args:
            painter: QPainter instance
            rect: Thumbnail rectangle (badge drawn in top-left corner)
        """
        badge_text = "⚠ Orphan"

        # Calculate badge size
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(badge_text)
        badge_width = text_width + 10
        badge_height = 18

        # Position in top-left corner
        badge_x = rect.x() + 4
        badge_y = rect.y() + 4
        badge_rect = QRect(badge_x, badge_y, badge_width, badge_height)

        # Draw badge background (orange warning)
        painter.setBrush(QBrush(QColor("#FF9800")))  # Orange
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 4, 4)

        # Draw text
        painter.setPen(QColor('#000000'))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)


__all__ = ['ShotCardRenderer']
