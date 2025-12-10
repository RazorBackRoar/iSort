"""
Detailed stats dialog shown when stat cards are clicked.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)


class StatsDetailDialog(QDialog):
    def __init__(self, category: str, count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{category.title()} Details")
        self.resize(420, 300)

        layout = QVBoxLayout(self)

        summary = QLabel(f"Items in category '{category}': {count}")
        summary.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(summary)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Property", "Value"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        # Basic properties; extend later when more detail is available.
        rows = [("Category", category.title()), ("Count", str(count))]
        table.setRowCount(len(rows))
        for row_idx, (k, v) in enumerate(rows):
            table.setItem(row_idx, 0, QTableWidgetItem(k))
            table.setItem(row_idx, 1, QTableWidgetItem(v))

        layout.addWidget(table)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
