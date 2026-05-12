"""
Shot Library Scene Properties

Scene-level properties for Shot Library Blender plugin.
"""

import bpy
from bpy.props import EnumProperty, BoolProperty, IntProperty


def register_properties():
    """Register Shot Library scene properties"""

    # Playblast quality setting
    bpy.types.Scene.shotlib_playblast_quality = EnumProperty(
        name="Playblast Quality",
        description="Quality setting for playblast render",
        items=[
            ('PREVIEW', "Preview", "Fast preview quality (50%)"),
            ('HALF', "Half", "Half resolution (50%)"),
            ('FULL', "Full", "Full resolution (100%)"),
        ],
        default='HALF'
    )

    # Use scene camera toggle
    bpy.types.Scene.shotlib_use_scene_camera = BoolProperty(
        name="Use Scene Camera",
        description="Render from scene camera instead of viewport",
        default=True
    )

    # Lookdev quality setting
    bpy.types.Scene.shotlib_lookdev_quality = EnumProperty(
        name="Lookdev Quality",
        description="Quality/resolution setting for lookdev render",
        items=[
            ('PREVIEW', "Preview", "Fast preview quality (25%)"),
            ('HALF', "Half", "Half resolution (50%)"),
            ('FULL', "Full", "Full resolution (100%)"),
        ],
        default='HALF'
    )

    # Lookdev samples override (for Cycles)
    bpy.types.Scene.shotlib_lookdev_samples = IntProperty(
        name="Lookdev Samples",
        description="Override Cycles samples for faster preview (0 = use scene settings)",
        default=32,
        min=0,
        max=4096
    )

    # Playblast: swap UAL linked assets to proxy representation
    bpy.types.Scene.shotlib_playblast_use_representations = BoolProperty(
        name="Use Asset Representations (Playblast)",
        description="Swap linked UAL assets to proxy representations during playblast",
        default=True
    )

    # Lookdev: swap UAL linked assets to render representation
    bpy.types.Scene.shotlib_lookdev_use_representations = BoolProperty(
        name="Use Asset Representations (Lookdev)",
        description="Swap linked UAL assets to render representations during lookdev",
        default=True
    )

    # Representation panel: selected-only toggle
    bpy.types.Scene.shotlib_repr_selected_only = BoolProperty(
        name="Representation Selected Only",
        description="Apply representation swaps only to selected objects' libraries",
        default=False
    )


def unregister_properties():
    """Unregister Shot Library scene properties"""

    if hasattr(bpy.types.Scene, 'shotlib_playblast_quality'):
        del bpy.types.Scene.shotlib_playblast_quality

    if hasattr(bpy.types.Scene, 'shotlib_use_scene_camera'):
        del bpy.types.Scene.shotlib_use_scene_camera

    if hasattr(bpy.types.Scene, 'shotlib_lookdev_quality'):
        del bpy.types.Scene.shotlib_lookdev_quality

    if hasattr(bpy.types.Scene, 'shotlib_lookdev_samples'):
        del bpy.types.Scene.shotlib_lookdev_samples

    if hasattr(bpy.types.Scene, 'shotlib_playblast_use_representations'):
        del bpy.types.Scene.shotlib_playblast_use_representations

    if hasattr(bpy.types.Scene, 'shotlib_lookdev_use_representations'):
        del bpy.types.Scene.shotlib_lookdev_use_representations

    if hasattr(bpy.types.Scene, 'shotlib_repr_selected_only'):
        del bpy.types.Scene.shotlib_repr_selected_only


def register():
    register_properties()


def unregister():
    unregister_properties()
