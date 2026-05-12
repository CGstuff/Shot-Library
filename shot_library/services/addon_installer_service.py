"""
Blender Addon Installation Service

Handles automatic installation of the Shot Library addon to Blender.
Uses zip + script method to install addon and auto-configure preferences.

Note: Unlike Universal Library, Shot Library has NO storage_path to configure.
Shot Library is per-project - storage is assigned dynamically when opening folders.
Only exe_path is configured in addon preferences.
"""

import os
import sys
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class AddonInstallerService:
    """Service for installing Blender addon programmatically"""

    ADDON_FOLDER_NAME = "SL_blender_plugin"

    def __init__(self):
        """
        Initialize addon installer service

        Auto-detects project root based on file location or PyInstaller bundle
        """
        # Check if running as PyInstaller bundle
        if getattr(sys, 'frozen', False):
            # Running as compiled exe - use internal _MEIPASS path
            base_path = Path(sys._MEIPASS)
            self.addon_source_path = base_path / "SL_blender_plugin"
            self.install_script_path = base_path / "shot_library" / "services" / "utils" / "install_addon.py"
            self.exe_path = Path(sys.executable)  # Path to this exe
            logger.info(f"Running as bundled exe, using internal plugin path: {self.addon_source_path}")
        else:
            # Running in development mode - auto-detect root
            # This file is at: shot_library/services/addon_installer_service.py
            # Plugin is at: SL_blender_plugin/
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # Up 3 levels
            self.addon_source_path = project_root / "SL_blender_plugin"
            self.install_script_path = current_file.parent / "utils" / "install_addon.py"
            self.exe_path = project_root / "run.py"  # Dev mode uses script
            logger.info(f"Running in dev mode, using project plugin path: {self.addon_source_path}")

    def verify_blender_executable(self, blender_path: str) -> Tuple[bool, str, Optional[str]]:
        """
        Verify that the provided path is a valid Blender executable

        Args:
            blender_path: Path to blender.exe

        Returns:
            Tuple of (is_valid, message, version_string)
        """
        blender_path = Path(blender_path)

        if not blender_path.exists():
            return False, "Blender executable not found at specified path", None

        if not blender_path.is_file():
            return False, "Specified path is not a file", None

        if blender_path.name.lower() not in ['blender.exe', 'blender']:
            return False, "File does not appear to be a Blender executable", None

        try:
            result = subprocess.run(
                [str(blender_path), '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )

            version_output = result.stdout.strip()

            if "Blender" in version_output:
                version_line = version_output.split('\n')[0]
                logger.info(f"Found Blender: {version_line}")
                return True, f"Valid Blender installation: {version_line}", version_line
            else:
                return False, "Could not verify Blender version", None

        except subprocess.TimeoutExpired:
            return False, "Blender executable timed out during verification", None
        except Exception as e:
            return False, f"Error verifying Blender: {str(e)}", None

    def _create_addon_zip(self) -> Optional[Path]:
        """
        Create a temporary zip file of the addon folder.

        Returns:
            Path to the temporary zip file, or None if failed
        """
        if not self.addon_source_path.exists():
            logger.error(f"Addon source not found: {self.addon_source_path}")
            return None

        try:
            # Create temp directory for zip
            temp_dir = Path(tempfile.mkdtemp())
            zip_path = temp_dir / f"{self.ADDON_FOLDER_NAME}.zip"

            logger.info(f"Creating addon zip at: {zip_path}")

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_path in self.addon_source_path.rglob('*'):
                    # Skip __pycache__ and .pyc files
                    if '__pycache__' in file_path.parts or file_path.suffix == '.pyc':
                        continue

                    # Calculate relative path within the zip
                    # Files should be under SL_blender_plugin/ in the zip
                    rel_path = file_path.relative_to(self.addon_source_path.parent)
                    if file_path.is_file():
                        zf.write(file_path, rel_path)

            logger.info(f"Created addon zip: {zip_path} ({zip_path.stat().st_size} bytes)")
            return zip_path

        except Exception as e:
            logger.error(f"Failed to create addon zip: {e}")
            return None

    def install_addon_with_config(
        self,
        blender_path: str,
        auto_configure_exe: bool = True
    ) -> Tuple[bool, str]:
        """
        Install addon using zip + script method with auto-configuration.

        This method:
        1. Creates a zip of the addon folder
        2. Runs Blender with install_addon.py script
        3. Script installs addon and configures preferences
        4. Cleans up temporary files

        Note: Shot Library has no storage_path - only exe_path is configured.

        Args:
            blender_path: Path to blender.exe
            auto_configure_exe: Whether to auto-set exe path in addon prefs

        Returns:
            Tuple of (success, message)
        """
        # Verify Blender executable
        is_valid, verify_msg, version = self.verify_blender_executable(blender_path)
        if not is_valid:
            return False, verify_msg

        # Check addon source exists
        if not self.addon_source_path.exists():
            error_msg = f"Addon source not found at: {self.addon_source_path}\n\n"
            error_msg += "This usually means the Blender plugin was not bundled with the application.\n"
            error_msg += "If you're running from source, make sure 'SL_blender_plugin' folder exists."
            logger.error(error_msg)
            return False, error_msg

        # Check install script exists
        if not self.install_script_path.exists():
            error_msg = f"Install script not found at: {self.install_script_path}"
            logger.error(error_msg)
            return False, error_msg

        # Create zip
        zip_path = self._create_addon_zip()
        if not zip_path:
            return False, "Failed to create addon zip file"

        try:
            # Build command arguments
            # Shot Library: only exe_path, no storage_path
            exe_arg = str(self.exe_path) if auto_configure_exe else "none"

            cmd = [
                str(blender_path),
                '--background',
                '--python', str(self.install_script_path),
                '--',
                str(zip_path),
                exe_arg
            ]

            logger.info(f"Running Blender install command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            # Log output for debugging
            if result.stdout:
                logger.info(f"Blender stdout:\n{result.stdout}")
            if result.stderr:
                logger.warning(f"Blender stderr:\n{result.stderr}")

            if result.returncode != 0:
                error_msg = f"Blender install script failed (code {result.returncode})"
                if result.stderr:
                    error_msg += f"\n{result.stderr}"
                return False, error_msg

            # Build success message
            success_msg = (
                f"Successfully installed Shot Library addon!\n\n"
                f"Blender version: {version}\n"
            )
            if auto_configure_exe:
                success_msg += f"Desktop app: {self.exe_path}\n"

            success_msg += (
                f"\nThe addon is now enabled and configured.\n"
                f"Restart Blender to ensure all changes take effect."
            )

            return True, success_msg

        except subprocess.TimeoutExpired:
            return False, "Blender installation timed out after 60 seconds"
        except Exception as e:
            logger.error(f"Error during addon installation: {e}")
            return False, f"Installation error: {str(e)}"
        finally:
            # Cleanup temp zip
            if zip_path and zip_path.exists():
                try:
                    shutil.rmtree(zip_path.parent)
                    logger.info("Cleaned up temporary zip file")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp zip: {e}")


# Singleton instance
_installer_instance: Optional[AddonInstallerService] = None


def get_addon_installer() -> AddonInstallerService:
    """Get global AddonInstallerService singleton instance"""
    global _installer_instance
    if _installer_instance is None:
        _installer_instance = AddonInstallerService()
    return _installer_instance


__all__ = ['AddonInstallerService', 'get_addon_installer']
