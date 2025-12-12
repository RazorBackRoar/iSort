"""
iSort - Media File Organization Tool
Entry point for the PySide6 GUI application.
"""

import logging
import os
import sys
from pathlib import Path

# Ensure src/ is on sys.path for absolute imports when launched via entry point
SRC_DIR = Path(__file__).resolve().parent.parent  # src/ directory
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox


def setup_dark_theme(app: QApplication) -> None:
    """Configure dark theme palette for the application."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(74, 158, 255))
    app.setPalette(palette)


def main() -> int:
    """Initialize and run the application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    QApplication.setApplicationName("iSort")
    QApplication.setOrganizationName("iSort")
    QApplication.setOrganizationDomain("com.isort.app")
    QApplication.setApplicationDisplayName("iSort - Apple Device File Organizer")
    if hasattr(Qt.ApplicationAttribute, "AA_DontShowIconsInMenus"):
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False
        )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    setup_dark_theme(app)

    # Optional dependency warning for external tools
    try:
        from isort_app.core.metadata import check_dependencies

        # Ensure Homebrew paths are visible when launched from Finder
        hb_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
        existing_path = os.environ.get("PATH", "")
        expanded_path = os.pathsep.join(
            list(
                dict.fromkeys(
                    hb_paths + [p for p in existing_path.split(os.pathsep) if p]
                )
            )
        )
        os.environ["PATH"] = expanded_path

        missing = check_dependencies()
        if missing:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Missing Dependencies")
            msg.setText(
                "Optional tools not found: "
                + ", ".join(missing)
                + "\n\nSome features may not work.\nInstall with:\n"
                "brew install exiftool mediainfo"
            )
            msg.exec()
    except Exception:
        logging.exception("Dependency check failed")

    # Initialize resources
    from isort_app.ui.resources import ResourceManager

    from isort_app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
