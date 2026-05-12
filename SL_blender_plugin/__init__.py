bl_info = {
    "name": "Shot Library",
    "author": "CG_stuff",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar > Shot",
    "description": "Render playblasts from scene camera to PlayBlast folder with versioning",
    "category": "Render",
}

import bpy
from .registration import register_all, unregister_all


def register():
    """Register Shot Library addon"""
    register_all()


def unregister():
    """Unregister Shot Library addon"""
    unregister_all()


if __name__ == "__main__":
    register()
