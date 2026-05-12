"""
Shot Library Preferences

Addon preferences for Shot Library Blender plugin.
Simplified - uses Blender's native FFMPEG encoding.
"""

import bpy
from bpy.types import AddonPreferences
from bpy.props import EnumProperty, BoolProperty, StringProperty


class ShotLibraryPreferences(AddonPreferences):
    """Shot Library addon preferences"""
    bl_idname = "SL_blender_plugin"  # Must match the addon folder name

    # Playblast settings
    default_quality: EnumProperty(
        name="Default Quality",
        description="Default playblast quality setting",
        items=[
            ('PREVIEW', "Preview", "Fast preview quality (50%)"),
            ('HALF', "Half", "Half resolution (50%)"),
            ('FULL', "Full", "Full resolution (100%)"),
        ],
        default='HALF'
    )

    default_hide_overlays: EnumProperty(
        name="Hide Overlays",
        description="Default overlay hiding during playblast",
        items=[
            ('ALL', "All", "Hide all overlays"),
            ('BONES', "Bones Only", "Hide only bone overlays"),
            ('NONE', "None", "Keep overlays visible"),
        ],
        default='ALL'
    )

    auto_open_folder: BoolProperty(
        name="Auto Open Folder",
        description="Automatically open PlayBlast folder after render",
        default=False
    )

    # Desktop App Launch Settings
    launch_mode: EnumProperty(
        name="Launch Mode",
        description="How to launch the Shot Library desktop app",
        items=[
            ('PRODUCTION', "Production", "Launch compiled executable"),
            ('DEVELOPMENT', "Development", "Run Python script directly"),
        ],
        default='PRODUCTION'
    )

    app_executable_path: StringProperty(
        name="App Executable",
        description="Path to ShotLibrary.exe (for Production mode)",
        subtype='FILE_PATH',
        default=""
    )

    dev_script_path: StringProperty(
        name="Dev Script Path",
        description="Path to run.py (for Development mode)",
        subtype='FILE_PATH',
        default=""
    )

    python_executable: StringProperty(
        name="Python Executable",
        description="Python interpreter path (for Development mode)",
        subtype='FILE_PATH',
        default="python"
    )

    def draw(self, context):
        layout = self.layout

        # Playblast settings
        playblast_box = layout.box()
        playblast_box.label(text="Playblast Settings", icon='RENDER_ANIMATION')

        playblast_box.prop(self, "default_quality")
        playblast_box.prop(self, "default_hide_overlays")
        playblast_box.prop(self, "auto_open_folder")

        # Info about encoding
        layout.separator()
        info_box = layout.box()
        info_box.label(text="Video Encoding", icon='FILE_MOVIE')
        info_box.label(text="Uses Blender's native FFMPEG (H.264/MP4)", icon='CHECKMARK')

        # Desktop App Settings
        layout.separator()
        app_box = layout.box()
        app_box.label(text="Desktop App Settings", icon='WINDOW')

        app_box.prop(self, "launch_mode")

        if self.launch_mode == 'PRODUCTION':
            app_box.prop(self, "app_executable_path")
            if not self.app_executable_path:
                app_box.label(text="Set executable path to enable launch button", icon='INFO')
        else:
            app_box.prop(self, "dev_script_path")
            app_box.prop(self, "python_executable")
            if not self.dev_script_path:
                app_box.label(text="Set script path to enable launch button", icon='INFO')


def get_preferences():
    """Get Shot Library addon preferences"""
    addon = bpy.context.preferences.addons.get("SL_blender_plugin")
    if addon:
        return addon.preferences
    return None


# Classes to register
classes = [
    ShotLibraryPreferences,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
