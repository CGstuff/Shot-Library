"""
Editorial Order

Regex-based extraction of episode/sequence/scene/shot numbers from shot names.
Implements the hierarchical sorting required by the Storyboard Law (FR-017, FR-018).

Shot Library NEVER allows user-defined sort order - editorial order is the only order.
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class EditorialComponents:
    """Extracted editorial order components."""
    episode: int = 0
    sequence: int = 0
    scene: int = 0
    shot: int = 0
    confidence: float = 0.0
    warning: Optional[str] = None


# Priority-ordered regex patterns for extracting editorial components
# More specific patterns come first
EDITORIAL_PATTERNS = [
    # Full: EP + SQ + SC + SH (e.g., EP01_SQ010_SC001_SH020, EP_01_SEQ_010_SCENE_001_SHOT_020)
    (
        r'^(?:EP[_\-]?)?(\d+)[_\-]?(?:SQ|SEQ)[_\-]?(\d+)[_\-]?(?:SC|SCENE)[_\-]?(\d+)[_\-]?(?:SH|SHOT)[_\-]?(\d+)',
        ('episode', 'sequence', 'scene', 'shot'),
        1.0
    ),
    # EP + SQ + SH (e.g., EP01_SQ010_SH020, ep01_seq010_shot020)
    (
        r'^(?:EP[_\-]?)?(\d+)[_\-]?(?:SQ|SEQ)[_\-]?(\d+)[_\-]?(?:SH|SHOT)[_\-]?(\d+)',
        ('episode', 'sequence', 'shot'),
        0.9
    ),
    # SQ + SC + SH (e.g., SQ010_SC001_SH020)
    (
        r'^(?:SQ|SEQ)[_\-]?(\d+)[_\-]?(?:SC|SCENE)[_\-]?(\d+)[_\-]?(?:SH|SHOT)[_\-]?(\d+)',
        ('sequence', 'scene', 'shot'),
        0.85
    ),
    # SQ + SH (industry standard, e.g., SQ010_SH020, seq_010_shot_020)
    (
        r'^(?:SQ|SEQ)[_\-]?(\d+)[_\-]?(?:SH|SHOT)[_\-]?(\d+)',
        ('sequence', 'shot'),
        0.8
    ),
    # EP + SH (e.g., EP01_SH020)
    (
        r'^(?:EP[_\-]?)?(\d+)[_\-]?(?:SH|SHOT)[_\-]?(\d+)',
        ('episode', 'shot'),
        0.7
    ),
    # SC + SH (e.g., SC001_SH020, scene_01_shot_20)
    (
        r'^(?:SC|SCENE)[_\-]?(\d+)[_\-]?(?:SH|SHOT)[_\-]?(\d+)',
        ('scene', 'shot'),
        0.7
    ),
    # Simple shot_NNN or sh_NNN or SHOT_NNN (e.g., shot_042, sh_100, SHOT_0050)
    (
        r'^(?:SHOT|SH|shot|sh)[_\-]?(\d+)(?:[_\-\.]|$)',
        ('shot',),
        0.6
    ),
    # Just a number at the end as shot (e.g., myshot_042, test_0100)
    (
        r'[_\-](\d+)(?:[_\-\.]|$)',
        ('shot',),
        0.4
    ),
    # Bare number (e.g., 042, 0100) - lowest confidence
    (
        r'^(\d+)$',
        ('shot',),
        0.3
    ),
]

# Compiled patterns for efficiency
_COMPILED_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), groups, confidence)
    for pattern, groups, confidence in EDITORIAL_PATTERNS
]


def extract_editorial_components(name: str) -> EditorialComponents:
    """
    Extract editorial order components from a shot/folder name.

    Args:
        name: Shot name, folder name, or filename (without extension)

    Returns:
        EditorialComponents with extracted values

    Examples:
        >>> extract_editorial_components("EP01_SQ010_SH020")
        EditorialComponents(episode=1, sequence=10, scene=0, shot=20, confidence=0.9)

        >>> extract_editorial_components("SQ050_SH001")
        EditorialComponents(episode=0, sequence=50, scene=0, shot=1, confidence=0.8)

        >>> extract_editorial_components("shot_042")
        EditorialComponents(episode=0, sequence=0, scene=0, shot=42, confidence=0.6)
    """
    if not name:
        return EditorialComponents(warning="Empty name provided")

    # Strip common file extensions if present
    name_clean = name
    for ext in ['.blend', '.mp4', '.mov', '.avi']:
        if name_clean.lower().endswith(ext):
            name_clean = name_clean[:-len(ext)]
            break

    # Try each pattern in priority order
    for compiled_pattern, groups, confidence in _COMPILED_PATTERNS:
        match = compiled_pattern.search(name_clean)
        if match:
            result = EditorialComponents(confidence=confidence)

            # Extract matched groups
            for i, group_name in enumerate(groups):
                try:
                    value = int(match.group(i + 1))
                    setattr(result, group_name, value)
                except (ValueError, IndexError):
                    pass

            return result

    # No pattern matched - return default with warning
    return EditorialComponents(
        warning=f"Could not parse editorial order from: {name}"
    )


def generate_editorial_order_string(
    episode: int = 0,
    sequence: int = 0,
    scene: int = 0,
    shot: int = 0
) -> str:
    """
    Generate editorial order string from component numbers.

    Format: "EEEE.SSSS.CCCC.HHHH" (4-digit zero-padded components)

    This string sorts correctly as a plain string comparison since each
    component is zero-padded to the same width.

    Args:
        episode: Episode number (0 if not applicable)
        sequence: Sequence number (0 if not applicable)
        scene: Scene number (0 if not applicable)
        shot: Shot number (0 if not applicable)

    Returns:
        Sort key string in format "EEEE.SSSS.CCCC.HHHH"

    Examples:
        >>> generate_editorial_order_string(1, 10, 0, 20)
        "0001.0010.0000.0020"

        >>> generate_editorial_order_string(sequence=50, shot=1)
        "0000.0050.0000.0001"
    """
    return f"{episode:04d}.{sequence:04d}.{scene:04d}.{shot:04d}"


# Sort key for unparseable names - sorts to the end
UNPARSEABLE_ORDER = "9999.9999.9999.9999"


def get_editorial_order(name: str) -> Tuple[str, Optional[str]]:
    """
    Get the editorial order string for a shot name.

    Convenience function that extracts components and generates the order string.

    Args:
        name: Shot name to parse

    Returns:
        Tuple of (editorial_order_string, warning_or_none)

    Examples:
        >>> get_editorial_order("EP01_SQ010_SH020")
        ("0001.0010.0000.0020", None)

        >>> get_editorial_order("random_folder")
        ("9999.9999.9999.9999", "Could not parse editorial order from: random_folder")
    """
    components = extract_editorial_components(name)

    if components.warning:
        # Could not parse - sort to end
        return UNPARSEABLE_ORDER, components.warning

    order = generate_editorial_order_string(
        episode=components.episode,
        sequence=components.sequence,
        scene=components.scene,
        shot=components.shot
    )

    return order, None


def compare_editorial_order(a: str, b: str) -> int:
    """
    Compare two editorial order strings.

    Args:
        a: First editorial order string
        b: Second editorial order string

    Returns:
        -1 if a < b, 0 if a == b, 1 if a > b
    """
    if a < b:
        return -1
    elif a > b:
        return 1
    return 0


__all__ = [
    'EditorialComponents',
    'EDITORIAL_PATTERNS',
    'UNPARSEABLE_ORDER',
    'extract_editorial_components',
    'generate_editorial_order_string',
    'get_editorial_order',
    'compare_editorial_order',
]
