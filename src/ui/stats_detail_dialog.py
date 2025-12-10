"""
Detailed stats dialog placeholder for StatCard clicks.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton


class StatsDetailDialog(QDialog):
    def __init__(self, category: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{category.title()} Details")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Details for: {category}"))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
