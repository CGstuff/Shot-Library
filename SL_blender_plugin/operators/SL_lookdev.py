"""
Shot Library Lookdev Operator

Renders lookdev preview from current render engine to Lookdev/ folder with version numbering.

Versioning strategy:
- Latest version is always at top level: Lookdev/{blend_stem}/{blend_stem}_LD_v###.mp4
- Old versions are archived to: Lookdev/{blend_stem}/_archive/

Key differences from playblast:
- For Cycles: Uses bpy.ops.render.render(animation=True) with sample override
- For EEVEE/Workbench: Sets viewport to RENDERED mode, then uses bpy.ops.render.opengl(animation=True)
  This captures the EEVEE lighting in a fast viewport render
- Tracks render engine and samples in metadata
- Viewport shading mode is restored after render
"""

import bpy
import os
import subprocess
import time
from pathlib import Path
from bpy.types import Operator
from bpy.props import IntProperty, EnumProperty, BoolProperty

from ..utils.logger import get_logger
from ..utils.lookdev_schema import (
    get_lookdev_config,
    get_lookdev_filename,
    get_metadata_filename,
    create_lookdev_metadata,
    save_lookdev_metadata,
)
from ..utils.version_manager import (
    get_next_lookdev_version,
    archive_lookdev_versions,
)
from ..utils.render_settings import (
    store_render_settings,
    restore_render_settings,
    configure_video_output,
)
# Automatic library swap disabled (lib_relocate crash) — manual panel used instead
# from ..utils.library_swap import swap_to_representation, schedule_restore

logger = get_logger()


def warning_not_saved(self, context):
    self.layout.label(text="Please save your blend file first")


def render_error(self, context):
    self.layout.label(text="Render failed. Check console for details.")


class SHOTLIB_OT_render_lookdev(Operator):
    """Render lookdev preview from current render engine"""
    bl_idname = "shotlib.render_lookdev"
    bl_label = "Render Lookdev"
    bl_description = "Render a lookdev preview using the scene's render engine"
    bl_options = {'REGISTER', 'UNDO'}

    # Properties
    samples_override: IntProperty(
        name="Preview Samples",
        description="Override Cycles samples for faster preview (0 = use scene settings)",
        default=32,
        min=0,
        max=4096
    )

    quality: EnumProperty(
        name="Quality",
        items=[
            ('PREVIEW', "Preview", "Fast preview quality (25%)"),
            ('HALF', "Half", "Half resolution (50%)"),
            ('FULL', "Full", "Full resolution (100%)"),
        ],
        default='HALF'
    )

    use_representation_swap: BoolProperty(
        name="Use Asset Representations",
        description="Swap linked UAL assets to render representations for lookdev",
        default=True
    )

    @classmethod
    def poll(cls, context):
        """Check if lookdev render can be executed"""
        return bpy.data.filepath != ""

    def execute(self, context):
        """Execute lookdev render"""
        # If file is not saved, show warning
        if not bpy.data.is_saved:
            context.window_manager.popup_menu(
                warning_not_saved, title="File not saved", icon='ERROR')
            return {'CANCELLED'}

        # Get paths
        blend_path = Path(bpy.data.filepath)
        blend_name = blend_path.stem  # Filename without extension
        shot_folder = blend_path.parent

        # Load project schema for lookdev configuration
        config = get_lookdev_config(blend_path)
        folder_name = config.get("folder_name", "Lookdev")
        archive_name = config.get("archive_folder", "_archive")

        # Create subfolder per blend file for version isolation
        # Structure: Lookdev/{blend_stem}/{blend_stem}_v###.mp4
        lookdev_folder = shot_folder / folder_name / blend_name
        archive_folder = lookdev_folder / archive_name

        # Create folders
        try:
            lookdev_folder.mkdir(parents=True, exist_ok=True)
            archive_folder.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self.report({'ERROR'}, f"Cannot create Lookdev folder: {lookdev_folder}")
            return {'CANCELLED'}

        # Archive existing versions
        archive_lookdev_versions(lookdev_folder, archive_folder, blend_name, config)

        # Determine next version
        next_version = get_next_lookdev_version(lookdev_folder, blend_name, config)

        # Generate filenames using schema
        output_filename = get_lookdev_filename(config, blend_name, next_version)
        metadata_filename = get_metadata_filename(config, blend_name, next_version)
        output_path = lookdev_folder / output_filename
        metadata_path = lookdev_folder / metadata_filename

        # Store ALL original settings (no overlay for lookdev)
        original = store_render_settings(context, include_overlay=False)

        # Store render info for metadata
        scene = context.scene
        frame_start = scene.frame_start
        frame_end = scene.frame_end
        fps = scene.render.fps
        resolution = (scene.render.resolution_x, scene.render.resolution_y)
        render_engine = scene.render.engine

        # Get effective samples
        effective_samples = 0
        if render_engine == 'CYCLES':
            if self.samples_override > 0:
                effective_samples = self.samples_override
            else:
                effective_samples = scene.cycles.samples
        elif render_engine == 'BLENDER_EEVEE':
            effective_samples = scene.eevee.taa_render_samples if hasattr(scene.eevee, 'taa_render_samples') else 64
        elif render_engine == 'BLENDER_EEVEE_NEXT':
            effective_samples = scene.eevee.taa_samples if hasattr(scene.eevee, 'taa_samples') else 64

        # Track render time
        start_time = time.time()

        # Automatic swap disabled — bpy.ops.wm.lib_relocate crashes during
        # ID remap (BKE_key_from_id null-ptr) when the proxy has fewer IDs
        # than the original.  Use the manual swap panel instead.
        swapped_paths = {}

        try:
            # Configure for lookdev render
            configure_video_output(context, output_path, self.quality)

            # Apply samples override for Cycles
            if render_engine == 'CYCLES' and self.samples_override > 0:
                scene.cycles.samples = self.samples_override
                logger.info(f"Cycles samples overridden to {self.samples_override}")

            self.report({'INFO'}, f"Rendering {output_filename} with {render_engine}...")

            try:
                # For Cycles: use full render (opengl doesn't support Cycles)
                # For EEVEE/Workbench: use opengl with RENDERED shading mode
                if render_engine == 'CYCLES':
                    bpy.ops.render.render(animation=True)
                else:
                    # Set viewport to Rendered shading mode for EEVEE lighting
                    for area in context.screen.areas:
                        if area.type == 'VIEW_3D':
                            for space in area.spaces:
                                if space.type == 'VIEW_3D':
                                    space.shading.type = 'RENDERED'
                            break
                    bpy.ops.render.opengl(animation=True)
            except Exception as e:
                context.window_manager.popup_menu(
                    render_error, title="Render error", icon='ERROR')
                logger.error(f"Render error: {e}")
                return {'CANCELLED'}

        finally:
            # ALWAYS restore original settings
            restore_render_settings(context, original, include_overlay=False)

            # Library swap/restore disabled — see comment above

        # Calculate render time
        render_time = time.time() - start_time

        # Create and save lookdev metadata JSON
        metadata = create_lookdev_metadata(
            version=next_version,
            blend_file=blend_path.name,
            frame_start=frame_start,
            frame_end=frame_end,
            resolution=resolution,
            fps=fps,
            render_engine=render_engine,
            samples=effective_samples,
            render_time_seconds=render_time
        )
        # Record representation swap info
        if swapped_paths:
            metadata['representation_swap'] = {
                'type': 'render',
                'libraries_swapped': len(swapped_paths),
                'library_names': list(swapped_paths.keys()),
            }
        if save_lookdev_metadata(metadata, metadata_path):
            logger.info(f"Saved metadata: {metadata_filename}")
        else:
            logger.warning(f"Failed to save metadata: {metadata_filename}")

        self.report({'INFO'}, f"Lookdev saved: {output_filename} ({render_time:.1f}s)")
        return {'FINISHED'}


class SHOTLIB_OT_open_lookdev_folder(Operator):
    """Open the Lookdev folder in file explorer"""
    bl_idname = "shotlib.open_lookdev_folder"
    bl_label = "Open Lookdev Folder"
    bl_description = "Open the Lookdev folder in your file explorer"

    @classmethod
    def poll(cls, context):
        return bpy.data.filepath != ""

    def execute(self, context):
        blend_path = Path(bpy.data.filepath)
        blend_name = blend_path.stem  # e.g., "SH0010_v002"

        # Get folder name from project schema
        config = get_lookdev_config(blend_path)
        folder_name = config.get("folder_name", "Lookdev")

        # Open blend-specific subfolder: Lookdev/{blend_stem}/
        lookdev_folder = blend_path.parent / folder_name / blend_name

        if not lookdev_folder.exists():
            # Fall back to parent Lookdev folder if blend-specific doesn't exist
            lookdev_folder = blend_path.parent / folder_name
            if not lookdev_folder.exists():
                self.report({'INFO'}, f"{folder_name} folder doesn't exist yet. Render a lookdev first.")
                # Open parent folder instead
                lookdev_folder = blend_path.parent

        # Open in file explorer
        import sys
        if sys.platform == 'win32':
            os.startfile(str(lookdev_folder))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(lookdev_folder)])
        else:
            subprocess.run(['xdg-open', str(lookdev_folder)])

        return {'FINISHED'}


# Classes to register
classes = [
    SHOTLIB_OT_render_lookdev,
    SHOTLIB_OT_open_lookdev_folder,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
