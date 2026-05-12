"""
Review Service

Manages review sessions, comments, and annotations.
Implements the review-service contract.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from uuid import UUID, uuid4
import json

from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.timecode_utils import frame_to_timecode


@dataclass
class AnnotationData:
    """Draw-over annotation data."""
    id: UUID
    frame: int
    tool: str  # "brush", "arrow", "rectangle", "text"
    color: str  # Hex color
    stroke_width: int
    points: List[tuple[float, float]]
    text: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Comment:
    """A timestamped comment on a playblast."""
    id: UUID
    user_id: UUID
    frame: int
    timecode: str  # HH:MM:SS:FF
    content: str
    annotations: List[AnnotationData] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Review:
    """A review session for a shot."""
    id: UUID
    shot_id: UUID
    playblast_version: int
    comments: List[Comment] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class ReviewService(QObject):
    """
    Manages review sessions, comments, and annotations.

    Stores data in sidecar JSON files (.shot_review.json).
    Implements last-write-wins for concurrent access.
    """

    # Signals
    comment_added = pyqtSignal(object, object)  # shot_folder (Path), Comment
    comment_updated = pyqtSignal(object, object)  # shot_folder (Path), Comment
    comment_deleted = pyqtSignal(object, object)  # shot_folder (Path), UUID (comment_id)
    concurrent_edit_detected = pyqtSignal(object)  # shot_folder (Path)
    review_loaded = pyqtSignal(object, object)  # shot_folder (Path), Review

    def __init__(self, sidecar_filename: str = ".shot_review.json", parent=None):
        """
        Initialize review service.

        Args:
            sidecar_filename: Name of sidecar file in shot folders
        """
        super().__init__(parent)
        self._sidecar_filename = sidecar_filename

    def get_review(self, shot_folder: Path) -> Optional[Review]:
        """
        Load review data for a shot.

        Args:
            shot_folder: Path to shot folder

        Returns:
            Review or None if no review exists
        """
        sidecar_path = shot_folder / self._sidecar_filename

        if not sidecar_path.exists():
            return None

        try:
            with open(sidecar_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            review = self._dict_to_review(data)
            self.review_loaded.emit(shot_folder, review)
            return review

        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def create_review(
        self,
        shot_folder: Path,
        shot_id: UUID,
        playblast_version: int
    ) -> Review:
        """
        Create a new review session.

        Args:
            shot_folder: Path to shot folder
            shot_id: Shot UUID
            playblast_version: Version being reviewed

        Returns:
            New Review instance

        Raises:
            FileExistsError: If review already exists
        """
        sidecar_path = shot_folder / self._sidecar_filename

        if sidecar_path.exists():
            raise FileExistsError(f"Review already exists: {sidecar_path}")

        now = datetime.now()
        review = Review(
            id=uuid4(),
            shot_id=shot_id,
            playblast_version=playblast_version,
            comments=[],
            created_at=now,
            updated_at=now
        )

        self._write_sidecar(shot_folder, review)
        return review

    def add_comment(
        self,
        shot_folder: Path,
        user_id: UUID,
        frame: int,
        content: str,
        annotations: Optional[List[AnnotationData]] = None
    ) -> Comment:
        """
        Add a comment to a review.

        Creates review if it doesn't exist.

        Args:
            shot_folder: Path to shot folder
            user_id: Commenting user's UUID
            frame: Frame number for comment
            content: Comment text
            annotations: Optional draw-over annotations

        Returns:
            Created Comment

        Raises:
            ValueError: If content is empty
        """
        if not content or not content.strip():
            raise ValueError("Comment content cannot be empty")

        review = self.get_review(shot_folder)

        if review is None:
            # Create a review with placeholder values
            # In a real implementation, we'd need the shot_id and playblast_version
            review = Review(
                id=uuid4(),
                shot_id=uuid4(),  # Placeholder
                playblast_version=0,  # Placeholder
                comments=[],
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

        # Generate timecode (placeholder - would need FPS info)
        timecode = self._frame_to_timecode(frame, 24.0)

        comment = Comment(
            id=uuid4(),
            user_id=user_id,
            frame=frame,
            timecode=timecode,
            content=content,
            annotations=annotations or [],
            created_at=datetime.now()
        )

        review.comments.append(comment)
        review.updated_at = datetime.now()

        self._write_sidecar(shot_folder, review)
        self.comment_added.emit(shot_folder, comment)

        return comment

    def update_comment(
        self,
        shot_folder: Path,
        comment_id: UUID,
        content: Optional[str] = None,
        annotations: Optional[List[AnnotationData]] = None
    ) -> Comment:
        """
        Update an existing comment.

        Args:
            shot_folder: Path to shot folder
            comment_id: Comment to update
            content: New content (None to keep existing)
            annotations: New annotations (None to keep existing)

        Returns:
            Updated Comment

        Raises:
            KeyError: If comment not found
        """
        review = self.get_review(shot_folder)
        if review is None:
            raise KeyError(f"No review found for: {shot_folder}")

        # Find comment
        comment = None
        for c in review.comments:
            if c.id == comment_id:
                comment = c
                break

        if comment is None:
            raise KeyError(f"Comment not found: {comment_id}")

        # Update fields
        if content is not None:
            comment.content = content
        if annotations is not None:
            comment.annotations = annotations

        review.updated_at = datetime.now()
        self._write_sidecar(shot_folder, review)
        self.comment_updated.emit(shot_folder, comment)

        return comment

    def delete_comment(
        self,
        shot_folder: Path,
        comment_id: UUID
    ) -> None:
        """
        Delete a comment.

        Args:
            shot_folder: Path to shot folder
            comment_id: Comment to delete

        Raises:
            KeyError: If comment not found
        """
        review = self.get_review(shot_folder)
        if review is None:
            raise KeyError(f"No review found for: {shot_folder}")

        # Find and remove comment
        original_count = len(review.comments)
        review.comments = [c for c in review.comments if c.id != comment_id]

        if len(review.comments) == original_count:
            raise KeyError(f"Comment not found: {comment_id}")

        review.updated_at = datetime.now()
        self._write_sidecar(shot_folder, review)
        self.comment_deleted.emit(shot_folder, comment_id)

    def get_comments_at_frame(
        self,
        shot_folder: Path,
        frame: int
    ) -> List[Comment]:
        """
        Get all comments at a specific frame.

        Args:
            shot_folder: Path to shot folder
            frame: Frame number

        Returns:
            List of comments at frame
        """
        review = self.get_review(shot_folder)
        if review is None:
            return []

        return [c for c in review.comments if c.frame == frame]

    def get_comments_by_user(
        self,
        shot_folder: Path,
        user_id: UUID
    ) -> List[Comment]:
        """
        Get all comments by a specific user.

        Args:
            shot_folder: Path to shot folder
            user_id: User's UUID

        Returns:
            List of comments by user
        """
        review = self.get_review(shot_folder)
        if review is None:
            return []

        return [c for c in review.comments if c.user_id == user_id]

    def check_for_changes(
        self,
        shot_folder: Path,
        last_known_update: datetime
    ) -> bool:
        """
        Check if sidecar file has been modified.

        Used for detecting concurrent edits.

        Args:
            shot_folder: Path to shot folder
            last_known_update: Last known update time

        Returns:
            True if file has been modified since last_known_update
        """
        sidecar_path = shot_folder / self._sidecar_filename

        if not sidecar_path.exists():
            return False

        mtime = datetime.fromtimestamp(sidecar_path.stat().st_mtime)
        return mtime > last_known_update

    def _write_sidecar(self, shot_folder: Path, review: Review) -> None:
        """Write review to sidecar file."""
        sidecar_path = shot_folder / self._sidecar_filename

        # Check for concurrent edits
        if sidecar_path.exists():
            mtime = datetime.fromtimestamp(sidecar_path.stat().st_mtime)
            if mtime > review.updated_at:
                self.concurrent_edit_detected.emit(shot_folder)

        # Write atomically (write to temp, then rename)
        temp_path = sidecar_path.with_suffix('.tmp')
        data = self._review_to_dict(review)

        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        temp_path.replace(sidecar_path)

    def _review_to_dict(self, review: Review) -> dict:
        """Convert Review to dictionary for JSON serialization."""
        return {
            'id': str(review.id),
            'shot_id': str(review.shot_id),
            'playblast_version': review.playblast_version,
            'comments': [self._comment_to_dict(c) for c in review.comments],
            'created_at': review.created_at.isoformat(),
            'updated_at': review.updated_at.isoformat()
        }

    def _comment_to_dict(self, comment: Comment) -> dict:
        """Convert Comment to dictionary."""
        return {
            'id': str(comment.id),
            'user_id': str(comment.user_id),
            'frame': comment.frame,
            'timecode': comment.timecode,
            'content': comment.content,
            'annotations': [self._annotation_to_dict(a) for a in comment.annotations],
            'created_at': comment.created_at.isoformat()
        }

    def _annotation_to_dict(self, annotation: AnnotationData) -> dict:
        """Convert AnnotationData to dictionary."""
        return {
            'id': str(annotation.id),
            'frame': annotation.frame,
            'tool': annotation.tool,
            'color': annotation.color,
            'stroke_width': annotation.stroke_width,
            'points': annotation.points,
            'text': annotation.text,
            'created_at': annotation.created_at.isoformat()
        }

    def _dict_to_review(self, data: dict) -> Review:
        """Convert dictionary to Review."""
        return Review(
            id=UUID(data['id']),
            shot_id=UUID(data['shot_id']),
            playblast_version=data['playblast_version'],
            comments=[self._dict_to_comment(c) for c in data.get('comments', [])],
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at'])
        )

    def _dict_to_comment(self, data: dict) -> Comment:
        """Convert dictionary to Comment."""
        return Comment(
            id=UUID(data['id']),
            user_id=UUID(data['user_id']),
            frame=data['frame'],
            timecode=data['timecode'],
            content=data['content'],
            annotations=[self._dict_to_annotation(a) for a in data.get('annotations', [])],
            created_at=datetime.fromisoformat(data['created_at'])
        )

    def _dict_to_annotation(self, data: dict) -> AnnotationData:
        """Convert dictionary to AnnotationData."""
        return AnnotationData(
            id=UUID(data['id']),
            frame=data['frame'],
            tool=data['tool'],
            color=data['color'],
            stroke_width=data['stroke_width'],
            points=data['points'],
            text=data.get('text'),
            created_at=datetime.fromisoformat(data['created_at'])
        )

    def _frame_to_timecode(self, frame: int, fps: float) -> str:
        """
        Generate SMPTE timecode from frame number.

        Uses centralized timecode utility.
        """
        return frame_to_timecode(frame, fps)


__all__ = [
    'AnnotationData',
    'Comment',
    'Review',
    'ReviewService',
]
