# ui/main_window.py
"""
Main application window for iSort - matches the design mockups exactly.
"""

import os
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QThread, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.metadata import check_dependencies
from core.organizer import check_disk_space, MIN_DISK_SPACE_MB
from core.worker import OrganizeWorker
from utils.checkpoint import CheckpointManager
from utils.error_log import ErrorLogger
from utils.manifest import ManifestUndoer, ManifestInfo, UndoResult
from .log_viewer import LogViewer
from .stats_widget import StatsWidget


class StatCard(QFrame):
    """A stat card widget with colored left border, value, label, and icon."""

    def __init__(self, label: str, icon: str, border_color: str, parent=None):
        super().__init__(parent)
        self.border_color = border_color
        self.value_label = QLabel("0")
        self.text_label = QLabel(label)
        self.icon_label = QLabel(icon)

        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(
            f"""
            StatCard {{
                background-color: #2d2d2d;
                border-radius: 12px;
                border-left: 4px solid {self.border_color};
            }}
        """
        )
        self.setFixedHeight(90)
        self.setMinimumWidth(140)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        # Left side: value and label
        left_layout = QVBoxLayout()
        left_layout.setSpacing(4)

        self.value_label.setStyleSheet(
            """
            QLabel {
                font-size: 32px;
                font-weight: bold;
                color: #ffffff;
            }
        """
        )

        self.text_label.setStyleSheet(
            """
            QLabel {
                font-size: 13px;
                color: #888888;
            }
        """
        )

        left_layout.addWidget(self.value_label)
        left_layout.addWidget(self.text_label)

        # Right side: icon
        self.icon_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 24px;
                color: {self.border_color};
            }}
        """
        )
        self.icon_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addLayout(left_layout, 1)
        layout.addWidget(self.icon_label)

    def set_value(self, value: int):
        self.value_label.setText(str(value))


class UndoWorker(QThread):
    """Background worker for undo operations."""

    progress = Signal(int, int)
    log_message = Signal(str)
    error_log = Signal(str, str, str)
    finished = Signal(UndoResult)

    def __init__(self, manifest_path: Path, undoer: ManifestUndoer):
        super().__init__()
        self.manifest_path = manifest_path
        self.undoer = undoer
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def run(self):
        result = self.undoer.undo_manifest(
            self.manifest_path,
            progress_callback=lambda c, t: self.progress.emit(c, t),
            log_callback=lambda m: self.log_message.emit(m),
            error_log_callback=lambda c, f, e: self.error_log.emit(c, f, e),
            should_cancel=lambda: self._cancel_requested,
        )
        self.finished.emit(result)


class MainWindow(QMainWindow):
    """Main application window for iSort file organizer."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("iSort - Apple Device File Organizer")
        self.setMinimumSize(1050, 720)

        self.worker = None
        self.stats = {
            "files_moved": 0,
            "iphone_photos": 0,
            "iphone_videos": 0,
            "screenshots": 0,
            "snapchat": 0,
            "non_apple": 0,
            "errors": 0,
        }

        self._setup_ui()
        self._connect_signals()
        self._check_external_tools()

    def _check_external_tools(self) -> None:
        """Check for missing external tools and warn user."""
        missing = check_dependencies()
        if missing:
            QMessageBox.warning(
                self,
                "Missing Dependencies",
                f"The following external tools are missing:\n\n"
                f"{', '.join(missing)}\n\n"
                "Metadata extraction quality may be degraded.\n"
                "Please install them via Homebrew:\n"
                "brew install exiftool mdls mediainfo",
            )

    def _setup_ui(self) -> None:
        """Set up the main UI layout matching the mockups."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setStyleSheet("background-color: #1a1a1a;")

        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(24)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # === Header Section ===
        header_layout = QHBoxLayout()

        # App icon and title
        title_layout = QHBoxLayout()
        app_icon = QLabel("💻")
        app_icon.setStyleSheet("font-size: 36px; color: #4a9eff;")

        title_text = QVBoxLayout()
        app_title = QLabel("iSort")
        app_title.setStyleSheet("font-size: 28px; font-weight: bold; color: #ffffff;")
        app_subtitle = QLabel("Apple Device File Organizer")
        app_subtitle.setStyleSheet("font-size: 14px; color: #888888;")
        title_text.addWidget(app_title)
        title_text.addWidget(app_subtitle)
        title_text.setSpacing(2)

        title_layout.addWidget(app_icon)
        title_layout.addLayout(title_text)
        title_layout.addStretch()

        # Version info
        version_layout = QVBoxLayout()
        version_layout.setAlignment(Qt.AlignRight)
        version_label = QLabel("v10.0")
        version_label.setStyleSheet("font-size: 14px; color: #888888;")
        engine_label = QLabel("Confidence Scoring Engine")
        engine_label.setStyleSheet("font-size: 12px; color: #666666;")
        version_layout.addWidget(version_label, alignment=Qt.AlignRight)
        version_layout.addWidget(engine_label, alignment=Qt.AlignRight)

        header_layout.addLayout(title_layout)
        header_layout.addLayout(version_layout)
        main_layout.addLayout(header_layout)

        # === Source Folder Section ===
        source_frame = QFrame()
        source_frame.setStyleSheet(
            """
            QFrame {
                background-color: #2d2d2d;
                border-radius: 12px;
            }
        """
        )
        source_layout = QVBoxLayout(source_frame)
        source_layout.setContentsMargins(16, 12, 16, 12)

        source_title = QLabel("Source Folder")
        source_title.setStyleSheet(
            "font-size: 13px; color: #888888; font-weight: bold;"
        )

        folder_row = QHBoxLayout()
        folder_icon = QLabel("📁")
        folder_icon.setStyleSheet("font-size: 18px;")

        self.source_path = QLabel("No folder selected")
        self.source_path.setStyleSheet(
            """
            QLabel {
                font-size: 14px;
                color: #888888;
                font-family: 'SF Mono', 'Menlo', monospace;
            }
        """
        )

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #3d3d3d;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """
        )

        folder_row.addWidget(folder_icon)
        folder_row.addWidget(self.source_path, 1)
        folder_row.addWidget(self.browse_btn)

        source_layout.addWidget(source_title)
        source_layout.addLayout(folder_row)
        main_layout.addWidget(source_frame)

        # === Options Section ===
        options_frame = QFrame()
        options_frame.setStyleSheet(
            """
            QFrame {
                background-color: #2d2d2d;
                border-radius: 12px;
            }
        """
        )
        options_layout = QVBoxLayout(options_frame)
        options_layout.setContentsMargins(16, 12, 16, 12)

        options_title = QLabel("Options")
        options_title.setStyleSheet(
            "font-size: 13px; color: #888888; font-weight: bold;"
        )

        options_row = QHBoxLayout()
        options_row.setSpacing(24)

        # Mode selector
        mode_layout = QHBoxLayout()
        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("font-size: 14px; color: #ffffff;")

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(
            [
                "Organize Files",
                "Preview Only (Dry Run)",
                "Generate Inventory",
                "Find Duplicates",
            ]
        )
        self.mode_combo.setStyleSheet(
            """
            QComboBox {
                background-color: #3d3d3d;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                min-width: 160px;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #888888;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #3d3d3d;
                color: #ffffff;
                selection-background-color: #4a9eff;
            }
        """
        )

        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo)

        # Checkboxes
        self.verify_hash_cb = QCheckBox("Verify hashes after move")
        self.verify_hash_cb.setChecked(True)
        self.verify_hash_cb.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #ffffff;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #555555;
                background-color: #2d2d2d;
            }
            QCheckBox::indicator:checked {
                background-color: #4a9eff;
                border-color: #4a9eff;
            }
        """
        )

        self.resume_cb = QCheckBox("Resume from checkpoint")
        self.resume_cb.setStyleSheet(self.verify_hash_cb.styleSheet())

        options_row.addLayout(mode_layout)
        options_row.addWidget(self.verify_hash_cb)
        options_row.addWidget(self.resume_cb)
        options_row.addStretch()

        options_layout.addWidget(options_title)
        options_layout.addLayout(options_row)
        main_layout.addWidget(options_frame)

        # === Progress Section ===
        progress_frame = QFrame()
        progress_frame.setStyleSheet(
            """
            QFrame {
                background-color: #2d2d2d;
                border-radius: 12px;
            }
        """
        )
        progress_layout = QVBoxLayout(progress_frame)
        progress_layout.setContentsMargins(16, 12, 16, 12)

        progress_header = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 14px; color: #ffffff;")

        self.progress_text = QLabel("0 / 100")
        self.progress_text.setStyleSheet(
            "font-size: 14px; color: #888888; font-family: 'SF Mono', monospace;"
        )

        progress_header.addWidget(self.status_label)
        progress_header.addStretch()
        progress_header.addWidget(self.progress_text)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: none;
                border-radius: 6px;
                background-color: #3d3d3d;
                height: 12px;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a9eff, stop:1 #7c3aed
                );
            }
        """
        )

        progress_layout.addLayout(progress_header)
        progress_layout.addWidget(self.progress_bar)
        main_layout.addWidget(progress_frame)

        # === Stats Cards Grid ===
        stats_grid = QGridLayout()
        stats_grid.setSpacing(12)

        # Row 1: Files Moved, iPhone Photos, iPhone Videos, Screenshots
        self.card_files_moved = StatCard("Files Moved", "✓", "#4a9eff")
        self.card_iphone_photos = StatCard("iPhone Photos", "💻", "#22c55e")
        self.card_iphone_videos = StatCard("iPhone Videos", "💻", "#06b6d4")
        self.card_screenshots = StatCard("Screenshots", "🖼", "#f59e0b")

        stats_grid.addWidget(self.card_files_moved, 0, 0)
        stats_grid.addWidget(self.card_iphone_photos, 0, 1)
        stats_grid.addWidget(self.card_iphone_videos, 0, 2)
        stats_grid.addWidget(self.card_screenshots, 0, 3)

        # Row 2: Snapchat, Non-Apple, Errors
        self.card_snapchat = StatCard("Snapchat", "👻", "#eab308")
        self.card_non_apple = StatCard("Non-Apple", "📄", "#ec4899")
        self.card_errors = StatCard("Errors", "⚠", "#ef4444")

        stats_grid.addWidget(self.card_snapchat, 1, 0)
        stats_grid.addWidget(self.card_non_apple, 1, 1)
        stats_grid.addWidget(self.card_errors, 1, 2)

        main_layout.addLayout(stats_grid)

        # === Tabbed View ===
        tab_frame = QFrame()
        tab_frame.setStyleSheet(
            """
            QFrame {
                background-color: #2d2d2d;
                border-radius: 12px;
            }
        """
        )
        tab_layout = QVBoxLayout(tab_frame)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background-color: #2d2d2d;
                border-radius: 12px;
            }
            QTabBar::tab {
                background-color: transparent;
                color: #888888;
                padding: 10px 20px;
                font-size: 14px;
                border: none;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #4a9eff;
                color: #ffffff;
                border-radius: 8px;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
            }
        """
        )

        # Log tab
        self.log_viewer = LogViewer()
        self.tab_widget.addTab(self.log_viewer, "📋 Log")

        # Statistics tab
        self.stats_widget = StatsWidget()
        self.tab_widget.addTab(self.stats_widget, "📊 Statistics")

        # Results tab
        self.results_viewer = QTextEdit()
        self.results_viewer.setReadOnly(True)
        self.results_viewer.setPlaceholderText("No logs yet...")
        self.results_viewer.setStyleSheet(
            """
            QTextEdit {
                background-color: #1a1a1a;
                color: #888888;
                border: none;
                border-radius: 8px;
                padding: 16px;
                font-family: 'SF Mono', 'Menlo', monospace;
                font-size: 14px;
            }
        """
        )
        self.tab_widget.addTab(self.results_viewer, "📁 Results")

        tab_layout.addWidget(self.tab_widget)
        main_layout.addWidget(tab_frame, 1)

        # === Action Buttons ===
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.undo_btn = QPushButton("↻  Undo Last Run")
        self.undo_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #ef4444;
                border: 2px solid #ef4444;
                border-radius: 8px;
                padding: 12px 24px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.1);
            }
        """
        )

        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #22c55e;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px 32px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #16a34a;
            }
            QPushButton:disabled {
                background-color: #4a4a4a;
            }
        """
        )

        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #ef4444;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px 32px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
            QPushButton:disabled {
                background-color: #4a4a4a;
            }
        """
        )
        self.stop_btn.hide()

        button_layout.addWidget(self.undo_btn)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)

        main_layout.addLayout(button_layout)

    def _connect_signals(self) -> None:
        """Connect widget signals to slots."""
        self.browse_btn.clicked.connect(self._browse_folder)
        self.start_btn.clicked.connect(self._start_processing)
        self.stop_btn.clicked.connect(self._stop_processing)
        self.undo_btn.clicked.connect(self._undo_last_run)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)

    @Slot()
    def _browse_folder(self) -> None:
        """Open folder selection dialog."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Source Folder",
            os.path.expanduser("~"),
        )

        if folder:
            self.source_path.setText(folder)
            self.source_path.setStyleSheet(
                """
                QLabel {
                    font-size: 14px;
                    color: #ffffff;
                    font-family: 'SF Mono', 'Menlo', monospace;
                }
            """
            )
            self.log_viewer.log(f"Selected folder: {folder}", "info")
            self._scan_folder_preview(folder)

    def _scan_folder_preview(self, folder: str) -> None:
        """Scan folder and update preview information."""
        file_count = 0
        for _ in self._iter_files(folder):
            file_count += 1

        self.progress_bar.setMaximum(file_count)
        self.progress_bar.setValue(0)
        self.progress_text.setText(f"0 / {file_count}")
        self.log_viewer.log(f"Found {file_count:,} files to process", "info")

    def _iter_files(self, folder: str):
        """Iterate over non-hidden files in folder tree."""
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for filename in files:
                if not filename.startswith("."):
                    yield os.path.join(root, filename)

    @Slot(str)
    def _on_mode_changed(self, mode_text: str) -> None:
        """Handle mode selection changes."""
        is_preview = mode_text == "Preview Only (Dry Run)"
        if is_preview:
            self.resume_cb.setChecked(False)
            self.resume_cb.setEnabled(False)
        else:
            self.resume_cb.setEnabled(True)

    def _toggle_controls(self, processing: bool) -> None:
        """Toggle UI controls based on processing state."""
        self.start_btn.setEnabled(not processing)
        self.start_btn.setVisible(not processing)
        self.stop_btn.setEnabled(processing)
        self.stop_btn.setVisible(processing)
        self.undo_btn.setEnabled(not processing)
        self.browse_btn.setEnabled(not processing)
        self.mode_combo.setEnabled(not processing)
        self.verify_hash_cb.setEnabled(not processing)

        if not processing:
            self._on_mode_changed(self.mode_combo.currentText())
        else:
            self.resume_cb.setEnabled(False)

    def _update_stats_cards(self, stats: dict) -> None:
        """Update all stat cards with current values."""
        self.card_files_moved.set_value(stats.get("files_moved", 0))
        self.card_iphone_photos.set_value(stats.get("iphone_photos", 0))
        self.card_iphone_videos.set_value(stats.get("iphone_videos", 0))
        self.card_screenshots.set_value(stats.get("screenshots", 0))
        self.card_snapchat.set_value(stats.get("snapchat", 0))
        self.card_non_apple.set_value(stats.get("non_apple", 0))
        self.card_errors.set_value(stats.get("errors", 0))

    @Slot()
    def _start_processing(self) -> None:
        """Start the file processing operation."""
        folder = self.source_path.text()

        if not folder or folder == "No folder selected":
            QMessageBox.warning(
                self,
                "No Folder Selected",
                "Please select a source folder to process.",
            )
            return

        if not os.path.exists(folder):
            QMessageBox.warning(
                self,
                "Invalid Folder",
                "The selected folder does not exist.",
            )
            return

        mode = self.mode_combo.currentText()
        dry_run = mode == "Preview Only (Dry Run)"

        self._toggle_controls(processing=True)
        self.status_label.setText("Processing...")

        # Reset stats
        self.stats = {k: 0 for k in self.stats}
        self._update_stats_cards(self.stats)

        # Check for checkpoint
        if self.resume_cb.isChecked():
            checkpoint_mgr = CheckpointManager()
            if checkpoint_mgr.exists():
                _, _, _, is_invalid = checkpoint_mgr.load()
                if is_invalid:
                    QMessageBox.information(
                        self,
                        "Invalid Checkpoint",
                        "The existing checkpoint file is corrupted.\n\n"
                        "Processing will start from the beginning.",
                    )
                    checkpoint_mgr.clear()

        # Check disk space
        if mode == "Organize Files":
            is_sufficient, available_mb = check_disk_space(Path(folder))
            if not is_sufficient:
                reply = QMessageBox.warning(
                    self,
                    "Low Disk Space",
                    f"Low disk space detected: {available_mb} MB available.\n\n"
                    f"Minimum recommended: {MIN_DISK_SPACE_MB} MB.\n\n"
                    "Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    self._toggle_controls(processing=False)
                    self.status_label.setText("Ready")
                    return

        self.progress_bar.setValue(0)
        self.log_viewer.log("Starting processing...", "info")

        # Create worker
        self.worker = OrganizeWorker(
            folder=folder,
            mode=self.mode_combo.currentText(),
            verify_hash=self.verify_hash_cb.isChecked(),
            dry_run=dry_run,
            resume=self.resume_cb.isChecked(),
        )

        # Connect signals
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._on_log)
        self.worker.file_processed.connect(self._on_file_processed)
        self.worker.stats_updated.connect(self._on_stats_updated)
        self.worker.finished.connect(self._on_finished)

        self.worker.start()

    @Slot()
    def _stop_processing(self) -> None:
        """Request stop of current processing operation."""
        if self.worker is not None:
            self.worker.request_stop()
            self.log_viewer.log("Stop requested, finishing current file...", "warning")

    @Slot(int, int, str)
    def _on_progress(self, current: int, total: int, eta: str) -> None:
        """Handle progress updates from worker."""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_text.setText(f"{current} / {total}")

    @Slot(str, str)
    def _on_log(self, message: str, level: str) -> None:
        """Handle log messages from worker."""
        self.log_viewer.log(message, level)

    @Slot(str, str, str)
    def _on_file_processed(self, filename: str, destination: str, status: str) -> None:
        """Handle file processed notifications from worker."""
        self.status_label.setText(f"Processing: {filename}")

    @Slot(dict)
    def _on_stats_updated(self, stats: dict) -> None:
        """Handle stats updates from worker."""
        self.stats.update(stats)
        self._update_stats_cards(self.stats)
        self.stats_widget.update_stats(stats)

    @Slot(dict)
    def _on_finished(self, stats: dict) -> None:
        """Handle processing completion."""
        self._toggle_controls(processing=False)
        self.status_label.setText("Ready")

        self._update_stats_cards(stats)
        self.stats_widget.update_stats(stats)

        stopped_by_user = stats.get("stopped_by_user", False)
        error_count = stats.get("errors", 0)

        if stopped_by_user:
            self.log_viewer.log("Processing cancelled by user", "warning")
            QMessageBox.information(
                self,
                "Processing Cancelled",
                f"Processing was cancelled by user.\n\n"
                f"Files processed: {stats.get('files_moved', 0)}\n\n"
                "A checkpoint may be available for resume.",
            )
        elif error_count > 0:
            self.log_viewer.log(
                f"Processing complete with {error_count} error(s)", "warning"
            )
            QMessageBox.warning(
                self,
                "Processing Complete with Errors",
                f"Processing completed with {error_count} error(s).\n\n"
                "Check the Log tab for details.",
            )
        else:
            self.log_viewer.log("Processing complete!", "success")

        self._show_results_summary(stats)

    def _show_results_summary(self, stats: dict) -> None:
        """Display formatted results summary."""
        mode = stats.get("mode", "")
        stopped_by_user = stats.get("stopped_by_user", False)

        if mode == "Generate Inventory":
            summary = [
                "╔════════════════════════════════════════════════════════════╗",
                "║                   INVENTORY COMPLETE                       ║",
                "╠════════════════════════════════════════════════════════════╣",
                f"║  Total Files:        {stats.get('total_files', 0):<38}║",
                f"║  Total Size:         {stats.get('total_size_human', 'N/A'):<38}║",
                f"║  Directories:        {stats.get('directories', 0):<38}║",
                f"║  Errors:             {stats.get('errors', 0):<38}║",
                "╚════════════════════════════════════════════════════════════╝",
            ]
        elif mode == "Find Duplicates":
            summary = [
                "╔════════════════════════════════════════════════════════════╗",
                "║                 DUPLICATE DETECTION COMPLETE               ║",
                "╠════════════════════════════════════════════════════════════╣",
                f"║  Files Scanned:      {stats.get('total_files', 0):<38}║",
                f"║  Duplicate Groups:   {stats.get('duplicate_groups', 0):<38}║",
                f"║  Duplicate Files:    {stats.get('duplicate_files', 0):<38}║",
                f"║  Wasted Space:       {stats.get('wasted_space_human', 'N/A'):<38}║",
                "╚════════════════════════════════════════════════════════════╝",
            ]
        else:
            header = (
                "PROCESSING CANCELLED" if stopped_by_user else "PROCESSING COMPLETE"
            )
            summary = [
                "╔════════════════════════════════════════════════════════════╗",
                f"║{header:^60}║",
                "╠════════════════════════════════════════════════════════════╣",
                f"║  Files Moved:        {stats.get('files_moved', 0):<38}║",
                f"║  iPhone Photos:      {stats.get('iphone_photos', 0):<38}║",
                f"║  iPhone Videos:      {stats.get('iphone_videos', 0):<38}║",
                f"║  Screenshots:        {stats.get('screenshots', 0):<38}║",
                f"║  Snapchat:           {stats.get('snapchat', 0):<38}║",
                f"║  Non-Apple:          {stats.get('non_apple', 0):<38}║",
                f"║  Errors:             {stats.get('errors', 0):<38}║",
                "╚════════════════════════════════════════════════════════════╝",
            ]

        self.results_viewer.setText("\n".join(summary))
        self.tab_widget.setCurrentWidget(self.results_viewer)

    @Slot()
    def _undo_last_run(self) -> None:
        """Undo the last processing run using manifest."""
        undoer = ManifestUndoer()
        manifests = undoer.list_manifests()

        if not manifests:
            QMessageBox.information(
                self,
                "No Manifests Found",
                "No manifest files found on Desktop.\n\n"
                "Manifests are created when you run 'Organize Files' mode.",
            )
            return

        manifest_items = [
            f"{m.formatted_date} ({self._count_manifest_lines(m.path)} files)"
            for m in manifests
        ]

        selected, ok = QInputDialog.getItem(
            self,
            "Select Manifest to Undo",
            "Choose a manifest file to undo:",
            manifest_items,
            0,
            False,
        )

        if not ok or not selected:
            return

        selected_idx = manifest_items.index(selected)
        manifest = manifests[selected_idx]
        file_count = self._count_manifest_lines(manifest.path)

        reply = QMessageBox.question(
            self,
            "Confirm Undo",
            f"Undo will restore {file_count} files to their original locations.\n\n"
            f"Manifest: {manifest.formatted_date}\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._toggle_controls(processing=True)

        progress = QProgressDialog(
            "Undoing file moves...",
            "Cancel",
            0,
            file_count,
            self,
        )
        progress.setWindowTitle("Undo in Progress")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        self.log_viewer.log(f"Starting undo of {file_count} files...", "info")

        undo_error_logger = ErrorLogger()
        undo_error_logger.initialize()

        def on_error(context: str, file: str, error: str) -> None:
            self.log_viewer.log(f"{context}: {file} - {error}", "error")
            undo_error_logger.log_error(context, file, error)

        self.undo_worker = UndoWorker(manifest.path, undoer)
        self.undo_worker.progress.connect(progress.setValue)
        self.undo_worker.progress.connect(
            lambda c, t: progress.setLabelText(f"Restoring file {c} of {t}...")
        )
        self.undo_worker.log_message.connect(lambda m: self.log_viewer.log(m, "info"))
        self.undo_worker.error_log.connect(on_error)

        progress.canceled.connect(self.undo_worker.request_cancel)

        def on_finished(result: UndoResult) -> None:
            progress.close()
            undo_error_logger.close()
            self._toggle_controls(processing=False)

            if progress.wasCanceled():
                self.log_viewer.log("Undo cancelled by user", "warning")
                QMessageBox.warning(
                    self,
                    "Undo Cancelled",
                    f"Undo was cancelled.\n\n"
                    f"Restored: {result.success_count} files\n"
                    f"Remaining: {result.total_count - result.success_count} files",
                )
            elif result.failed_count > 0:
                self.log_viewer.log(
                    f"Undo completed with errors: {result.success_count} restored, "
                    f"{result.failed_count} failed",
                    "warning",
                )
                QMessageBox.warning(
                    self,
                    "Undo Completed with Errors",
                    f"Undo completed with some errors.\n\n"
                    f"Restored: {result.success_count} files\n"
                    f"Failed: {result.failed_count} files\n\n"
                    "Check the log for details.",
                )
            else:
                self.log_viewer.log(
                    f"Undo complete: {result.success_count} files restored", "success"
                )
                QMessageBox.information(
                    self,
                    "Undo Complete",
                    f"Successfully restored {result.success_count} files "
                    f"to their original locations.",
                )

        self.undo_worker.finished.connect(on_finished)
        self.undo_worker.start()

    def _count_manifest_lines(self, path: Path) -> int:
        """Count number of file entries in a manifest."""
        try:
            with open(path, "r") as f:
                return sum(1 for line in f if line.strip() and not line.startswith("#"))
        except Exception:
            return 0
