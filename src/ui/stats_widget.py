# ui/stats_widget.py
"""
Statistics widget with color-coded stat cards.

Displays real-time statistics in a grid of styled cards,
each with a value and label.
"""

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QVBoxLayout, QWidget


class StatsWidget(QWidget):
    """
    Grid of color-coded statistic cards.

    Displays 7 stats: files_moved, iphone_photos, iphone_videos,
    screenshots, snapchat, non_apple, errors.
    """

    def __init__(self):
        super().__init__()

        # Main grid layout
        layout = QGridLayout(self)
        layout.setSpacing(16)

        # Stats configuration: (key, label, color)
        stats = [
            ("files_moved", "Files Moved", "#4a9eff"),
            ("iphone_photos", "iPhone Photos", "#22c55e"),
            ("iphone_videos", "iPhone Videos", "#8b5cf6"),
            ("screenshots", "Screenshots", "#f59e0b"),
            ("snapchat", "Snapchat", "#fffc00"),
            ("non_apple", "Non-Apple", "#ec4899"),
            ("errors", "Errors", "#ef4444"),
        ]

        # Store value labels for updates
        self.stat_labels: dict[str, QLabel] = {}

        # Create stat cards in 3-column grid
        for i, (key, label, color) in enumerate(stats):
            card, value_label = self._create_stat_card(label, color)
            self.stat_labels[key] = value_label

            row, col = divmod(i, 3)
            layout.addWidget(card, row, col)

    def _create_stat_card(self, label: str, color: str) -> tuple[QGroupBox, QLabel]:
        """
        Create a styled stat card.

        Args:
            label: Display name for the stat
            color: Accent color (hex string)

        Returns:
            Tuple of (card widget, value label for updates)
        """
        card = QGroupBox()
        card.setStyleSheet(
            f"""
            QGroupBox {{
                background-color: #2d2d2d;
                border-radius: 12px;
                padding: 16px;
                border-left: 4px solid {color};
                border-top: none;
                border-right: none;
                border-bottom: none;
            }}
        """
        )

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(4)

        # Value label (large, bold, colored)
        value_label = QLabel("0")
        value_label.setObjectName("value")
        value_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {color};
            }}
        """
        )

        # Name label (small, gray)
        name_label = QLabel(label)
        name_label.setStyleSheet(
            """
            QLabel {
                font-size: 12px;
                color: #888888;
            }
        """
        )

        card_layout.addWidget(value_label)
        card_layout.addWidget(name_label)

        return card, value_label

    @Slot(dict)
    def update_stats(self, stats: dict) -> None:
        """
        Update stat card values from a stats dictionary.

        Args:
            stats: Dictionary with stat keys and integer values
        """
        for key, label in self.stat_labels.items():
            if key in stats:
                label.setText(f"{stats[key]:,}")


__all__ = ["StatsWidget"]
