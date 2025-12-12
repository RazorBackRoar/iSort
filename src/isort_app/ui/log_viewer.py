# ui/log_viewer.py
"""
Log viewer widget with colored output and timestamps.

Provides a read-only text display for log messages with level-based
color formatting (info, success, warning, error, debug).
"""

from datetime import datetime

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit


class LogViewer(QTextEdit):
    """
    Read-only log viewer with colored, timestamped messages.

    Displays log messages with:
    - Timestamp in gray
    - Level badge in color (info=blue, success=green, warning=orange, error=red, debug=gray)
    - Message text in light gray
    """

    COLORS = {
        "info": QColor("#4a9eff"),
        "success": QColor("#22c55e"),
        "warning": QColor("#f59e0b"),
        "error": QColor("#ef4444"),
        "debug": QColor("#888888"),
    }

    def __init__(self):
        super().__init__()

        # Read-only mode
        self.setReadOnly(True)

        # Monospace font
        font = QFont("SF Mono", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

        # Dark background styling
        self.setStyleSheet(
            """
            QTextEdit {
                background-color: #1a1a1a;
                color: #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                border: none;
            }
        """
        )

    def log(self, message: str, level: str = "info") -> None:
        """
        Append a log message with timestamp and level formatting.

        Args:
            message: The log message text
            level: Log level (info, success, warning, error, debug)
        """
        # Generate timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Get cursor and move to end
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Insert timestamp (gray)
        timestamp_format = QTextCharFormat()
        timestamp_format.setForeground(QColor("#666666"))
        cursor.insertText(f"[{timestamp}] ", timestamp_format)

        # Insert level badge (colored, bold, 8-char width)
        level_format = QTextCharFormat()
        level_format.setForeground(self.COLORS.get(level, self.COLORS["info"]))
        level_format.setFontWeight(QFont.Weight.Bold)
        level_badge = f"{level.upper():<8}"
        cursor.insertText(level_badge, level_format)

        # Insert message (light gray)
        message_format = QTextCharFormat()
        message_format.setForeground(QColor("#cccccc"))
        cursor.insertText(f" {message}\n", message_format)

        # Update cursor and ensure visible
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


__all__ = ["LogViewer"]
