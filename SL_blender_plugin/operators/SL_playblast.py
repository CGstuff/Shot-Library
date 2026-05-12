"""
Shot Library Playblast Operator

Renders playblast from viewport to PlayBlast/ folder with version numbering.
Uses Blender's native FFMPEG encoding (4.0+) or fallback to external ffmpeg.

Versioning strategy:
- Latest version is always at top level: PlayBlast/v###.mp4
- Old versions are archived to: PlayBlast/_archive/v###.mp4
"""

import bpy
import os
import subprocess
from pathlib import Path
from bpy.types import Operator
from bpy.props import BoolProperty, EnumProperty

from ..utils.logger import get_logger
from ..utils.playblast_schema import (
    get_playblast_config,
    get_playblast_filename,
    get_metadata_filename,
    create_playblast_metadata,
    save_playblast_metadata,
)
from ..utils.version_manager import (
    get_next_playblast_version,
    archive_playblast_versions,
)
from ..utils.render_settings import (
    store_render_settings,
    restore_render_settings,
    configure_video_output,
    hide_overlays,
)
# Automatic library swap disabled (lib_relocate crash) — manual panel used instead
# from ..utils.library_swap import swap_to_representation, schedule_restore

logger = get_logger()


def warning_not_saved(self, context):
    self.layout.label(text="Please save your blend file first")


def codecs_error(self, context):
    self.layout.label(
        text="Set resolution divisible by 2, or choose another codec")


class SHOTLIB_OT_render_playblast(Operator):
    """Render playblast from viewport to PlayBlast folder"""
    bl_idname = "shotlib.render_playblast"
    bl_label = "Render Playblast"
    bl_description = "Render a viewport playblast to the PlayBlast folder"
    bl_options = {'REGISTER', 'UNDO'}

    # Properties
    use_scene_camera: BoolProperty(
        name="Use Scene Camera",
        description="Render from scene camera instead of current viewport",
        default=True
    )

    quality: EnumProperty(
        name="Quality",
        items=[
            ('PREVIEW', "Preview", "Fast preview quality (50%)"),
            ('HALF', "Half", "Half resolution (50%)"),
            ('FULL', "Full", "Full resolution (100%)"),
        ],
        default='HALF'
    )

    hide_overlays: EnumProperty(
        name="Hide Overlays",
        items=[
            ('ALL', "All", "Hide all overlays"),
            ('BONES', "Bones Only", "Hide only bone overlays"),
            ('NONE', "None", "Keep overlays visible"),
        ],
        default='ALL'
    )

    use_representation_swap: BoolProperty(
        name="Use Asset Representations",
        description="Swap linked UAL assets to proxy representations for playblast",
        default=True
    )

    @classmethod
    def poll(cls, context):
        """Check if playblast can be rendered"""
        if context.area is not None:
            if context.area.ui_type == 'VIEW_3D':
                return True
        return False

    def execute(self, context):
        """Execute playblast render"""
        # If file is not saved, show warning
        if not bpy.data.is_saved:
            context.window_manager.popup_menu(
                warning_not_saved, title="File not saved", icon='ERROR')
            return {'CANCELLED'}

        # Get paths
        blend_path = Path(bpy.data.filepath)
        blend_name = blend_path.stem  # Filename without extension
        shot_folder = blend_path.parent

        # Load project schema for playblast configuration
        config = get_playblast_config(blend_path)
        folder_name = config.get("folder_name", "PlayBlast")
        archive_name = config.get("archive_folder", "_archive")

        # Create subfolder per blend file for version isolation
        # Structure: PlayBlast/{blend_stem}/{blend_stem}_v###.mp4
        playblast_folder = shot_folder / folder_name / blend_name
        archive_folder = playblast_folder / archive_name

        # Create folders
        try:
            playblast_folder.mkdir(parents=True, exist_ok=True)
            archive_folder.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self.report({'ERROR'}, f"Cannot create PlayBlast folder: {playblast_folder}")
            return {'CANCELLED'}

        # Archive existing versions
        archive_playblast_versions(playblast_folder, archive_folder, blend_name, config)

        # Determine next version
        next_version = get_next_playblast_version(playblast_folder, blend_name, config)

        # Generate filenames using schema
        output_filename = get_playblast_filename(config, blend_name, next_version)
        metadata_filename = get_metadata_filename(config, blend_name, next_version)
        output_path = playblast_folder / output_filename
        metadata_path = playblast_folder / metadata_filename

        # Store ALL original settings
        original = store_render_settings(context, include_overlay=True)

        # Store render info for metadata
        scene = context.scene
        frame_start = scene.frame_start
        frame_end = scene.frame_end
        fps = scene.render.fps
        resolution = (scene.render.resolution_x, scene.render.resolution_y)

        # Automatic swap disabled — bpy.ops.wm.lib_relocate crashes during
        # ID remap (BKE_key_from_id null-ptr) when the proxy has fewer IDs
        # than the original.  Use the manual swap panel instead.
        swapped_paths = {}

        try:
            # Configure for playblast
            # Note: playblast uses 50% for both PREVIEW and HALF quality
            quality_for_render = 'HALF' if self.quality in ('PREVIEW', 'HALF') else 'FULL'
            configure_video_output(context, output_path, quality_for_render)
            hide_overlays(context, self.hide_overlays)

            # Set camera view if requested
            if self.use_scene_camera and context.scene.camera:
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            if space.type == 'VIEW_3D':
                                space.region_3d.view_perspective = 'CAMERA'
                        break

            # Render using Blender's native FFMPEG
            self.report({'INFO'}, f"Rendering {output_filename}...")

            try:
                bpy.ops.render.opengl(animation=True)
            except Exception as e:
                context.window_manager.popup_menu(
                    codecs_error, title="Codecs error", icon='ERROR')
                logger.error(f"Render error: {e}")
                return {'CANCELLED'}

        finally:
            # ALWAYS restore original settings
            restore_render_settings(context, original, include_overlay=True)

            # Library swap/restore disabled — see comment above

        # Create and save playblast metadata JSON
        metadata = create_playblast_metadata(
            version=next_version,
            blend_file=blend_path.name,
            frame_start=frame_start,
            frame_end=frame_end,
            resolution=resolution,
            fps=fps,
            quality=self.quality
        )
        # Record representation swap info
        if swapped_paths:
            metadata['representation_swap'] = {
                'type': 'proxy',
                'libraries_swapped': len(swapped_paths),
                'library_names': list(swapped_paths.keys()),
            }
        if save_playblast_metadata(metadata, metadata_path):
            logger.info(f"Saved metadata: {metadata_filename}")
        else:
            logger.warning(f"Failed to save metadata: {metadata_filename}")

        self.report({'INFO'}, f"Playblast saved: {output_filename}")
        return {'FINISHED'}


class SHOTLIB_OT_open_playblast_folder(Operator):
    """Open the PlayBlast folder in file explorer"""
    bl_idname = "shotlib.open_playblast_folder"
    bl_label = "Open PlayBlast Folder"
    bl_description = "Open the PlayBlast folder in your file explorer"

    @classmethod
    def poll(cls, context):
        return bpy.data.filepath != ""

    def execute(self, context):
        blend_path = Path(bpy.data.filepath)
        blend_name = blend_path.stem  # e.g., "SH0010_v002"

        # Get folder name from project schema
        config = get_playblast_config(blend_path)
        folder_name = config.get("folder_name", "PlayBlast")

        # Open blend-specific subfolder: PlayBlast/{blend_stem}/
        playblast_folder = blend_path.parent / folder_name / blend_name

        if not playblast_folder.exists():
            # Fall back to parent PlayBlast folder if blend-specific doesn't exist
            playblast_folder = blend_path.parent / folder_name
            if not playblast_folder.exists():
                self.report({'INFO'}, f"{folder_name} folder doesn't exist yet. Render a playblast first.")
                # Open parent folder instead
                playblast_folder = blend_path.parent

        # Open in file explorer
        import sys
        if sys.platform == 'win32':
            os.startfile(str(playblast_folder))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(playblast_folder)])
        else:
            subprocess.run(['xdg-open', str(playblast_folder)])

        return {'FINISHED'}


# Classes to register
classes = [
    SHOTLIB_OT_render_playblast,
    SHOTLIB_OT_open_playblast_folder,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
