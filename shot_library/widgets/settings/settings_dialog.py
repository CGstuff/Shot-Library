"""
SettingsDialog - Application settings dialog for Shot Library

Pattern: QDialog with sidebar list + stacked pages (Photoshop/Blender style)
"""

import logging

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QDialogButtonBox, QFrame,
    QWidget, QLabel, QGroupBox, QPushButton
)

from ...config import Config

logger = logging.getLogger(__name__)
from .blender_integration_tab import BlenderIntegrationTab
from .theme_tab import ThemeTab
from .library_tab import LibraryTab
from .maintenance_tab import MaintenanceTab
from .operation_mode_tab import OperationModeTab


class SettingsDialog(QDialog):
    """
    Main settings dialog with sidebar navigation

    Features:
    - Sidebar list of categories (Photoshop/Blender prefs style)
    - Stacked page area on the right
    - OK/Cancel/Apply buttons

    Usage:
        dialog = SettingsDialog(theme_manager, parent=main_window)
        if dialog.exec():
            # Settings were saved
            pass
    """

    # Signal emitted when schema changes (T153, T155)
    schema_changed = pyqtSignal(str)  # schema_id

    SIDEBAR_WIDTH = 180

    def __init__(self, theme_manager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager

        self.setWindowTitle(f"Settings - {Config.APP_NAME}")
        self.setModal(True)
        self.resize(820, 560)

        self._tabs = []  # list of (label, widget) for index lookup
        self._create_ui()

    def _create_ui(self):
        """Create UI layout"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sharp button style for dialog buttons
        button_style = """
            QPushButton {
                border-radius: 0px;
            }
        """

        # ---- Body: sidebar + stacked pages ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar list
        self._sidebar = QListWidget()
        self._sidebar.setObjectName("settingsSidebar")
        self._sidebar.setFixedWidth(self.SIDEBAR_WIDTH)
        self._sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self._sidebar.setUniformItemSizes(True)
        self._sidebar.setSpacing(0)
        self._sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.setObjectName("settingsStack")

        body.addWidget(self._sidebar)
        body.addWidget(self._stack, 1)

        # Instantiate tabs
        self.blender_tab = BlenderIntegrationTab(self.theme_manager, self)
        self.theme_tab = ThemeTab(self.theme_manager, self)
        self.library_tab = LibraryTab(self.theme_manager, self)
        self.maintenance_tab = MaintenanceTab(self.theme_manager, self)
        self.operation_mode_tab = OperationModeTab(self.theme_manager, self)
        self.schema_tab = self._build_schema_tab()

        for label, widget in [
            ("Blender Integration", self.blender_tab),
            ("Appearance",          self.theme_tab),
            ("Backup",              self.library_tab),
            ("Maintenance",         self.maintenance_tab),
            ("Operation Mode",      self.operation_mode_tab),
            ("Folder Schema",       self.schema_tab),
        ]:
            self._add_page(label, widget)

        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._sidebar.setCurrentRow(0)

        # Apply sidebar styling using the theme palette
        self._sidebar.setStyleSheet(self._sidebar_qss())

        # Restyle live if the user changes the theme inside this dialog
        try:
            self.theme_manager.theme_changed.connect(self._refresh_sidebar_style)
        except Exception:
            logger.warning("Failed to connect theme_changed signal", exc_info=True)

        body_widget = QFrame()
        body_widget.setLayout(body)
        outer.addWidget(body_widget, 1)

        # Load current schema info now that the schema tab is built
        self._refresh_schema_info()

        # ---- Button box ----
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        # Connect OK button directly to ensure save happens before close
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.clicked.connect(self._on_apply)
        button_box.accepted.connect(super().accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._on_apply
        )

        for button in button_box.buttons():
            button.setStyleSheet(button_style)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(12, 8, 12, 12)
        button_row.addStretch(1)
        button_row.addWidget(button_box)
        outer.addLayout(button_row)

    def _add_page(self, label: str, widget):
        """Add one (label, widget) pair to the sidebar + stack."""
        item = QListWidgetItem(label)
        item.setSizeHint(QSize(self.SIDEBAR_WIDTH, 32))
        self._sidebar.addItem(item)
        self._stack.addWidget(widget)
        self._tabs.append((label, widget))

    def _build_schema_tab(self) -> QWidget:
        """Create the Folder Schema configuration tab widget (T153)."""
        schema_tab = QWidget()
        layout = QVBoxLayout(schema_tab)

        # Description
        desc_label = QLabel(
            "Folder schemas define how Shot Library discovers shots in your studio's folder structure.\n\n"
            "Configure schemas to match your pipeline's naming conventions and folder hierarchy."
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Schema configuration group
        schema_group = QGroupBox("Folder Schema Configuration")
        schema_layout = QVBoxLayout()

        # Info about current schema
        self._schema_info_label = QLabel("Loading schema information...")
        schema_layout.addWidget(self._schema_info_label)

        # Button to open full schema dialog
        configure_btn = QPushButton("Configure Folder Schemas...")
        configure_btn.setToolTip("Open the full schema configuration dialog")
        configure_btn.clicked.connect(self._open_schema_config)
        schema_layout.addWidget(configure_btn)

        schema_group.setLayout(schema_layout)
        layout.addWidget(schema_group)

        layout.addStretch()
        return schema_tab

    def _refresh_schema_info(self):
        """Refresh the current schema information display."""
        try:
            from ...services.database_service import get_database_service
            from ...services.database.folder_schemas import FolderSchemaRepository

            db_service = get_database_service()
            if db_service and db_service._connection:
                repo = FolderSchemaRepository(db_service._connection)
                active = repo.get_active()
                total = repo.get_count()

                if active:
                    self._schema_info_label.setText(
                        f"Active Schema: {active['name']}\n"
                        f"Total Schemas: {total}"
                    )
                else:
                    self._schema_info_label.setText(
                        f"No active schema selected.\n"
                        f"Total Schemas: {total}"
                    )
            else:
                self._schema_info_label.setText("Database not connected")
        except Exception as e:
            self._schema_info_label.setText(f"Error loading schema info: {e}")

    def _open_schema_config(self):
        """Open the full schema configuration dialog (T153)."""
        from ...services.database_service import get_database_service
        from ..dialogs.schema_config_dialog import SchemaConfigDialog

        db_service = get_database_service()
        dialog = SchemaConfigDialog(db_service=db_service, parent=self)

        # Forward schema change signal (T155)
        dialog.schema_changed.connect(self.schema_changed.emit)

        dialog.exec()

        # Refresh info after dialog closes
        self._refresh_schema_info()

    def _sidebar_qss(self) -> str:
        """Sidebar styling — pulls colors from the active theme palette."""
        theme = None
        try:
            theme = self.theme_manager.get_current_theme()
        except Exception:
            pass

        if theme is None:
            sidebar_bg = "#1a1a1a"
            border = "#404040"
            text = "#e0e0e0"
            hover_bg = "#2d2d2d"
            sel_bg = "#3A8FB7"
            sel_text = "#ffffff"
        else:
            p = theme.palette
            sidebar_bg = p.background_secondary
            border = p.border
            text = p.text_primary
            hover_bg = p.list_item_hover
            sel_bg = p.list_item_selected
            sel_text = p.selection_text

        return f"""
        QListWidget#settingsSidebar {{
            background: {sidebar_bg};
            border: none;
            border-right: 1px solid {border};
            outline: 0;
            padding-top: 6px;
            color: {text};
        }}
        QListWidget#settingsSidebar::item {{
            padding: 6px 14px;
            border: none;
            color: {text};
        }}
        QListWidget#settingsSidebar::item:hover {{
            background: {hover_bg};
        }}
        QListWidget#settingsSidebar::item:selected {{
            background: {sel_bg};
            color: {sel_text};
        }}
        """

    def _refresh_sidebar_style(self, *_):
        """Re-apply the sidebar QSS when the active theme changes."""
        self._sidebar.setStyleSheet(self._sidebar_qss())

    def _on_apply(self):
        """Handle Apply button - save settings without closing dialog"""
        self.blender_tab.save_settings()
        self.theme_tab.save_settings()
        self.operation_mode_tab.save_settings()



__all__ = ['SettingsDialog']
