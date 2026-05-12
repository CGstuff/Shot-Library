"""
Shot Library Properties

Scene and window manager properties for Shot Library.
"""

from .SL_scene_properties import register as register_scene_props, unregister as unregister_scene_props


def register_properties():
    """Register Shot Library properties"""
    register_scene_props()


def unregister_properties():
    """Unregister Shot Library properties"""
    unregister_scene_props()
