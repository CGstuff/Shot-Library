"""
Shot Library Operators

Playblast and Lookdev operators for Shot Library.
Removed: pose capture, animation capture, asset export (Action Library specific)
Note: Representation swap functionality moved to Universal Library addon.
"""

import bpy
from bpy.utils import register_class, unregister_class

# Shot Library operators
from .SL_playblast import (
    SHOTLIB_OT_render_playblast,
    SHOTLIB_OT_open_playblast_folder,
)
from .SL_lookdev import (
    SHOTLIB_OT_render_lookdev,
    SHOTLIB_OT_open_lookdev_folder,
)
from .SL_launch_app import (
    SHOTLIB_OT_launch_desktop_app,
)

# Shot Library operator classes
classes = (
    SHOTLIB_OT_render_playblast,
    SHOTLIB_OT_open_playblast_folder,
    SHOTLIB_OT_render_lookdev,
    SHOTLIB_OT_open_lookdev_folder,
    SHOTLIB_OT_launch_desktop_app,
)

def _safe_register(cls):
    try:
        register_class(cls)
    except ValueError:
        # stale or duplicate class object: clean and retry
        try:
            unregister_class(cls)
        except Exception:
            pass
        register_class(cls)


def _safe_unregister(cls):
    try:
        unregister_class(cls)
    except Exception:
        pass


__OPS_REGISTERED = False


def register_operators():
    """Register Shot Library operators"""
    global __OPS_REGISTERED
    if __OPS_REGISTERED:
        return

    for cls in classes:
        _safe_register(cls)

    __OPS_REGISTERED = True


def unregister_operators():
    """Unregister Shot Library operators"""
    global __OPS_REGISTERED
    if not __OPS_REGISTERED:
        return

    for cls in reversed(classes):
        _safe_unregister(cls)

    __OPS_REGISTERED = False
