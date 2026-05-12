"""
Dialog Helper - Centralized dialog utilities

Provides consistent QMessageBox dialogs across the application.
Consolidates 59+ scattered dialog calls into reusable methods.

Includes ProgressDialogHelper for standardized progress dialog creation.
"""

from typing import Optional, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QMessageBox, QInputDialog, QProgressDialog


class DialogHelper:
    """Centralized dialog creation utilities"""

    @staticmethod
    def confirm(
        parent: QWidget,
        title: str,
        message: str,
        yes_text: str = "Yes",
        no_text: str = "No"
    ) -> bool:
        """
        Show Yes/No confirmation dialog.

        Args:
            parent: Parent widget
            title: Dialog title
            message: Dialog message
            yes_text: Text for Yes button (default: "Yes")
            no_text: Text for No button (default: "No")

        Returns:
            True if user clicked Yes, False otherwise
        """
        reply = QMessageBox.question(
            parent,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes

    @staticmethod
    def confirm_destructive(
        parent: QWidget,
        title: str,
        message: str
    ) -> bool:
        """
        Show warning-style confirmation for destructive actions.

        Args:
            parent: Parent widget
            title: Dialog title
            message: Warning message

        Returns:
            True if user confirmed, False otherwise
        """
        reply = QMessageBox.warning(
            parent,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes

    @staticmethod
    def warning(parent: QWidget, title: str, message: str) -> None:
        """
        Show warning dialog.

        Args:
            parent: Parent widget
            title: Dialog title
            message: Warning message
        """
        QMessageBox.warning(parent, title, message)

    @staticmethod
    def info(parent: QWidget, title: str, message: str) -> None:
        """
        Show information dialog.

        Args:
            parent: Parent widget
            title: Dialog title
            message: Info message
        """
        QMessageBox.information(parent, title, message)

    @staticmethod
    def error(parent: QWidget, title: str, message: str) -> None:
        """
        Show error dialog.

        Args:
            parent: Parent widget
            title: Dialog title
            message: Error message
        """
        QMessageBox.critical(parent, title, message)

    @staticmethod
    def select_item(
        parent: QWidget,
        title: str,
        label: str,
        items: list,
        current: int = 0,
        editable: bool = False
    ) -> tuple:
        """
        Show item selection dialog.

        Args:
            parent: Parent widget
            title: Dialog title
            label: Selection label
            items: List of items to choose from
            current: Index of initially selected item
            editable: Whether user can type custom value

        Returns:
            Tuple of (selected_item, ok_pressed)
        """
        return QInputDialog.getItem(
            parent,
            title,
            label,
            items,
            current,
            editable
        )

    @staticmethod
    def get_text(
        parent: QWidget,
        title: str,
        label: str,
        default: str = ""
    ) -> tuple:
        """
        Show text input dialog.

        Args:
            parent: Parent widget
            title: Dialog title
            label: Input label
            default: Default text value

        Returns:
            Tuple of (entered_text, ok_pressed)
        """
        return QInputDialog.getText(
            parent,
            title,
            label,
            text=default
        )


class ProgressDialogHelper:
    """
    Helper for creating and managing progress dialogs.

    Standardizes progress dialog creation across the application,
    reducing boilerplate for common patterns.
    """

    @staticmethod
    def create_modal_progress(
        parent: QWidget,
        title: str,
        label: str,
        minimum: int = 0,
        maximum: int = 100,
        on_cancel: Optional[Callable[[], None]] = None,
        auto_close: bool = True,
        auto_reset: bool = True,
        min_duration: int = 0
    ) -> QProgressDialog:
        """
        Create a modal progress dialog.

        Args:
            parent: Parent widget
            title: Dialog window title
            label: Progress label text
            minimum: Minimum progress value (default: 0)
            maximum: Maximum progress value (default: 100, use 0 for indeterminate)
            on_cancel: Optional callback when cancelled
            auto_close: Auto-close when progress reaches maximum
            auto_reset: Reset progress when dialog re-shows
            min_duration: Minimum time before showing dialog (ms)

        Returns:
            Configured QProgressDialog

        Example:
            progress = ProgressDialogHelper.create_modal_progress(
                self, "Exporting", "Exporting videos...",
                maximum=len(videos),
                on_cancel=lambda: self.cancel_export()
            )
            progress.show()
        """
        progress = QProgressDialog(label, "Cancel", minimum, maximum, parent)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(auto_close)
        progress.setAutoReset(auto_reset)
        progress.setMinimumDuration(min_duration)

        if on_cancel:
            progress.canceled.connect(on_cancel)

        return progress

    @staticmethod
    def create_indeterminate_progress(
        parent: QWidget,
        title: str,
        label: str,
        on_cancel: Optional[Callable[[], None]] = None
    ) -> QProgressDialog:
        """
        Create an indeterminate (spinner) progress dialog.

        Args:
            parent: Parent widget
            title: Dialog window title
            label: Progress label text
            on_cancel: Optional callback when cancelled

        Returns:
            Configured QProgressDialog with indeterminate progress

        Example:
            progress = ProgressDialogHelper.create_indeterminate_progress(
                self, "Loading", "Loading project..."
            )
            progress.show()
        """
        progress = ProgressDialogHelper.create_modal_progress(
            parent, title, label,
            minimum=0, maximum=0,  # Indeterminate
            on_cancel=on_cancel,
            auto_close=False
        )
        return progress

    @staticmethod
    def update_progress(
        dialog: QProgressDialog,
        current: int,
        total: int,
        message: Optional[str] = None
    ) -> bool:
        """
        Update progress dialog with current status.

        Args:
            dialog: Progress dialog to update
            current: Current progress value
            total: Total expected value
            message: Optional updated label text

        Returns:
            False if dialog was cancelled, True otherwise

        Example:
            for i, item in enumerate(items):
                if not ProgressDialogHelper.update_progress(progress, i + 1, len(items)):
                    break  # User cancelled
                process(item)
        """
        if dialog.wasCanceled():
            return False

        dialog.setMaximum(total)
        dialog.setValue(current)

        if message:
            dialog.setLabelText(message)

        # Process events to keep UI responsive
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        return not dialog.wasCanceled()

    @staticmethod
    def finish_progress(
        dialog: QProgressDialog,
        success_message: Optional[str] = None
    ) -> None:
        """
        Finish and close progress dialog.

        Args:
            dialog: Progress dialog to finish
            success_message: Optional final message to show briefly
        """
        if success_message:
            dialog.setLabelText(success_message)

        # Set to maximum to trigger auto-close if enabled
        if dialog.maximum() > 0:
            dialog.setValue(dialog.maximum())

        dialog.close()


__all__ = ['DialogHelper', 'ProgressDialogHelper']
