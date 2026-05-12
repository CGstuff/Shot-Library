"""
Schema Configuration Dialog

Dialog for configuring folder schemas that define how studio folder structures
map to shots. Allows pipeline TDs to create, edit, and test schema configurations.

Tasks: T134-T140, T144, T145, T154
"""

import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QFormLayout, QListWidget,
    QListWidgetItem, QTextEdit, QMessageBox, QFileDialog,
    QTabWidget, QWidget, QSplitter, QFrame, QScrollArea,
    QSpinBox, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from ...themes.fonts import Fonts, get_font_stylesheet
from PyQt6.QtGui import QFont

from ...core.folder_schema_parser import (
    FolderSchemaParser, SchemaConfig, HierarchyLevel, ParsedPath, SCHEMA_PRESETS
)


def _build_level_examples() -> Dict[str, str]:
    """Build a lookup of pattern/folder_contains -> examples from all schema presets."""
    lookup = {}
    for preset in SCHEMA_PRESETS.values():
        for level in preset.get('hierarchy_levels', []):
            examples = level.get('examples', '')
            if not examples:
                continue
            pattern = level.get('pattern', '')
            if pattern:
                lookup[('pattern', pattern)] = examples
            folder_contains = level.get('folder_contains', '')
            if folder_contains:
                lookup[('contains', level.get('level', ''), folder_contains)] = examples
    return lookup

_LEVEL_EXAMPLES = _build_level_examples()


# Cheat-sheet shown under each hierarchy row so users don't have to guess regex syntax.
# Format: level_name -> list of (regex_pattern, what_it_matches) tuples.
# These are common conventions; the user can still type anything they want.
_LEVEL_PATTERN_CHEATSHEET: Dict[str, List[tuple]] = {
    'show': [
        (r'^[A-Z]{3}$',                       'three-letter codes like ARC, BTL'),
        (r'^[A-Z][A-Za-z0-9_]*$',             'CamelCase names like MyShow, Project_X'),
    ],
    'episode': [
        (r'^EP\d{2}$',                        'EP01, EP02 ... EP99'),
        (r'^EP[_\-]?\d+$',                    'EP01, EP_02, EP-12'),
        (r'^(?P<episode>\d+)$',               'plain digits: 01, 02, 100'),
    ],
    'sequence': [
        (r'^SQ\d{3}$',                        'SQ005, SQ120'),
        (r'^(SQ|SEQ)\d{3,4}$',                'SQ005 or SEQ0100'),
        (r'^(SQ|SEQ|sq)_?\d{3,4}$',           'SQ005, SEQ_0100, sq005'),
    ],
    'scene': [
        (r'^SC\d{3}$',                        'SC001, SC100'),
        (r'^(SC|SCENE)_?\d+$',                'SC01, SCENE_02'),
    ],
    'shot': [
        (r'^SH\d{4}$',                        'SH0010, SH0020 (5-leeway spacing)'),
        (r'^(SH|SHOT|sh)_?\d{3,4}$',          'SH010, SHOT_0020, sh005'),
        (r'^[\w]+$',                          'any word characters (catch-all)'),
    ],
}


def _format_cheatsheet(level: str) -> str:
    """Build a 'Common patterns:' helper string for the given level type."""
    entries = _LEVEL_PATTERN_CHEATSHEET.get(level)
    if not entries:
        return ''
    lines = ['Common patterns:']
    for pattern, matches in entries:
        lines.append(f'  {pattern}    →  {matches}')
    return '\n'.join(lines)


class HierarchyLevelWidget(QFrame):
    """Widget for editing a single hierarchy level."""

    level_changed = pyqtSignal()
    remove_requested = pyqtSignal(object)  # Emits self

    LEVEL_TYPES = ['show', 'episode', 'sequence', 'scene', 'shot']

    def __init__(self, level_data: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self._setup_ui()

        if level_data:
            self._load_data(level_data)

    def _setup_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 4, 8, 4)
        outer_layout.setSpacing(2)

        # Top row: controls
        row = QHBoxLayout()
        row.setSpacing(8)

        # Level type dropdown
        self._level_combo = QComboBox()
        self._level_combo.addItems(self.LEVEL_TYPES)
        self._level_combo.setMinimumWidth(100)
        self._level_combo.currentTextChanged.connect(self._on_changed)
        row.addWidget(self._level_combo)

        # Pattern input
        pattern_label = QLabel("Pattern:")
        row.addWidget(pattern_label)

        self._pattern_input = QLineEdit()
        self._pattern_input.setPlaceholderText("Regex pattern (e.g., ^EP\\d{2}$)")
        self._pattern_input.setMinimumWidth(200)
        self._pattern_input.textChanged.connect(self._on_changed)
        row.addWidget(self._pattern_input, 1)

        # OR folder_contains
        or_label = QLabel("OR contains:")
        row.addWidget(or_label)

        self._folder_contains = QLineEdit()
        self._folder_contains.setPlaceholderText(".blend")
        self._folder_contains.setMaximumWidth(80)
        self._folder_contains.textChanged.connect(self._on_changed)
        row.addWidget(self._folder_contains)

        # Remove button
        remove_btn = QPushButton("X")
        remove_btn.setMaximumWidth(30)
        remove_btn.setToolTip("Remove this level")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        row.addWidget(remove_btn)

        outer_layout.addLayout(row)

        # Bottom row: examples label (matches a preset pattern exactly)
        self._examples_label = QLabel("")
        self._examples_label.setStyleSheet("color: #888; font-size: 11px; padding-left: 110px;")
        self._examples_label.setVisible(False)
        outer_layout.addWidget(self._examples_label)

        # Cheat-sheet shown for the currently-selected level type so users
        # don't have to guess regex syntax. Always visible (when there's content).
        self._cheatsheet_label = QLabel("")
        self._cheatsheet_label.setStyleSheet(
            "color: #888; font-size: 11px; padding-left: 110px; "
            "font-family: Consolas, 'Courier New', monospace;"
        )
        self._cheatsheet_label.setVisible(False)
        outer_layout.addWidget(self._cheatsheet_label)

        # Show cheat-sheet for the default level on first paint.
        self._update_cheatsheet()

    def _load_data(self, data: Dict[str, Any]):
        """Load hierarchy level data."""
        level = data.get('level', 'shot')
        if level in self.LEVEL_TYPES:
            self._level_combo.setCurrentText(level)

        pattern = data.get('pattern', '')
        self._pattern_input.setText(pattern or '')

        folder_contains = data.get('folder_contains', '')
        self._folder_contains.setText(folder_contains or '')

        self._update_examples()

    def _on_changed(self):
        """Emit change signal."""
        self._update_examples()
        self._update_cheatsheet()
        self.level_changed.emit()

    def _update_cheatsheet(self):
        """Show common regex patterns for the selected level type."""
        level = self._level_combo.currentText()
        text = _format_cheatsheet(level)
        if text:
            self._cheatsheet_label.setText(text)
            self._cheatsheet_label.setVisible(True)
        else:
            self._cheatsheet_label.setVisible(False)

    def _update_examples(self):
        """Show examples if the current pattern/contains matches a known preset."""
        pattern = self._pattern_input.text().strip()
        contains = self._folder_contains.text().strip()
        level = self._level_combo.currentText()

        examples = ''
        if pattern:
            examples = _LEVEL_EXAMPLES.get(('pattern', pattern), '')
        if not examples and contains:
            examples = _LEVEL_EXAMPLES.get(('contains', level, contains), '')

        if examples:
            self._examples_label.setText(f"e.g. {examples}")
            self._examples_label.setVisible(True)
        else:
            self._examples_label.setVisible(False)

    def get_data(self) -> Dict[str, Any]:
        """Get hierarchy level data."""
        data = {'level': self._level_combo.currentText()}

        pattern = self._pattern_input.text().strip()
        if pattern:
            data['pattern'] = pattern

        folder_contains = self._folder_contains.text().strip()
        if folder_contains:
            data['folder_contains'] = folder_contains

        return data

    def validate(self) -> List[str]:
        """Validate this level configuration."""
        errors = []
        pattern = self._pattern_input.text().strip()
        folder_contains = self._folder_contains.text().strip()

        # Must have pattern or folder_contains
        if not pattern and not folder_contains:
            errors.append(f"Level '{self._level_combo.currentText()}' needs a pattern or folder_contains")

        # Validate regex if provided
        if pattern:
            try:
                re.compile(pattern)
            except re.error as e:
                errors.append(f"Invalid regex for '{self._level_combo.currentText()}': {e}")

        return errors


class SchemaConfigDialog(QDialog):
    """
    Dialog for configuring folder schemas.

    Features:
    - Preset selection (T139)
    - Hierarchy level editor (T135)
    - Regex pattern editor with validation (T136)
    - Blend file pattern editor (T137)
    - Playblast folder/pattern configuration (T138)
    - Test/validate with sample path (T140)
    - Import/export to JSON (T144, T145)
    - Validation error display (T154)
    """

    schema_changed = pyqtSignal(str)  # Emits schema ID when active schema changes

    def __init__(self, db_service=None, parent=None):
        super().__init__(parent)
        self._db_service = db_service
        self._current_schema_id: Optional[str] = None
        self._hierarchy_widgets: List[HierarchyLevelWidget] = []
        self._is_dirty = False

        self.setWindowTitle("Folder Schema Configuration")
        self.setModal(True)
        self.resize(800, 700)

        self._setup_ui()
        self._connect_signals()
        self._load_schemas()

    def _setup_ui(self):
        """Create UI layout."""
        main_layout = QVBoxLayout(self)

        # Schema selector
        selector_group = QGroupBox("Schema")
        selector_layout = QHBoxLayout()

        self._schema_combo = QComboBox()
        self._schema_combo.setMinimumWidth(200)
        selector_layout.addWidget(self._schema_combo, 1)

        self._new_btn = QPushButton("New")
        self._new_btn.setToolTip("Create a new schema")
        selector_layout.addWidget(self._new_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setToolTip("Delete selected schema")
        selector_layout.addWidget(self._delete_btn)

        self._preset_combo = QComboBox()
        self._preset_combo.addItem("Load Preset...")
        self._preset_combo.addItems(list(SCHEMA_PRESETS.keys()))
        self._preset_combo.setToolTip("Load a built-in preset")
        selector_layout.addWidget(self._preset_combo)

        selector_group.setLayout(selector_layout)
        main_layout.addWidget(selector_group)

        # Tab widget for configuration
        tabs = QTabWidget()

        # Basic tab
        basic_tab = QWidget()
        basic_layout = QVBoxLayout(basic_tab)

        # Schema name
        name_layout = QFormLayout()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("My Studio Schema")
        name_layout.addRow("Schema Name:", self._name_input)
        basic_layout.addLayout(name_layout)

        # Hierarchy levels (T135)
        hierarchy_group = QGroupBox("Hierarchy Levels")
        hierarchy_layout = QVBoxLayout()

        hierarchy_desc = QLabel(
            "Define folder levels from root to shot. Each level can use a regex pattern "
            "or specify a required file extension."
        )
        hierarchy_desc.setWordWrap(True)
        hierarchy_desc.setStyleSheet("color: gray; font-size: 11px;")
        hierarchy_layout.addWidget(hierarchy_desc)

        # Scroll area for levels
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(150)

        self._levels_container = QWidget()
        self._levels_layout = QVBoxLayout(self._levels_container)
        self._levels_layout.setContentsMargins(0, 0, 0, 0)
        self._levels_layout.setSpacing(4)
        self._levels_layout.addStretch()

        scroll.setWidget(self._levels_container)
        hierarchy_layout.addWidget(scroll)

        # Add level button
        add_level_btn = QPushButton("+ Add Level")
        add_level_btn.clicked.connect(self._add_hierarchy_level)
        hierarchy_layout.addWidget(add_level_btn)

        hierarchy_group.setLayout(hierarchy_layout)
        basic_layout.addWidget(hierarchy_group)

        tabs.addTab(basic_tab, "Structure")

        # Patterns tab (T136, T137, T138)
        patterns_tab = QWidget()
        patterns_layout = QVBoxLayout(patterns_tab)

        # Blend file patterns (T137)
        blend_group = QGroupBox("Blend File Patterns")
        blend_layout = QVBoxLayout()

        blend_desc = QLabel(
            "Regex patterns to match .blend filenames. Must include (?P<shot>...) named group. "
            "Optionally include (?P<version>...) for version extraction."
        )
        blend_desc.setWordWrap(True)
        blend_desc.setStyleSheet("color: gray; font-size: 11px;")
        blend_layout.addWidget(blend_desc)

        self._blend_patterns_edit = QTextEdit()
        self._blend_patterns_edit.setPlaceholderText(
            "One pattern per line:\n"
            "^(?P<shot>[\\w]+)_v(?P<version>\\d{3})\\.blend$\n"
            "^(?P<shot>[\\w]+)\\.blend$"
        )
        self._blend_patterns_edit.setMaximumHeight(100)
        blend_layout.addWidget(self._blend_patterns_edit)

        blend_group.setLayout(blend_layout)
        patterns_layout.addWidget(blend_group)

        # Playblast configuration (T138)
        playblast_group = QGroupBox("Playblast Configuration")
        playblast_layout = QFormLayout()

        self._playblast_folder_input = QLineEdit()
        self._playblast_folder_input.setText("PlayBlast")
        self._playblast_folder_input.setPlaceholderText("PlayBlast")
        playblast_layout.addRow("Playblast Folder:", self._playblast_folder_input)

        self._playblast_pattern_input = QLineEdit()
        self._playblast_pattern_input.setText(r"^v(?P<version>\d{3})\.mp4$")
        self._playblast_pattern_input.setPlaceholderText(r"^v(?P<version>\d{3})\.mp4$")
        playblast_layout.addRow("Playblast Pattern:", self._playblast_pattern_input)

        playblast_desc = QLabel(
            "Playblast pattern must include (?P<version>...) named group for version extraction."
        )
        playblast_desc.setWordWrap(True)
        playblast_desc.setStyleSheet("color: gray; font-size: 11px;")
        playblast_layout.addRow("", playblast_desc)

        playblast_group.setLayout(playblast_layout)
        patterns_layout.addWidget(playblast_group)

        patterns_layout.addStretch()
        tabs.addTab(patterns_tab, "Patterns")

        # Test tab (T140)
        test_tab = QWidget()
        test_layout = QVBoxLayout(test_tab)

        test_desc = QLabel(
            "Test your schema by entering a sample path. The parser will show what it extracts."
        )
        test_desc.setWordWrap(True)
        test_layout.addWidget(test_desc)

        # Sample path input
        path_layout = QHBoxLayout()
        self._test_path_input = QLineEdit()
        self._test_path_input.setPlaceholderText("C:\\Projects\\MyShow\\EP01\\SQ010\\SH_0100\\SH_0100_v003.blend")
        path_layout.addWidget(self._test_path_input, 1)

        self._test_btn = QPushButton("Test")
        self._test_btn.clicked.connect(self._test_schema)
        path_layout.addWidget(self._test_btn)

        self._browse_test_btn = QPushButton("Browse...")
        self._browse_test_btn.clicked.connect(self._browse_test_path)
        path_layout.addWidget(self._browse_test_btn)

        test_layout.addLayout(path_layout)

        # Test results
        results_group = QGroupBox("Parse Results")
        results_layout = QVBoxLayout()

        self._test_results = QTextEdit()
        self._test_results.setReadOnly(True)
        self._test_results.setMaximumHeight(200)
        results_layout.addWidget(self._test_results)

        results_group.setLayout(results_layout)
        test_layout.addWidget(results_group)

        test_layout.addStretch()
        tabs.addTab(test_tab, "Test")

        main_layout.addWidget(tabs)

        # Validation errors (T154)
        self._errors_group = QGroupBox("Validation Errors")
        errors_layout = QVBoxLayout()

        self._errors_list = QListWidget()
        self._errors_list.setMaximumHeight(80)
        errors_layout.addWidget(self._errors_list)

        self._errors_group.setLayout(errors_layout)
        self._errors_group.hide()  # Hidden until there are errors
        main_layout.addWidget(self._errors_group)

        # Button bar
        button_layout = QHBoxLayout()

        self._import_btn = QPushButton("Import...")
        self._import_btn.setToolTip("Import schema from JSON file")
        self._import_btn.clicked.connect(self._import_schema)
        button_layout.addWidget(self._import_btn)

        self._export_btn = QPushButton("Export...")
        self._export_btn.setToolTip("Export schema to JSON file")
        self._export_btn.clicked.connect(self._export_schema)
        button_layout.addWidget(self._export_btn)

        button_layout.addStretch()

        self._set_active_btn = QPushButton("Set Active")
        self._set_active_btn.setToolTip("Set this schema as the active schema for shot discovery")
        self._set_active_btn.clicked.connect(self._set_active_schema)
        button_layout.addWidget(self._set_active_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._save_schema)
        button_layout.addWidget(self._save_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self._on_close)
        button_layout.addWidget(self._close_btn)

        main_layout.addLayout(button_layout)

    def _connect_signals(self):
        """Connect widget signals."""
        self._schema_combo.currentIndexChanged.connect(self._on_schema_selected)
        self._new_btn.clicked.connect(self._create_new_schema)
        self._delete_btn.clicked.connect(self._delete_schema)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)

        # Track changes
        self._name_input.textChanged.connect(self._mark_dirty)
        self._blend_patterns_edit.textChanged.connect(self._mark_dirty)
        self._playblast_folder_input.textChanged.connect(self._mark_dirty)
        self._playblast_pattern_input.textChanged.connect(self._mark_dirty)

    def _load_schemas(self):
        """Load schemas from database into combo box."""
        self._schema_combo.clear()

        if not self._db_service:
            self._schema_combo.addItem("No database connection", None)
            return

        try:
            from ...services.database.folder_schemas import FolderSchemaRepository
            repo = FolderSchemaRepository(self._db_service._connection)
            schemas = repo.get_all()

            for schema in schemas:
                name = schema['name']
                if schema['is_active']:
                    name = f"* {name}"  # Mark active schema
                self._schema_combo.addItem(name, schema['id'])

            # Select active schema
            active = repo.get_active()
            if active:
                for i in range(self._schema_combo.count()):
                    if self._schema_combo.itemData(i) == active['id']:
                        self._schema_combo.setCurrentIndex(i)
                        break

        except Exception as e:
            self._schema_combo.addItem("Error loading schemas", None)

    def _on_schema_selected(self, index: int):
        """Handle schema selection."""
        if index < 0:
            return

        if self._is_dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Discard them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        schema_id = self._schema_combo.itemData(index)
        if schema_id:
            self._load_schema(schema_id)

    def _load_schema(self, schema_id: str):
        """Load a schema by ID."""
        if not self._db_service:
            return

        try:
            from ...services.database.folder_schemas import FolderSchemaRepository
            repo = FolderSchemaRepository(self._db_service._connection)
            schema = repo.get_by_id(schema_id)

            if schema:
                self._current_schema_id = schema_id
                self._populate_form(schema)
                self._is_dirty = False

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load schema: {e}")

    def _populate_form(self, schema: Dict[str, Any]):
        """Populate form with schema data."""
        config = schema.get('config', {})

        # Name
        self._name_input.setText(schema.get('name', ''))

        # Clear hierarchy levels
        for widget in self._hierarchy_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._hierarchy_widgets.clear()

        # Add hierarchy levels
        levels = config.get('hierarchy_levels', [])
        for level_data in levels:
            self._add_hierarchy_level(level_data)

        # Blend patterns
        blend_patterns = config.get('blend_file_patterns', [])
        self._blend_patterns_edit.setText('\n'.join(blend_patterns))

        # Playblast config
        self._playblast_folder_input.setText(config.get('playblast_folder', 'PlayBlast'))
        self._playblast_pattern_input.setText(
            config.get('playblast_pattern', r'^v(?P<version>\d{3})\.mp4$')
        )

        # Clear validation errors
        self._errors_list.clear()
        self._errors_group.hide()

    def _add_hierarchy_level(self, level_data: Optional[Dict[str, Any]] = None):
        """Add a hierarchy level widget."""
        widget = HierarchyLevelWidget(level_data)
        widget.level_changed.connect(self._mark_dirty)
        widget.remove_requested.connect(self._remove_hierarchy_level)

        self._hierarchy_widgets.append(widget)

        # Insert before the stretch
        count = self._levels_layout.count()
        self._levels_layout.insertWidget(count - 1, widget)

        self._mark_dirty()

    def _remove_hierarchy_level(self, widget: HierarchyLevelWidget):
        """Remove a hierarchy level widget."""
        if widget in self._hierarchy_widgets:
            self._hierarchy_widgets.remove(widget)
            widget.setParent(None)
            widget.deleteLater()
            self._mark_dirty()

    def _create_new_schema(self):
        """Create a new schema."""
        if self._is_dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Discard them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Clear form
        self._current_schema_id = None
        self._name_input.setText("New Schema")
        self._name_input.selectAll()
        self._name_input.setFocus()

        # Clear hierarchy levels
        for widget in self._hierarchy_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._hierarchy_widgets.clear()

        # Add default shot level
        self._add_hierarchy_level({'level': 'shot', 'folder_contains': '.blend'})

        # Default patterns
        self._blend_patterns_edit.setText(r'^(?P<shot>[\w]+)\.blend$')
        self._playblast_folder_input.setText('PlayBlast')
        self._playblast_pattern_input.setText(r'^v(?P<version>\d{3})\.mp4$')

        self._errors_list.clear()
        self._errors_group.hide()
        self._is_dirty = True

    def _delete_schema(self):
        """Delete the current schema."""
        if not self._current_schema_id:
            QMessageBox.warning(self, "No Schema", "No schema selected to delete.")
            return

        reply = QMessageBox.question(
            self, "Delete Schema",
            f"Are you sure you want to delete '{self._name_input.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from ...services.database.folder_schemas import FolderSchemaRepository
            repo = FolderSchemaRepository(self._db_service._connection)
            repo.delete(self._current_schema_id)

            self._current_schema_id = None
            self._is_dirty = False
            self._load_schemas()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete schema: {e}")

    def _on_preset_selected(self, index: int):
        """Load a preset schema (T139)."""
        if index <= 0:  # Skip "Load Preset..." item
            return

        preset_name = self._preset_combo.itemText(index)
        preset_data = SCHEMA_PRESETS.get(preset_name)

        if preset_data:
            # Clear and populate with preset
            self._name_input.setText(preset_data.get('name', preset_name))

            # Clear hierarchy levels
            for widget in self._hierarchy_widgets:
                widget.setParent(None)
                widget.deleteLater()
            self._hierarchy_widgets.clear()

            # Add preset levels
            for level_data in preset_data.get('hierarchy_levels', []):
                self._add_hierarchy_level(level_data)

            # Patterns
            blend_patterns = preset_data.get('blend_file_patterns', [])
            self._blend_patterns_edit.setText('\n'.join(blend_patterns))

            self._playblast_folder_input.setText(preset_data.get('playblast_folder', 'PlayBlast'))
            self._playblast_pattern_input.setText(
                preset_data.get('playblast_pattern', r'^v(?P<version>\d{3})\.mp4$')
            )

            self._mark_dirty()

        # Reset combo to "Load Preset..."
        self._preset_combo.setCurrentIndex(0)

    def _mark_dirty(self):
        """Mark form as having unsaved changes."""
        self._is_dirty = True

    def _validate_schema(self) -> List[str]:
        """Validate the current schema configuration (T154)."""
        errors = []

        # Name required
        name = self._name_input.text().strip()
        if not name:
            errors.append("Schema name is required")

        # At least one hierarchy level
        if not self._hierarchy_widgets:
            errors.append("At least one hierarchy level is required")

        # Validate each level
        for widget in self._hierarchy_widgets:
            errors.extend(widget.validate())

        # Must have shot level or folder_contains
        has_shot = any(
            w.get_data().get('level') == 'shot' or w.get_data().get('folder_contains')
            for w in self._hierarchy_widgets
        )
        if not has_shot:
            errors.append("Schema must define a 'shot' level or use 'folder_contains'")

        # Validate blend patterns
        blend_text = self._blend_patterns_edit.toPlainText().strip()
        if not blend_text:
            errors.append("At least one blend file pattern is required")
        else:
            for line in blend_text.split('\n'):
                line = line.strip()
                if line:
                    try:
                        compiled = re.compile(line)
                        if 'shot' not in compiled.groupindex:
                            errors.append(f"Blend pattern missing (?P<shot>...) group: {line[:50]}")
                    except re.error as e:
                        errors.append(f"Invalid blend pattern: {e}")

        # Validate playblast pattern
        playblast_pattern = self._playblast_pattern_input.text().strip()
        if playblast_pattern:
            try:
                compiled = re.compile(playblast_pattern)
                if 'version' not in compiled.groupindex:
                    errors.append("Playblast pattern missing (?P<version>...) group")
            except re.error as e:
                errors.append(f"Invalid playblast pattern: {e}")

        return errors

    def _show_validation_errors(self, errors: List[str]):
        """Display validation errors (T154)."""
        self._errors_list.clear()

        if errors:
            for error in errors:
                item = QListWidgetItem(error)
                item.setForeground(Qt.GlobalColor.red)
                self._errors_list.addItem(item)
            self._errors_group.show()
        else:
            self._errors_group.hide()

    def _save_schema(self):
        """Save the current schema (T141)."""
        # Validate first
        errors = self._validate_schema()
        self._show_validation_errors(errors)

        if errors:
            QMessageBox.warning(
                self, "Validation Failed",
                f"Please fix {len(errors)} error(s) before saving."
            )
            return

        if not self._db_service:
            QMessageBox.warning(self, "Error", "No database connection")
            return

        try:
            from ...services.database.folder_schemas import FolderSchemaRepository
            repo = FolderSchemaRepository(self._db_service._connection)

            # Build config
            config = self._build_config()
            name = self._name_input.text().strip()

            if self._current_schema_id:
                # Update existing
                repo.update(self._current_schema_id, name=name, config=config)
            else:
                # Create new
                self._current_schema_id = repo.create(name, config)

            self._is_dirty = False
            self._load_schemas()

            QMessageBox.information(self, "Saved", f"Schema '{name}' saved successfully.")

        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save schema: {e}")

    def _build_config(self) -> Dict[str, Any]:
        """Build schema config dict from form."""
        return {
            'name': self._name_input.text().strip(),
            'hierarchy_levels': [w.get_data() for w in self._hierarchy_widgets],
            'blend_file_patterns': [
                line.strip()
                for line in self._blend_patterns_edit.toPlainText().split('\n')
                if line.strip()
            ],
            'playblast_folder': self._playblast_folder_input.text().strip() or 'PlayBlast',
            'playblast_pattern': self._playblast_pattern_input.text().strip() or r'^v(?P<version>\d{3})\.mp4$',
        }

    def _set_active_schema(self):
        """Set current schema as active (T143)."""
        if not self._current_schema_id:
            QMessageBox.warning(self, "No Schema", "Please save the schema first.")
            return

        if not self._db_service:
            return

        try:
            from ...services.database.folder_schemas import FolderSchemaRepository
            repo = FolderSchemaRepository(self._db_service._connection)
            repo.set_active(self._current_schema_id)

            self._load_schemas()
            self.schema_changed.emit(self._current_schema_id)

            QMessageBox.information(
                self, "Active Schema",
                f"'{self._name_input.text()}' is now the active schema."
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to set active schema: {e}")

    def _test_schema(self):
        """Test schema against sample path (T140)."""
        test_path = self._test_path_input.text().strip()
        if not test_path:
            self._test_results.setText("Please enter a sample path to test.")
            return

        # Build and validate config first
        errors = self._validate_schema()
        if errors:
            self._test_results.setText("Schema has validation errors:\n" + '\n'.join(errors))
            return

        try:
            config = self._build_config()
            parser = FolderSchemaParser.from_dict(config)

            path = Path(test_path)
            result = parser.parse_path(path)

            # Also parse filename if it's a file
            filename_result = None
            if path.suffix == '.blend':
                filename_result = parser.parse_blend_filename(path.name)

            # Format results
            output = ["=== Path Parse Results ==="]
            output.append(f"Show: {result.show or '(not matched)'}")
            output.append(f"Episode: {result.episode or '(not matched)'} (num: {result.episode_num})")
            output.append(f"Sequence: {result.sequence or '(not matched)'} (num: {result.sequence_num})")
            output.append(f"Scene: {result.scene or '(not matched)'} (num: {result.scene_num})")
            output.append(f"Shot: {result.shot or '(not matched)'} (num: {result.shot_num})")
            output.append(f"Match Confidence: {result.match_confidence:.1%}")

            if result.warnings:
                output.append("\nWarnings:")
                for warning in result.warnings:
                    output.append(f"  - {warning}")

            if filename_result:
                output.append("\n=== Filename Parse Results ===")
                output.append(f"Shot: {filename_result.shot or '(not matched)'}")
                output.append(f"Version: {filename_result.version or '(not matched)'}")

            # Check if it would be recognized as a shot folder
            if path.is_dir() or (path.parent.exists() and path.suffix == '.blend'):
                folder = path if path.is_dir() else path.parent
                is_shot = parser.is_shot_folder(folder)
                output.append(f"\nIs Shot Folder: {'Yes' if is_shot else 'No'}")

            self._test_results.setText('\n'.join(output))

        except Exception as e:
            self._test_results.setText(f"Error testing schema:\n{e}")

    def _browse_test_path(self):
        """Browse for a test path."""
        path = QFileDialog.getExistingDirectory(
            self, "Select Folder to Test",
            str(Path.home())
        )
        if path:
            self._test_path_input.setText(path)

    def _import_schema(self):
        """Import schema from JSON file (T145)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Schema",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Populate form with imported data
            self._name_input.setText(data.get('name', 'Imported Schema'))

            # Clear hierarchy levels
            for widget in self._hierarchy_widgets:
                widget.setParent(None)
                widget.deleteLater()
            self._hierarchy_widgets.clear()

            # Add levels
            for level_data in data.get('hierarchy_levels', []):
                self._add_hierarchy_level(level_data)

            # Patterns
            blend_patterns = data.get('blend_file_patterns', [])
            self._blend_patterns_edit.setText('\n'.join(blend_patterns))

            self._playblast_folder_input.setText(data.get('playblast_folder', 'PlayBlast'))
            self._playblast_pattern_input.setText(
                data.get('playblast_pattern', r'^v(?P<version>\d{3})\.mp4$')
            )

            self._current_schema_id = None  # Treat as new
            self._mark_dirty()

            QMessageBox.information(self, "Imported", f"Schema imported from {Path(file_path).name}")

        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Failed to import schema: {e}")

    def _export_schema(self):
        """Export schema to JSON file (T144)."""
        # Validate first
        errors = self._validate_schema()
        if errors:
            self._show_validation_errors(errors)
            QMessageBox.warning(self, "Validation Failed", "Please fix errors before exporting.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Schema",
            str(Path.home() / f"{self._name_input.text()}.json"),
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            config = self._build_config()

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            QMessageBox.information(self, "Exported", f"Schema exported to {Path(file_path).name}")

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Failed to export schema: {e}")

    def _on_close(self):
        """Handle close button."""
        if self._is_dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Discard them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.accept()

    def closeEvent(self, event):
        """Handle window close."""
        if self._is_dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Discard them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

        event.accept()


__all__ = ['SchemaConfigDialog']
