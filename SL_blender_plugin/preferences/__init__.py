"""
Shot Library Preferences

Addon preferences for Shot Library.
"""

from bpy.utils import register_class, unregister_class

from .SL_preferences import ShotLibraryPreferences, get_preferences


classes = (
    ShotLibraryPreferences,
)


def register_preferences():
    """Register addon preferences"""
    for cls in classes:
        register_class(cls)


def unregister_preferences():
    """Unregister addon preferences"""
    for cls in reversed(classes):
        unregister_class(cls)
