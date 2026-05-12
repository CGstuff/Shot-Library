"""
Shot Library Main Panel

Provides Blender UI for Shot Library - focused on playblast and lookdev capture.
Removes all asset/animation library functionality from Action Library.
"""

import bpy
from bpy.types import Panel
from pathlib import Path

from ..utils.playblast_schema import (
    get_playblast_config,
    get_playblast_filename,
)
from ..utils.lookdev_schema import (
    get_lookdev_config,
    get_lookdev_filename,
)
from ..utils.version_manager import (
    get_next_playblast_version,
    get_next_lookdev_version,
)
from ..utils.icon_loader import get_icon_id, Icons
from ..preferences.SL_preferences import get_preferences


class SHOTLIB_PT_main_panel(Panel):
    """Main Shot Library panel"""
    bl_label = "Shot Library"
    bl_idname = "SHOTLIB_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shot'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Launch Desktop App - Prominent button at top
        prefs = get_preferences()
        launch_enabled = False
        if prefs:
            if prefs.launch_mode == 'PRODUCTION' and prefs.app_executable_path:
                launch_enabled = True
            elif prefs.launch_mode == 'DEVELOPMENT' and prefs.dev_script_path:
                launch_enabled = True

        launch_box = layout.box()
        launch_row = launch_box.row()
        launch_row.scale_y = 1.5

        # Try to use custom icon, fall back to built-in
        icon_id = get_icon_id(Icons.LAUNCH_APP)
        if icon_id:
            launch_row.operator(
                "shotlib.launch_desktop_app",
                text="  Open Shot Library",
                icon_value=icon_id
            )
        else:
            launch_row.operator(
                "shotlib.launch_desktop_app",
                text="Open Shot Library",
                icon='WINDOW'
            )

        if not launch_enabled:
            launch_box.label(text="Configure path in addon preferences", icon='INFO')

        layout.separator()

        # File status
        status_box = layout.box()
        if bpy.data.filepath:
            blend_path = Path(bpy.data.filepath)
            shot_name = blend_path.stem

            status_box.label(text=f"Shot: {shot_name}", icon='FILE_BLEND')

            # Get folder name from project schema
            config = get_playblast_config(blend_path)
            folder_name = config.get("folder_name", "PlayBlast")
            archive_name = config.get("archive_folder", "_archive")
            ext = config.get("file_extension", ".mp4")

            # Show playblast folder status
            # New structure: PlayBlast/{blend_stem}/ with fallback to PlayBlast/
            playblast_subfolder = blend_path.parent / folder_name / shot_name
            playblast_folder = playblast_subfolder if playblast_subfolder.exists() else blend_path.parent / folder_name

            if playblast_folder.exists():
                # Count existing playblasts (main folder + _archive folder)
                # Match both old format and new format with blend name prefix
                playblasts = list(playblast_folder.glob(f"*{ext}"))
                archive_folder = playblast_folder / archive_name
                if archive_folder.exists():
                    playblasts.extend(archive_folder.glob(f"*{ext}"))

                if playblasts:
                    latest = max(playblasts, key=lambda p: p.name)
                    status_box.label(text=f"Latest: {latest.name}", icon='SEQUENCE')
                    status_box.label(text=f"Versions: {len(playblasts)}", icon='FILE_MOVIE')
                else:
                    status_box.label(text="No playblasts yet", icon='INFO')
            else:
                status_box.label(text=f"{folder_name} folder will be created", icon='INFO')
        else:
            status_box.label(text="Save file first", icon='ERROR')
            status_box.label(text="Playblast needs a saved .blend", icon='INFO')


class SHOTLIB_PT_playblast(Panel):
    """Playblast capture sub-panel"""
    bl_label = "Playblast"
    bl_idname = "SHOTLIB_PT_playblast"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shot'
    bl_parent_id = "SHOTLIB_PT_main_panel"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Check if file is saved
        if not bpy.data.filepath:
            layout.label(text="Save file to enable playblast", icon='ERROR')
            return

        # Camera status
        camera_box = layout.box()
        if scene.camera:
            camera_box.label(text=f"Camera: {scene.camera.name}", icon='CAMERA_DATA')
        else:
            camera_box.label(text="No scene camera!", icon='ERROR')
            camera_box.label(text="Add a camera for playblast", icon='INFO')

        # Frame range info
        info_box = layout.box()
        info_box.label(text="Frame Range", icon='TIME')
        info_row = info_box.row()
        info_row.label(text=f"Start: {scene.frame_start}")
        info_row.label(text=f"End: {scene.frame_end}")

        fps = scene.render.fps or 1
        duration = (scene.frame_end - scene.frame_start + 1) / fps
        info_box.label(text=f"Duration: {duration:.2f}s @ {scene.render.fps}fps")

        # Quality setting
        layout.separator()
        layout.prop(scene, "shotlib_playblast_quality", text="Quality")

        # Asset representation toggle
        layout.prop(scene, "shotlib_playblast_use_representations", text="Use Asset Representations")

        # Render Playblast button
        render_row = layout.row()
        render_row.scale_y = 2.0

        # Determine next version
        if bpy.data.filepath:
            blend_path = Path(bpy.data.filepath)
            blend_name = blend_path.stem

            # Get config from project schema
            config = get_playblast_config(blend_path)
            folder_name = config.get("folder_name", "PlayBlast")

            # New structure: PlayBlast/{blend_stem}/ with fallback to PlayBlast/
            playblast_subfolder = blend_path.parent / folder_name / blend_name
            playblast_folder = playblast_subfolder if playblast_subfolder.exists() else blend_path.parent / folder_name
            next_version = get_next_playblast_version(playblast_folder, blend_name, config)

            # Generate button text using schema pattern
            next_filename = get_playblast_filename(config, blend_name, next_version)
            button_text = f"Render {next_filename}"
        else:
            button_text = "Render Playblast"

        op = render_row.operator("shotlib.render_playblast", text=button_text, icon='RENDER_ANIMATION')
        op.use_representation_swap = scene.shotlib_playblast_use_representations

        # Open folder button
        layout.separator()
        if bpy.data.filepath:
            folder_label = f"Open {folder_name} Folder"
        else:
            folder_label = "Open PlayBlast Folder"
        layout.operator("shotlib.open_playblast_folder", text=folder_label, icon='FILE_FOLDER')


class SHOTLIB_PT_lookdev(Panel):
    """Lookdev render sub-panel"""
    bl_label = "Lookdev"
    bl_idname = "SHOTLIB_PT_lookdev"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shot'
    bl_parent_id = "SHOTLIB_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Check if file is saved
        if not bpy.data.filepath:
            layout.label(text="Save file to enable lookdev", icon='ERROR')
            return

        # Render engine info
        engine_box = layout.box()
        engine_name = scene.render.engine
        engine_display = {
            'CYCLES': 'Cycles',
            'BLENDER_EEVEE': 'EEVEE',
            'BLENDER_EEVEE_NEXT': 'EEVEE Next',
            'BLENDER_WORKBENCH': 'Workbench'
        }.get(engine_name, engine_name)
        engine_box.label(text=f"Engine: {engine_display}", icon='SHADING_RENDERED')

        # Cycles-specific: show/edit sample override
        if scene.render.engine == 'CYCLES':
            engine_box.prop(scene, "shotlib_lookdev_samples", text="Preview Samples")
            engine_box.label(text=f"Scene samples: {scene.cycles.samples}")

        # Frame range info
        info_box = layout.box()
        info_box.label(text="Frame Range", icon='TIME')
        info_row = info_box.row()
        info_row.label(text=f"Start: {scene.frame_start}")
        info_row.label(text=f"End: {scene.frame_end}")

        fps = scene.render.fps or 1
        duration = (scene.frame_end - scene.frame_start + 1) / fps
        info_box.label(text=f"Duration: {duration:.2f}s @ {scene.render.fps}fps")

        # Quality setting
        layout.separator()
        layout.prop(scene, "shotlib_lookdev_quality", text="Quality")

        # Asset representation toggle
        layout.prop(scene, "shotlib_lookdev_use_representations", text="Use Asset Representations")

        # Render Lookdev button
        render_row = layout.row()
        render_row.scale_y = 2.0

        # Determine next version
        blend_path = Path(bpy.data.filepath)
        blend_name = blend_path.stem

        # Get config from project schema
        config = get_lookdev_config(blend_path)
        folder_name = config.get("folder_name", "Lookdev")

        # New structure: Lookdev/{blend_stem}/ with fallback to Lookdev/
        lookdev_subfolder = blend_path.parent / folder_name / blend_name
        lookdev_folder = lookdev_subfolder if lookdev_subfolder.exists() else blend_path.parent / folder_name
        next_version = get_next_lookdev_version(lookdev_folder, blend_name, config)

        # Generate button text using schema pattern
        next_filename = get_lookdev_filename(config, blend_name, next_version)
        button_text = f"Render {next_filename}"

        op = render_row.operator("shotlib.render_lookdev", text=button_text, icon='RENDER_STILL')
        op.samples_override = scene.shotlib_lookdev_samples
        op.quality = scene.shotlib_lookdev_quality
        op.use_representation_swap = scene.shotlib_lookdev_use_representations

        # Lookdev status
        if lookdev_folder.exists():
            ext = config.get("file_extension", ".mp4")
            archive_name = config.get("archive_folder", "_archive")

            # Count existing lookdevs
            lookdevs = list(lookdev_folder.glob(f"*{ext}"))
            archive_folder = lookdev_folder / archive_name
            if archive_folder.exists():
                lookdevs.extend(archive_folder.glob(f"*{ext}"))

            if lookdevs:
                latest = max(lookdevs, key=lambda p: p.name)
                layout.label(text=f"Latest: {latest.name}", icon='SEQUENCE')
                layout.label(text=f"Versions: {len(lookdevs)}", icon='FILE_MOVIE')

        # Open folder button
        layout.separator()
        folder_label = f"Open {folder_name} Folder"
        layout.operator("shotlib.open_lookdev_folder", text=folder_label, icon='FILE_FOLDER')


class SHOTLIB_PT_settings(Panel):
    """Settings sub-panel"""
    bl_label = "Settings"
    bl_idname = "SHOTLIB_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shot'
    bl_parent_id = "SHOTLIB_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Resolution settings
        res_box = layout.box()
        res_box.label(text="Resolution", icon='IMAGE_DATA')
        res_box.prop(scene.render, "resolution_x", text="Width")
        res_box.prop(scene.render, "resolution_y", text="Height")

        # Camera settings
        layout.separator()
        cam_box = layout.box()
        cam_box.label(text="Camera", icon='CAMERA_DATA')
        cam_box.prop(scene, "camera", text="")

        # Frame range
        layout.separator()
        frame_box = layout.box()
        frame_box.label(text="Frame Range", icon='TIME')
        frame_box.prop(scene, "frame_start", text="Start")
        frame_box.prop(scene, "frame_end", text="End")
        frame_box.prop(scene.render, "fps", text="FPS")


# Panel registration list
classes = [
    SHOTLIB_PT_main_panel,
    SHOTLIB_PT_playblast,
    SHOTLIB_PT_lookdev,
    SHOTLIB_PT_settings,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
