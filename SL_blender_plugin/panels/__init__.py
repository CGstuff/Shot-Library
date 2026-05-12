"""
Shot Library Panels

Blender UI panels for Shot Library - playblast and lookdev focused.
Note: Representation swap functionality moved to Universal Library addon.
"""

from bpy.utils import register_class, unregister_class

from .SL_main_panel import (
    SHOTLIB_PT_main_panel,
    SHOTLIB_PT_playblast,
    SHOTLIB_PT_lookdev,
    SHOTLIB_PT_settings,
)

classes = (
    SHOTLIB_PT_main_panel,
    SHOTLIB_PT_playblast,
    SHOTLIB_PT_lookdev,
    SHOTLIB_PT_settings,
)


def register_panels():
    """Register all panel classes"""
    for cls in classes:
        register_class(cls)


def unregister_panels():
    """Unregister all panel classes"""
    for cls in reversed(classes):
        unregister_class(cls)
