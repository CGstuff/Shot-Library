"""
Shot Library Addon Installer Script

This script is executed by Blender in background mode to:
1. Install the addon from a zip file
2. Enable the addon
3. Configure the exe_path in addon preferences

Note: Shot Library has NO storage_path to configure (per-project design).
Only exe_path is set to allow launching the desktop app from Blender.

Usage:
    blender --background --python install_addon.py -- <zip_path> [exe_path]
"""

import bpy
import sys
import os
import addon_utils


def install_addon(zip_path, exe_path=None):
    print(f"Starting installation of addon from: {zip_path}")

    if not os.path.exists(zip_path):
        print(f"Error: Zip file not found at {zip_path}")
        return False

    try:
        # Install the addon
        print("Installing addon...")
        bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)

        # The addon name is the folder name inside the zip
        addon_name = "SL_blender_plugin"

        # Enable the addon
        print(f"Enabling addon '{addon_name}'...")
        addon_utils.enable(addon_name, default_set=True)

        # Get preferences object
        prefs = None
        if addon_name in bpy.context.preferences.addons:
            prefs = bpy.context.preferences.addons[addon_name].preferences
        else:
            print(f"Warning: Addon '{addon_name}' not found in preferences after enabling.")

        if prefs:
            # Configure executable path if provided
            # Shot Library: only exe_path, no storage_path
            if exe_path and exe_path.lower() != "none":
                print(f"Configuring executable path: {exe_path}")
                try:
                    prefs.app_executable_path = exe_path
                    # Also force mode to PRODUCTION
                    prefs.launch_mode = 'PRODUCTION'
                    print("Executable path and PRODUCTION mode set successfully.")
                except Exception as e:
                    print(f"Error setting executable path: {e}")

        # Save preferences to make it persistent
        print("Saving user preferences...")
        bpy.ops.wm.save_userpref()

        print("Shot Library addon installed and enabled successfully.")
        return True

    except Exception as e:
        print(f"Error during installation: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Get arguments after "--"
    try:
        args_idx = sys.argv.index("--")
        args = sys.argv[args_idx + 1:]

        if not args:
            print("Error: No zip path provided")
            sys.exit(1)

        zip_path = args[0]

        # Check for optional exe_path argument
        exe_path = None
        if len(args) > 1:
            exe_path = args[1]

        success = install_addon(zip_path, exe_path)

        if not success:
            sys.exit(1)

    except ValueError:
        print("Error: Arguments not found. Use '--' to separate arguments.")
        sys.exit(1)
