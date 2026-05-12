"""
Settings Panel for Render Queue Manager

Per-job settings panel with override checkboxes.
Default: show .blend file values (read-only)
Override checkbox enables editing that field.
"""

from pathlib import Path
from typing import Dict, Optional, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QCheckBox, QGroupBox, QScrollArea,
    QSlider, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from ...themes.fonts import Fonts, get_font_stylesheet

from ...services.blender_render_service import BlendFileInfo


# Store UI state per job (override checkboxes, button selections)
_job_ui_state: Dict[str, Dict[str, Any]] = {}


class OverrideField(QWidget):
    """A field with an override checkbox."""

    value_changed = pyqtSignal()

    def __init__(
        self,
        label: str,
        widget: QWidget,
        show_checkbox: bool = True,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        self._widget = widget
        self._original_value = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Label
        self._label = QLabel(label)
        self._label.setFixedWidth(100)
        self._label.setStyleSheet("color: #888;")
        layout.addWidget(self._label)

        # Widget
        widget.setEnabled(False)  # Disabled by default
        layout.addWidget(widget, 1)

        # Override checkbox
        if show_checkbox:
            self._checkbox = QCheckBox()
            self._checkbox.setToolTip("Override this setting")
            self._checkbox.stateChanged.connect(self._on_checkbox_changed)
            layout.addWidget(self._checkbox)
        else:
            self._checkbox = None

    def _on_checkbox_changed(self, state):
        """Handle checkbox state change."""
        enabled = state == Qt.CheckState.Checked.value
        self._widget.setEnabled(enabled)
        if not enabled and self._original_value is not None:
            self._set_value(self._original_value)
        self.value_changed.emit()

    def set_value(self, value, as_original: bool = True):
        """Set the field value."""
        if as_original:
            self._original_value = value
        self._set_value(value)

    def _set_value(self, value):
        """Internal set value."""
        if isinstance(self._widget, QLineEdit):
            self._widget.setText(str(value) if value else "")
        elif isinstance(self._widget, QSpinBox):
            self._widget.setValue(int(value) if value else 0)
        elif isinstance(self._widget, QComboBox):
            idx = self._widget.findText(str(value))
            if idx >= 0:
                self._widget.setCurrentIndex(idx)
        elif isinstance(self._widget, QCheckBox):
            self._widget.setChecked(bool(value))

    def get_value(self):
        """Get current value."""
        if isinstance(self._widget, QLineEdit):
            return self._widget.text()
        elif isinstance(self._widget, QSpinBox):
            return self._widget.value()
        elif isinstance(self._widget, QComboBox):
            return self._widget.currentText()
        elif isinstance(self._widget, QCheckBox):
            return self._widget.isChecked()
        return None

    def is_override_enabled(self) -> bool:
        """Check if override is enabled."""
        return self._checkbox.isChecked() if self._checkbox else False

    def set_override_enabled(self, enabled: bool):
        """Set override checkbox state."""
        if self._checkbox:
            self._checkbox.setChecked(enabled)


class SettingsPanel(QWidget):
    """
    Per-job settings panel with override checkboxes.

    Sections matching mockup:
    - Render: Engine, Samples, Film Transparent
    - Format: Media Type, Resolution, Scale, Overwrite, Placeholders
    - Output: Path, File Format, Color Mode, Depth, Compression
    - Python arguments: Script path, execution timing
    """

    settings_changed = pyqtSignal(str, dict)  # job_id, overrides

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._current_job_id: Optional[str] = None
        self._fields: Dict[str, OverrideField] = {}

        self._setup_ui()
        self._connect_field_signals()

    def _connect_field_signals(self):
        """Connect field value_changed signals to emit settings_changed."""
        for name, field in self._fields.items():
            field.value_changed.connect(self._on_field_changed)

    def _on_field_changed(self):
        """Handle any field value change."""
        self._save_ui_state()
        if self._current_job_id:
            overrides = self.get_overrides()
            self.settings_changed.emit(self._current_job_id, overrides)

    def _setup_ui(self):
        """Create the UI."""
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
            }
            QGroupBox {
                color: white;
                font-weight: bold;
                border: none;
                margin-top: 16px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 0px;
                padding: 0px;
            }
            QLabel {
                color: #888;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #404040;
                border-radius: 0px;
                padding: 4px 8px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #3A8FB7;
            }
            QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
                background-color: #252525;
                color: #666;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #3A3A3A;
                color: white;
                border: 1px solid #404040;
                selection-background-color: #3A8FB7;
            }
            QCheckBox {
                color: white;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #404040;
                border-radius: 0px;
                background-color: #2D2D2D;
            }
            QCheckBox::indicator:checked {
                background-color: #3A8FB7;
                border-color: #3A8FB7;
            }
            QCheckBox::indicator:unchecked {
                background-color: #2D2D2D;
            }
            QCheckBox::indicator:hover {
                border-color: #3A8FB7;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #3A3A3A;
                border: none;
                width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #3A8FB7;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Job title
        self._title_label = QLabel("")
        self._title_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        layout.addWidget(self._title_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #333;")
        layout.addWidget(sep)

        # ===== Render Section =====
        render_group = QGroupBox("Render")
        render_layout = QVBoxLayout(render_group)
        render_layout.setSpacing(8)

        # Render Engine
        engine_combo = QComboBox()
        engine_combo.addItems(["Eevee", "Cycles", "Workbench"])
        self._fields['render_engine'] = OverrideField("Render Engine", engine_combo)
        render_layout.addWidget(self._fields['render_engine'])

        # Render Samples
        samples_spin = QSpinBox()
        samples_spin.setRange(1, 10000)
        samples_spin.setValue(64)
        self._fields['samples'] = OverrideField("Render Samples", samples_spin)
        render_layout.addWidget(self._fields['samples'])

        # Film Transparent
        transparent_check = QCheckBox("Film Transparent")
        transparent_check.setStyleSheet("color: white;")
        self._fields['film_transparent'] = OverrideField("", transparent_check, show_checkbox=False)
        render_layout.addWidget(self._fields['film_transparent'])

        layout.addWidget(render_group)

        # ===== Format Section =====
        format_group = QGroupBox("Format")
        format_layout = QVBoxLayout(format_group)
        format_layout.setSpacing(8)

        # Match source button
        match_btn = QPushButton("Match source")
        match_btn.setStyleSheet("""
            QPushButton {
                background-color: #3A3A3A;
                color: #888;
                border: 1px solid #404040;
                border-radius: 0px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #3A8FB7;
                color: white;
                border-color: #3A8FB7;
            }
        """)
        match_btn.clicked.connect(self._on_match_source)
        format_layout.addWidget(match_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # Media Type (button group style)
        media_widget = QWidget()
        media_layout = QHBoxLayout(media_widget)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(0)

        media_label = QLabel("Media Type")
        media_label.setFixedWidth(100)
        media_layout.addWidget(media_label)

        self._media_buttons = []
        for i, text in enumerate(["Image", "Multi-Layer EXR", "Video"]):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3A3A3A;
                    color: #888;
                    border: 1px solid #404040;
                    border-radius: 0px;
                    padding: 6px 12px;
                }
                QPushButton:checked {
                    background-color: #3A8FB7;
                    color: white;
                    border-color: #3A8FB7;
                }
                QPushButton:hover:!checked {
                    background-color: #444;
                    border-color: #3A8FB7;
                }
            """)
            btn.clicked.connect(lambda checked, b=btn: self._on_media_type_clicked(b))
            self._media_buttons.append(btn)
            media_layout.addWidget(btn)

        media_layout.addStretch()
        format_layout.addWidget(media_widget)

        # Resolution X
        res_x_spin = QSpinBox()
        res_x_spin.setRange(1, 16384)
        res_x_spin.setValue(1920)
        res_x_spin.setSuffix("px")
        self._fields['resolution_x'] = OverrideField("Resolution X", res_x_spin)
        format_layout.addWidget(self._fields['resolution_x'])

        # Resolution Y
        res_y_spin = QSpinBox()
        res_y_spin.setRange(1, 16384)
        res_y_spin.setValue(1080)
        res_y_spin.setSuffix("px")
        self._fields['resolution_y'] = OverrideField("Resolution Y", res_y_spin)
        format_layout.addWidget(self._fields['resolution_y'])

        # Resolution Scale
        scale_spin = QSpinBox()
        scale_spin.setRange(1, 100)
        scale_spin.setValue(100)
        scale_spin.setSuffix("%")
        self._fields['resolution_scale'] = OverrideField("Resolution Scale", scale_spin)
        format_layout.addWidget(self._fields['resolution_scale'])

        # Overwrite checkbox
        overwrite_widget = QWidget()
        overwrite_layout = QHBoxLayout(overwrite_widget)
        overwrite_layout.setContentsMargins(0, 0, 0, 0)
        overwrite_check = QCheckBox("Overwrite")
        overwrite_check.setChecked(True)
        overwrite_check.setStyleSheet("color: white;")
        overwrite_layout.addWidget(overwrite_check)
        placeholder_check = QCheckBox("Placeholders")
        placeholder_check.setStyleSheet("color: white;")
        overwrite_layout.addWidget(placeholder_check)
        overwrite_layout.addStretch()
        format_layout.addWidget(overwrite_widget)

        layout.addWidget(format_group)

        # ===== Output Section =====
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        output_layout.setSpacing(8)

        # Output path with warning
        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(4)

        self._output_path = QLineEdit()
        self._output_path.setPlaceholderText("/tmp/")
        path_layout.addWidget(self._output_path, 1)

        self._path_warning = QLabel("")
        self._path_warning.setStyleSheet("color: #f39c12;")
        path_layout.addWidget(self._path_warning)

        browse_btn = QPushButton("...")
        browse_btn.setFixedSize(24, 24)
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #3A3A3A;
                color: white;
                border: 1px solid #404040;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #3A8FB7;
                border-color: #3A8FB7;
            }
        """)
        path_layout.addWidget(browse_btn)

        self._fields['output_path'] = OverrideField("", self._output_path, show_checkbox=False)
        output_layout.addWidget(path_widget)

        # ===== Image Format Settings (shown when Media Type = Image) =====
        self._image_settings_container = QWidget()
        image_settings_layout = QVBoxLayout(self._image_settings_container)
        image_settings_layout.setContentsMargins(0, 0, 0, 0)
        image_settings_layout.setSpacing(8)

        # File Format dropdown (Image only)
        format_combo = QComboBox()
        format_combo.addItems(["PNG", "JPEG", "OpenEXR", "TIFF", "BMP"])
        self._fields['file_format'] = OverrideField("File Format", format_combo)
        image_settings_layout.addWidget(self._fields['file_format'])

        # Color Mode (Image)
        color_widget = QWidget()
        color_layout = QHBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(0)

        color_label = QLabel("Color Mode")
        color_label.setFixedWidth(100)
        color_layout.addWidget(color_label)

        self._color_buttons = []
        for i, text in enumerate(["BW", "RGB", "RGBA"]):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(i == 2)  # RGBA default
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3A3A3A;
                    color: #888;
                    border: 1px solid #404040;
                    border-radius: 0px;
                    padding: 6px 12px;
                    min-width: 40px;
                }
                QPushButton:checked {
                    background-color: #3A8FB7;
                    color: white;
                    border-color: #3A8FB7;
                }
                QPushButton:hover:!checked {
                    background-color: #444;
                    border-color: #3A8FB7;
                }
            """)
            btn.clicked.connect(lambda checked, b=btn: self._on_color_mode_clicked(b))
            self._color_buttons.append(btn)
            color_layout.addWidget(btn)

        color_layout.addStretch()
        image_settings_layout.addWidget(color_widget)

        # Color Depth (Image - 8/16 bit)
        depth_widget = QWidget()
        depth_layout = QHBoxLayout(depth_widget)
        depth_layout.setContentsMargins(0, 0, 0, 0)
        depth_layout.setSpacing(0)

        depth_label = QLabel("Color Depth")
        depth_label.setFixedWidth(100)
        depth_layout.addWidget(depth_label)

        self._depth_buttons = []
        for i, text in enumerate(["8", "16"]):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(i == 0)  # 8-bit default
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3A3A3A;
                    color: #888;
                    border: 1px solid #404040;
                    border-radius: 0px;
                    padding: 6px 12px;
                    min-width: 40px;
                }
                QPushButton:checked {
                    background-color: #3A8FB7;
                    color: white;
                    border-color: #3A8FB7;
                }
                QPushButton:hover:!checked {
                    background-color: #444;
                    border-color: #3A8FB7;
                }
            """)
            btn.clicked.connect(lambda checked, b=btn: self._on_depth_clicked(b))
            self._depth_buttons.append(btn)
            depth_layout.addWidget(btn)

        depth_layout.addStretch()
        image_settings_layout.addWidget(depth_widget)

        # Compression slider (PNG/JPEG)
        self._compress_widget = QWidget()
        compress_layout = QHBoxLayout(self._compress_widget)
        compress_layout.setContentsMargins(0, 0, 0, 0)

        compress_label = QLabel("Compression")
        compress_label.setFixedWidth(100)
        compress_layout.addWidget(compress_label)

        self._compression_slider = QSlider(Qt.Orientation.Horizontal)
        self._compression_slider.setRange(0, 100)
        self._compression_slider.setValue(15)
        compress_layout.addWidget(self._compression_slider, 1)

        self._compression_value = QLabel("15%")
        self._compression_value.setFixedWidth(40)
        self._compression_slider.valueChanged.connect(self._on_compression_changed)
        compress_layout.addWidget(self._compression_value)

        image_settings_layout.addWidget(self._compress_widget)

        output_layout.addWidget(self._image_settings_container)

        # ===== EXR Format Settings (shown when Media Type = Multi-Layer EXR) =====
        self._exr_settings_container = QWidget()
        exr_settings_layout = QVBoxLayout(self._exr_settings_container)
        exr_settings_layout.setContentsMargins(0, 0, 0, 0)
        exr_settings_layout.setSpacing(8)

        # EXR Color Depth (16/32 bit float)
        exr_depth_widget = QWidget()
        exr_depth_layout = QHBoxLayout(exr_depth_widget)
        exr_depth_layout.setContentsMargins(0, 0, 0, 0)
        exr_depth_layout.setSpacing(0)

        exr_depth_label = QLabel("Color Depth")
        exr_depth_label.setFixedWidth(100)
        exr_depth_layout.addWidget(exr_depth_label)

        self._exr_depth_buttons = []
        for i, text in enumerate(["Half (16-bit)", "Full (32-bit)"]):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(i == 0)  # Half float default
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3A3A3A;
                    color: #888;
                    border: 1px solid #404040;
                    border-radius: 0px;
                    padding: 6px 12px;
                }
                QPushButton:checked {
                    background-color: #3A8FB7;
                    color: white;
                    border-color: #3A8FB7;
                }
                QPushButton:hover:!checked {
                    background-color: #444;
                    border-color: #3A8FB7;
                }
            """)
            btn.clicked.connect(lambda checked, b=btn: self._on_exr_depth_clicked(b))
            self._exr_depth_buttons.append(btn)
            exr_depth_layout.addWidget(btn)

        exr_depth_layout.addStretch()
        exr_settings_layout.addWidget(exr_depth_widget)

        # EXR Codec
        exr_codec_widget = QWidget()
        exr_codec_layout = QHBoxLayout(exr_codec_widget)
        exr_codec_layout.setContentsMargins(0, 0, 0, 0)

        exr_codec_label = QLabel("Codec")
        exr_codec_label.setFixedWidth(100)
        exr_codec_layout.addWidget(exr_codec_label)

        self._exr_codec_combo = QComboBox()
        self._exr_codec_combo.addItems(["ZIP (lossless)", "PIZ (lossless)", "DWAA (lossy)", "DWAB (lossy)", "None"])
        self._exr_codec_combo.setCurrentIndex(0)
        self._exr_codec_combo.currentIndexChanged.connect(self._on_exr_codec_changed)
        exr_codec_layout.addWidget(self._exr_codec_combo, 1)

        exr_settings_layout.addWidget(exr_codec_widget)

        # EXR info label
        exr_info = QLabel("Multi-Layer EXR includes all render passes")
        exr_info.setStyleSheet("color: #666; font-style: italic;")
        exr_settings_layout.addWidget(exr_info)

        output_layout.addWidget(self._exr_settings_container)

        # Initially hide EXR settings
        self._exr_settings_container.setVisible(False)

        layout.addWidget(output_group)

        # ===== Python Arguments Section =====
        python_group = QGroupBox("Python arguments")
        python_layout = QVBoxLayout(python_group)
        python_layout.setSpacing(8)

        # Script path
        script_widget = QWidget()
        script_layout = QHBoxLayout(script_widget)
        script_layout.setContentsMargins(0, 0, 0, 0)

        self._script_path = QLineEdit()
        self._script_path.setPlaceholderText("Python expression or script path")
        script_layout.addWidget(self._script_path, 1)

        script_browse = QPushButton("...")
        script_browse.setFixedSize(24, 24)
        script_browse.setStyleSheet("""
            QPushButton {
                background-color: #3A3A3A;
                color: white;
                border: 1px solid #404040;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #3A8FB7;
                border-color: #3A8FB7;
            }
        """)
        script_layout.addWidget(script_browse)

        python_layout.addWidget(script_widget)

        # Execution time
        exec_widget = QWidget()
        exec_layout = QHBoxLayout(exec_widget)
        exec_layout.setContentsMargins(0, 0, 0, 0)

        exec_label = QLabel("Execution time:")
        exec_label.setStyleSheet("color: #888;")
        exec_layout.addWidget(exec_label)

        exec_combo = QComboBox()
        exec_combo.addItems(["After rendering completes", "Before rendering starts"])
        exec_layout.addWidget(exec_combo)

        exec_layout.addStretch()
        python_layout.addWidget(exec_widget)

        layout.addWidget(python_group)

        layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _on_media_type_clicked(self, clicked_btn):
        """Handle media type button click."""
        for btn in self._media_buttons:
            btn.setChecked(btn == clicked_btn)

        # Get selected media type
        media_type = clicked_btn.text()

        if media_type == "Video":
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Video Not Supported",
                "Video output is not supported by the Render Manager.\n"
                "Use Image or Multi-Layer EXR for frame sequences."
            )
            # Revert to Image
            self._media_buttons[0].setChecked(True)
            clicked_btn.setChecked(False)
            media_type = "Image"

        # Toggle visibility of format-specific settings
        is_exr = (media_type == "Multi-Layer EXR")
        self._image_settings_container.setVisible(not is_exr)
        self._exr_settings_container.setVisible(is_exr)

        # Save UI state for current job
        self._save_ui_state()

        # Emit settings change with appropriate format
        if self._current_job_id:
            if is_exr:
                file_format = "OPEN_EXR_MULTILAYER"
            else:
                # Use dropdown value for Image type
                file_format = self._get_image_format()

            self.settings_changed.emit(self._current_job_id, {'file_format': file_format})

    def _get_image_format(self) -> str:
        """Get the file format from the dropdown, mapped to Blender CLI names."""
        if 'file_format' not in self._fields:
            return 'PNG'
        dropdown_value = self._fields['file_format'].get_value()
        format_map = {
            'PNG': 'PNG', 'JPEG': 'JPEG', 'OpenEXR': 'OPEN_EXR',
            'TIFF': 'TIFF', 'BMP': 'BMP',
        }
        return format_map.get(dropdown_value, 'PNG')

    def get_selected_media_type(self) -> str:
        """Get the currently selected media type."""
        for btn in self._media_buttons:
            if btn.isChecked():
                return btn.text()
        return "Image"

    def _on_color_mode_clicked(self, clicked_btn):
        """Handle color mode button click."""
        for btn in self._color_buttons:
            btn.setChecked(btn == clicked_btn)

        self._save_ui_state()

        # Emit settings change
        if self._current_job_id:
            color_mode = clicked_btn.text()  # "BW", "RGB", "RGBA"
            self.settings_changed.emit(self._current_job_id, {'color_mode': color_mode})

    def _on_depth_clicked(self, clicked_btn):
        """Handle depth button click."""
        for btn in self._depth_buttons:
            btn.setChecked(btn == clicked_btn)

        self._save_ui_state()

        # Emit settings change
        if self._current_job_id:
            depth = clicked_btn.text()  # "8", "16"
            self.settings_changed.emit(self._current_job_id, {'color_depth': depth})

    def _on_compression_changed(self, value: int):
        """Handle compression slider change."""
        self._compression_value.setText(f"{value}%")
        self._save_ui_state()
        if self._current_job_id:
            self.settings_changed.emit(self._current_job_id, {'compression': value})

    def _on_exr_depth_clicked(self, clicked_btn):
        """Handle EXR color depth button click."""
        for btn in self._exr_depth_buttons:
            btn.setChecked(btn == clicked_btn)

        self._save_ui_state()

        if self._current_job_id:
            # Map button text to Blender values
            depth = "16" if "16" in clicked_btn.text() else "32"
            self.settings_changed.emit(self._current_job_id, {'exr_color_depth': depth})

    def _on_exr_codec_changed(self, index: int):
        """Handle EXR codec change."""
        self._save_ui_state()

        if self._current_job_id:
            codec_map = {
                0: 'ZIP', 1: 'PIZ', 2: 'DWAA', 3: 'DWAB', 4: 'NONE'
            }
            codec = codec_map.get(index, 'ZIP')
            self.settings_changed.emit(self._current_job_id, {'exr_codec': codec})

    def _save_ui_state(self):
        """Save current UI state for the current job."""
        if not self._current_job_id:
            return

        state = {
            # Override checkboxes
            'overrides': {name: field.is_override_enabled() for name, field in self._fields.items()},
            # Field values
            'values': {name: field.get_value() for name, field in self._fields.items()},
            # Media type
            'media_type': self.get_selected_media_type(),
            # Color mode
            'color_mode': next((btn.text() for btn in self._color_buttons if btn.isChecked()), 'RGBA'),
            # Color depth (image)
            'color_depth': next((btn.text() for btn in self._depth_buttons if btn.isChecked()), '8'),
            # Compression
            'compression': self._compression_slider.value(),
            # EXR settings
            'exr_depth': next((btn.text() for btn in self._exr_depth_buttons if btn.isChecked()), 'Half (16-bit)'),
            'exr_codec': self._exr_codec_combo.currentIndex(),
        }
        _job_ui_state[self._current_job_id] = state

    def _restore_ui_state(self, job_id: str):
        """Restore UI state for a job."""
        state = _job_ui_state.get(job_id)
        if not state:
            return False

        # Restore override checkboxes
        for name, enabled in state.get('overrides', {}).items():
            if name in self._fields:
                self._fields[name].set_override_enabled(enabled)

        # Restore field values (only if override was enabled)
        for name, value in state.get('values', {}).items():
            if name in self._fields and state.get('overrides', {}).get(name, False):
                self._fields[name].set_value(value, as_original=False)

        # Restore media type
        media_type = state.get('media_type', 'Image')
        for btn in self._media_buttons:
            btn.setChecked(btn.text() == media_type)

        # Toggle visibility based on media type
        is_exr = (media_type == "Multi-Layer EXR")
        self._image_settings_container.setVisible(not is_exr)
        self._exr_settings_container.setVisible(is_exr)

        # Restore color mode
        color_mode = state.get('color_mode', 'RGBA')
        for btn in self._color_buttons:
            btn.setChecked(btn.text() == color_mode)

        # Restore color depth
        color_depth = state.get('color_depth', '8')
        for btn in self._depth_buttons:
            btn.setChecked(btn.text() == color_depth)

        # Restore compression
        self._compression_slider.setValue(state.get('compression', 15))

        # Restore EXR settings
        exr_depth = state.get('exr_depth', 'Half (16-bit)')
        for btn in self._exr_depth_buttons:
            btn.setChecked(btn.text() == exr_depth)

        exr_codec = state.get('exr_codec', 0)
        self._exr_codec_combo.setCurrentIndex(exr_codec)

        return True

    def _on_match_source(self):
        """Reset all overrides to blend file values (match source)."""
        if not self._current_job_id:
            return

        # Uncheck all override checkboxes
        for field in self._fields.values():
            field.set_override_enabled(False)

        # Reset media type to Image
        self._media_buttons[0].setChecked(True)
        for btn in self._media_buttons[1:]:
            btn.setChecked(False)

        # Show image settings, hide EXR settings
        self._image_settings_container.setVisible(True)
        self._exr_settings_container.setVisible(False)

        # Reset color mode to RGBA
        for btn in self._color_buttons:
            btn.setChecked(btn.text() == "RGBA")

        # Reset depth to 8
        for btn in self._depth_buttons:
            btn.setChecked(btn.text() == "8")

        # Reset compression to default
        self._compression_slider.setValue(15)

        # Reset EXR settings
        for btn in self._exr_depth_buttons:
            btn.setChecked("16" in btn.text())
        self._exr_codec_combo.setCurrentIndex(0)

        # Clear saved UI state for this job
        if self._current_job_id in _job_ui_state:
            del _job_ui_state[self._current_job_id]

    def set_job(self, job_id: str, job_info: Dict, blend_info: Optional[BlendFileInfo] = None):
        """Set current job and populate fields."""
        # Save UI state for current job before switching
        if self._current_job_id and self._current_job_id != job_id:
            self._save_ui_state()

        self._current_job_id = job_id

        # Title
        blend_name = Path(job_info.get('blend_file', '')).name
        self._title_label.setText(blend_name)

        # Populate from blend_info or job_info (original values for non-override display)
        info = blend_info or BlendFileInfo(blend_file=Path(""))

        # Render settings
        engine = info.render_engine if blend_info else job_info.get('render_engine', 'CYCLES')
        engine_display = {'CYCLES': 'Cycles', 'BLENDER_EEVEE': 'Eevee', 'BLENDER_WORKBENCH': 'Workbench'}.get(engine, engine)
        self._fields['render_engine'].set_value(engine_display)

        samples = info.samples if blend_info else job_info.get('samples', 128)
        self._fields['samples'].set_value(samples)

        # Resolution
        self._fields['resolution_x'].set_value(info.resolution_x if blend_info else job_info.get('resolution_x', 1920))
        self._fields['resolution_y'].set_value(info.resolution_y if blend_info else job_info.get('resolution_y', 1080))

        # File format
        file_format = info.file_format if blend_info else job_info.get('file_format', 'PNG')
        self._fields['file_format'].set_value(file_format)

        # Output path
        output_dir = job_info.get('output_dir', '')
        self._output_path.setText(str(output_dir))

        # Check if output path is not in Render/current - show warning
        if output_dir and 'Render/current' not in str(output_dir) and 'Render\\current' not in str(output_dir):
            self._path_warning.setText("")
        else:
            self._path_warning.setText("")

        # Try to restore saved UI state (override checkboxes, button selections, etc.)
        if self._restore_ui_state(job_id):
            return  # UI state restored, don't reset to defaults

        # No saved state - initialize to defaults based on file format
        is_multilayer = file_format.upper() in ('MULTILAYER', 'OPEN_EXR_MULTILAYER')

        # Set media type buttons based on format
        for i, btn in enumerate(self._media_buttons):
            if i == 1:  # Multi-Layer EXR button
                btn.setChecked(is_multilayer)
            elif i == 0:  # Image button
                btn.setChecked(not is_multilayer)
            else:  # Video button
                btn.setChecked(False)

        # Toggle visibility of format-specific settings
        self._image_settings_container.setVisible(not is_multilayer)
        self._exr_settings_container.setVisible(is_multilayer)

        # Reset all override checkboxes for new jobs
        for field in self._fields.values():
            field.set_override_enabled(False)

        # Reset button groups to defaults
        for btn in self._color_buttons:
            btn.setChecked(btn.text() == "RGBA")
        for btn in self._depth_buttons:
            btn.setChecked(btn.text() == "8")
        for btn in self._exr_depth_buttons:
            btn.setChecked("16" in btn.text())
        self._exr_codec_combo.setCurrentIndex(0)
        self._compression_slider.setValue(15)

    def get_overrides(self) -> Dict:
        """Get all enabled overrides."""
        overrides = {}

        # Check media type selection
        media_type = self.get_selected_media_type()
        is_exr = (media_type == "Multi-Layer EXR")

        if is_exr:
            # EXR format settings
            overrides['file_format'] = 'OPEN_EXR_MULTILAYER'

            # EXR color depth (16 or 32 bit float)
            for btn in self._exr_depth_buttons:
                if btn.isChecked():
                    overrides['exr_color_depth'] = "16" if "16" in btn.text() else "32"
                    break

            # EXR codec
            codec_map = {0: 'ZIP', 1: 'PIZ', 2: 'DWAA', 3: 'DWAB', 4: 'NONE'}
            overrides['exr_codec'] = codec_map.get(self._exr_codec_combo.currentIndex(), 'ZIP')

        else:
            # Image format settings
            if 'file_format' in self._fields and self._fields['file_format'].is_override_enabled():
                overrides['file_format'] = self._get_image_format()

            # Color mode - only include if not default RGBA
            for btn in self._color_buttons:
                if btn.isChecked():
                    if btn.text() != "RGBA":  # Only include if changed from default
                        overrides['color_mode'] = btn.text()
                    break

            # Color depth - only include if not default 8
            for btn in self._depth_buttons:
                if btn.isChecked():
                    if btn.text() != "8":  # Only include if changed from default
                        overrides['color_depth'] = btn.text()
                    break

            # Compression - only include if not default 15
            compression = self._compression_slider.value()
            if compression != 15:
                overrides['compression'] = compression

        # Get other field overrides (resolution, samples, etc.)
        for name, field in self._fields.items():
            if name == 'file_format':
                continue  # Already handled above
            if field.is_override_enabled():
                overrides[name] = field.get_value()

        return overrides

    def clear(self):
        """Clear all fields."""
        self._current_job_id = None
        self._title_label.setText("")

        for field in self._fields.values():
            field.set_override_enabled(False)


__all__ = ['SettingsPanel']
