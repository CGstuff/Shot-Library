"""
Blender Integration Tab for Shot Library

Provides UI for:
- Configuring Blender executable path
- Verifying Blender installation
- Installing Shot Library addon to Blender
- Auto-configuring addon preferences (exe_path only - no storage for Shot Library)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt

from ...config import Config
from ...services.addon_installer_service import get_addon_installer


class BlenderIntegrationTab(QWidget):
    """
    Blender integration settings tab for Shot Library.

    Allows users to:
    - Set and verify Blender executable path
    - Install the Shot Library addon to Blender
    - Auto-configure desktop app launch settings in addon
    """

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._addon_installer = get_addon_installer()
        self._blender_version = None
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Create the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Sharp button style
        self._button_style = """
            QPushButton {
                border-radius: 0px;
            }
        """

        # Blender Executable Section
        layout.addWidget(self._create_blender_path_section())

        # Addon Installation Section
        layout.addWidget(self._create_addon_install_section())

        # Info Section
        layout.addWidget(self._create_info_section())

        layout.addStretch()

    def _create_blender_path_section(self):
        """Create Blender executable path configuration section."""
        group = QGroupBox("Blender Executable")
        group_layout = QVBoxLayout(group)

        # Description
        desc = QLabel(
            "Set the path to your Blender installation. "
            "This is required to install the Shot Library addon."
        )
        desc.setWordWrap(True)
        group_layout.addWidget(desc)

        group_layout.addSpacing(5)

        # Path input row
        path_row = QHBoxLayout()

        self._blender_path_edit = QLineEdit()
        self._blender_path_edit.setPlaceholderText("Path to blender.exe...")
        path_row.addWidget(self._blender_path_edit, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.setStyleSheet(self._button_style)
        browse_btn.clicked.connect(self._browse_blender)
        path_row.addWidget(browse_btn)

        group_layout.addLayout(path_row)

        group_layout.addSpacing(5)

        # Verify button and status
        verify_row = QHBoxLayout()

        verify_btn = QPushButton("Verify Blender")
        verify_btn.setStyleSheet(self._button_style)
        verify_btn.clicked.connect(self._verify_blender)
        verify_row.addWidget(verify_btn)

        verify_row.addStretch()

        group_layout.addLayout(verify_row)

        # Status label
        self._verify_status_label = QLabel("")
        self._verify_status_label.setWordWrap(True)
        group_layout.addWidget(self._verify_status_label)

        return group

    def _create_addon_install_section(self):
        """Create addon installation section."""
        group = QGroupBox("Addon Installation")
        group_layout = QVBoxLayout(group)

        # Description
        desc = QLabel(
            "Install the Shot Library addon to Blender. "
            "This will also configure the addon to launch this desktop app."
        )
        desc.setWordWrap(True)
        group_layout.addWidget(desc)

        group_layout.addSpacing(5)

        # Install button
        self._install_btn = QPushButton("Install Addon to Blender")
        self._install_btn.setStyleSheet(self._button_style)
        self._install_btn.clicked.connect(self._install_addon)
        group_layout.addWidget(self._install_btn)

        # Status label
        self._install_status_label = QLabel("")
        self._install_status_label.setWordWrap(True)
        group_layout.addWidget(self._install_status_label)

        return group

    def _create_info_section(self):
        """Create informational section."""
        group = QGroupBox("About Shot Library Addon")
        group_layout = QVBoxLayout(group)

        info_text = (
            "The Shot Library Blender addon provides:\n\n"
            "- Playblast capture from viewport\n"
            "- Lookdev render capture\n"
            "- Quick launch button for this desktop app\n\n"
            "Note: Shot Library is per-project. When you install the addon, "
            "only the desktop app path is configured. Project folders are "
            "selected dynamically when you open Shot Library."
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        self._apply_secondary_style(info_label)
        group_layout.addWidget(info_label)

        return group

    def _apply_secondary_style(self, label):
        """Apply secondary text styling to a label."""
        if self._theme_manager:
            current_theme = self._theme_manager.get_current_theme()
            if current_theme:
                palette = current_theme.palette
                label.setStyleSheet(
                    f"font-style: italic; color: {palette.text_secondary};"
                )
                return
        label.setStyleSheet("font-style: italic; color: gray;")

    def _load_settings(self):
        """Load saved settings."""
        blender_path = Config.get_blender_path()
        if blender_path:
            self._blender_path_edit.setText(str(blender_path))

    def _browse_blender(self):
        """Open file dialog to browse for Blender executable."""
        current_path = self._blender_path_edit.text()

        if current_path:
            from pathlib import Path
            start_dir = str(Path(current_path).parent)
        else:
            start_dir = ""

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Blender Executable",
            start_dir,
            "Blender (blender.exe blender);;All Files (*)"
        )

        if file_path:
            self._blender_path_edit.setText(file_path)
            # Auto-verify after selection
            self._verify_blender()

    def _verify_blender(self):
        """Verify the Blender executable."""
        blender_path = self._blender_path_edit.text().strip()

        if not blender_path:
            self._verify_status_label.setText("Please enter a Blender path first.")
            self._verify_status_label.setStyleSheet("color: orange;")
            self._blender_version = None
            return

        is_valid, message, version = self._addon_installer.verify_blender_executable(blender_path)

        if is_valid:
            self._verify_status_label.setText(f"Verified: {version}")
            self._verify_status_label.setStyleSheet("color: green;")
            self._blender_version = version
        else:
            self._verify_status_label.setText(f"Invalid: {message}")
            self._verify_status_label.setStyleSheet("color: red;")
            self._blender_version = None

    def _install_addon(self):
        """Install the addon to Blender."""
        blender_path = self._blender_path_edit.text().strip()

        if not blender_path:
            QMessageBox.warning(
                self,
                "No Blender Path",
                "Please set the Blender executable path first."
            )
            return

        # Verify first if not already verified
        if not self._blender_version:
            is_valid, message, version = self._addon_installer.verify_blender_executable(blender_path)
            if not is_valid:
                QMessageBox.warning(
                    self,
                    "Invalid Blender",
                    f"Could not verify Blender installation:\n{message}"
                )
                return
            self._blender_version = version

        # Confirm installation
        reply = QMessageBox.question(
            self,
            "Install Addon",
            f"Install Shot Library addon to Blender?\n\n"
            f"Blender: {self._blender_version}\n\n"
            f"This will:\n"
            f"- Create and install the addon zip\n"
            f"- Enable the addon\n"
            f"- Configure desktop app launch path",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Update status
        self._install_status_label.setText("Installing addon...")
        self._install_status_label.setStyleSheet("color: blue;")
        self._install_btn.setEnabled(False)

        # Process events to show status
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        # Perform installation
        success, message = self._addon_installer.install_addon_with_config(
            blender_path,
            auto_configure_exe=True
        )

        self._install_btn.setEnabled(True)

        if success:
            self._install_status_label.setText("Addon installed successfully!")
            self._install_status_label.setStyleSheet("color: green;")
            QMessageBox.information(
                self,
                "Installation Complete",
                message
            )
        else:
            self._install_status_label.setText(f"Installation failed: {message}")
            self._install_status_label.setStyleSheet("color: red;")
            QMessageBox.warning(
                self,
                "Installation Failed",
                message
            )

    def save_settings(self):
        """Save settings to config."""
        blender_path = self._blender_path_edit.text().strip()
        if blender_path:
            Config.set_blender_path(blender_path)


__all__ = ['BlenderIntegrationTab']
