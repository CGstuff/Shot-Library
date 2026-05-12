"""
Shot Library Launch App Operator

Operator to launch the Shot Library desktop application from within Blender.
Supports both production (exe) and development (Python script) modes.
"""

import os
import subprocess
import bpy
from bpy.types import Operator

from ..preferences.SL_preferences import get_preferences
from ..utils.logger import get_logger

logger = get_logger()


class SHOTLIB_OT_launch_desktop_app(Operator):
    """Launch the Shot Library desktop application"""
    bl_idname = "shotlib.launch_desktop_app"
    bl_label = "Launch Shot Library"
    bl_description = "Open the Shot Library desktop application"
    bl_options = {'REGISTER'}

    def execute(self, context):
        prefs = get_preferences()
        if not prefs:
            self.report({'ERROR'}, "Could not access Shot Library preferences")
            return {'CANCELLED'}

        launch_mode = prefs.launch_mode

        if launch_mode == 'PRODUCTION':
            return self._launch_production(prefs)
        else:
            return self._launch_development(prefs)

    def _launch_production(self, prefs):
        """Launch the compiled executable."""
        exe_path = prefs.app_executable_path

        if not exe_path:
            self.report({'ERROR'}, "Desktop app executable path not configured. "
                       "Set it in addon preferences.")
            return {'CANCELLED'}

        if not os.path.exists(exe_path):
            self.report({'ERROR'}, f"Executable not found: {exe_path}")
            return {'CANCELLED'}

        try:
            logger.info(f"Launching Shot Library (Production): {exe_path}")

            # Launch detached from Blender
            if os.name == 'nt':  # Windows
                # Use CREATE_NEW_PROCESS_GROUP to detach from Blender
                subprocess.Popen(
                    [exe_path],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
            else:  # Linux/Mac
                subprocess.Popen(
                    [exe_path],
                    start_new_session=True,
                    close_fds=True
                )

            self.report({'INFO'}, "Shot Library launched")
            return {'FINISHED'}

        except Exception as e:
            logger.error(f"Failed to launch Shot Library: {e}")
            self.report({'ERROR'}, f"Failed to launch: {str(e)}")
            return {'CANCELLED'}

    def _launch_development(self, prefs):
        """Launch via Python script (development mode)."""
        script_path = prefs.dev_script_path
        python_exe = prefs.python_executable or "python"

        if not script_path:
            self.report({'ERROR'}, "Development script path not configured. "
                       "Set it in addon preferences.")
            return {'CANCELLED'}

        if not os.path.exists(script_path):
            self.report({'ERROR'}, f"Script not found: {script_path}")
            return {'CANCELLED'}

        try:
            logger.info(f"Launching Shot Library (Development): {python_exe} {script_path}")

            # Get the directory containing the script
            script_dir = os.path.dirname(script_path)

            # Launch detached from Blender
            if os.name == 'nt':  # Windows
                subprocess.Popen(
                    [python_exe, script_path],
                    cwd=script_dir,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
            else:  # Linux/Mac
                subprocess.Popen(
                    [python_exe, script_path],
                    cwd=script_dir,
                    start_new_session=True,
                    close_fds=True
                )

            self.report({'INFO'}, "Shot Library launched (dev mode)")
            return {'FINISHED'}

        except Exception as e:
            logger.error(f"Failed to launch Shot Library: {e}")
            self.report({'ERROR'}, f"Failed to launch: {str(e)}")
            return {'CANCELLED'}


# Classes to register
classes = [
    SHOTLIB_OT_launch_desktop_app,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
