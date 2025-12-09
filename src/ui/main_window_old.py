# ui/main_window.py
"""
Main application window for iSort.

Provides the primary user interface with folder selection, mode selection,
options, progress tracking, tabbed log/stats/results views, and action buttons.
"""

import os
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QThread, Signal, QUrl
from PySide6.QtGui import QAction, QFont, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.metadata import check_dependencies
from core.organizer import check_disk_space, MIN_DISK_SPACE_MB
from core.worker import OrganizeWorker
from ui.resources import ResourceManager
from utils.checkpoint import CheckpointManager
from utils.error_log import ErrorLogger
from utils.manifest import ManifestUndoer, ManifestInfo, UndoResult
from .log_viewer import LogViewer
from .stats_widget import StatsWidget


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
    """
    Main application window for iSort file organizer.

    Features:
    - Folder selection with preview
    - Mode selection (Organize, Dry Run, Inventory, Duplicates, Compare)
    - Options (hash verification, resume from checkpoint)
    - Progress tracking with ETA
    - Tabbed view (Log, Statistics, Results)
    - Toolbar and statusbar
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("iSort - Apple Device File Organizer")
        self.setMinimumSize(900, 650)

        # Worker thread placeholder (Phase 8: OrganizeWorker)
        self.worker = None

        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()

        # Check dependencies on startup
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
        """Set up the main UI layout and widgets."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # === Source Folder Section ===
        source_group = QGroupBox("Source Folder")
        source_layout = QHBoxLayout(source_group)

        self.source_path = QLabel("No folder selected")
        self.source_path.setStyleSheet(
            """
            QLabel {
                background-color: #2d2d2d;
                padding: 8px;
                border-radius: 8px;
                font-family: 'SF Mono', monospace;
            }
        """
        )

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setFixedWidth(100)

        source_layout.addWidget(self.source_path, 1)
        source_layout.addWidget(self.browse_btn)

        main_layout.addWidget(source_group)

        # === Options Section ===
        options_group = QGroupBox("Options")
        options_layout = QGridLayout(options_group)

        # Mode combo
        mode_label = QLabel("Mode:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(
            [
                "Organize Files",
                "Preview Only (Dry Run)",
                "Generate Inventory",
                "Find Duplicates",
                "Compare Folders (coming soon)",
            ]
        )
        self.mode_combo.setToolTip(
            "Select operation mode.\n"
            "Note: Compare Folders is planned but not yet available."
        )
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)

        # Checkboxes
        self.verify_hash_cb = QCheckBox("Verify file hashes after move")
        self.verify_hash_cb.setChecked(True)

        self.resume_cb = QCheckBox("Resume from checkpoint if available")
        self.resume_cb.setToolTip(
            "If checked, resumes from the last saved progress.\n"
            "Checkpoints are saved roughly every 10 files.\n"
            "Stopping between checkpoints may re-process a small number of files."
        )

        options_layout.addWidget(mode_label, 0, 0)
        options_layout.addWidget(self.mode_combo, 0, 1)
        options_layout.addWidget(self.verify_hash_cb, 1, 0, 1, 2)
        options_layout.addWidget(self.resume_cb, 2, 0, 1, 2)

        main_layout.addWidget(options_group)

        # === Progress Section ===
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: none;
                border-radius: 12px;
                background-color: #2d2d2d;
                height: 24px;
                text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 12px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a9eff, stop:1 #7c3aed
                );
            }
        """
        )

        status_row = QHBoxLayout()
        self.current_file_label = QLabel("Ready")
        self.current_file_label.setStyleSheet("color: #888888;")

        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("color: #4a9eff;")
        self.eta_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        status_row.addWidget(self.current_file_label, 1)
        status_row.addWidget(self.eta_label)

        progress_layout.addWidget(self.progress_bar)
        progress_layout.addLayout(status_row)

        main_layout.addWidget(progress_group)

        # === Tabbed View ===
        self.tab_widget = QTabWidget()

        # Log tab
        self.log_viewer = LogViewer()
        self.tab_widget.addTab(self.log_viewer, "Log")

        # Statistics tab
        self.stats_widget = StatsWidget()
        self.tab_widget.addTab(self.stats_widget, "Statistics")

        # Results tab
        self.results_viewer = QTextEdit()
        self.results_viewer.setReadOnly(True)
        self.results_viewer.setFont(QFont("SF Mono", 11))
        self.results_viewer.setStyleSheet(
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
        self.tab_widget.addTab(self.results_viewer, "Results")

        main_layout.addWidget(self.tab_widget, 1)

        # === Action Buttons ===
        button_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start")
        self.start_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #22c55e;
                color: white;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #16a34a;
            }
            QPushButton:disabled {
                background-color: #4a4a4a;
            }
        """
        )

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #ef4444;
                color: white;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
            QPushButton:disabled {
                background-color: #4a4a4a;
            }
        """
        )

        self.undo_btn = QPushButton("Undo Last Run")
        self.undo_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #f59e0b;
                color: white;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #d97706;
            }
        """
        )

        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.undo_btn)

        main_layout.addLayout(button_layout)

    def _setup_toolbar(self) -> None:
        """Set up the application toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Open folder action
        open_action = QAction("📂 Open Folder", self)
        open_action.triggered.connect(self._browse_folder)
        toolbar.addAction(open_action)

        toolbar.addSeparator()

        # View manifests action
        manifests_action = QAction("View Manifests", self)
        manifests_action.triggered.connect(self._view_manifests)
        toolbar.addAction(manifests_action)

        # Settings action
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self._open_settings)
        toolbar.addAction(settings_action)

        # Help action
        help_action = QAction("Help", self)
        help_action.triggered.connect(
            lambda: QMessageBox.information(
                self, "About iSort", "iSort - Apple Device File Organizer\nVersion 1.0"
            )
        )
        toolbar.addAction(help_action)

    def _setup_statusbar(self) -> None:
        """Set up the status bar."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready")

    def _connect_signals(self) -> None:
        """Connect widget signals to slots."""
        self.browse_btn.clicked.connect(self._browse_folder)
        self.start_btn.clicked.connect(self._start_processing)
        self.stop_btn.clicked.connect(self._stop_processing)
        self.undo_btn.clicked.connect(self._undo_last_run)

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
            self.log_viewer.log(f"Selected folder: {folder}", "info")
            self._scan_folder_preview(folder)

    def _scan_folder_preview(self, folder: str) -> None:
        """Scan folder and update preview information."""
        file_count = 0
        for _ in self._iter_files(folder):
            file_count += 1

        self.statusbar.showMessage(f"Found {file_count:,} files in selected folder")
        self.progress_bar.setMaximum(file_count)
        self.progress_bar.setValue(0)
        self.log_viewer.log(f"Found {file_count:,} files to process", "info")

    def _iter_files(self, folder: str):
        """
        Iterate over non-hidden files in folder tree.

        Yields:
            File paths for all non-hidden files
        """
        for root, dirs, files in os.walk(folder):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for filename in files:
                # Skip hidden files
                if not filename.startswith("."):
                    yield os.path.join(root, filename)

    @Slot(str)
    def _on_mode_changed(self, mode_text: str) -> None:
        """Handle mode selection changes."""
        is_preview = mode_text == "Preview Only (Dry Run)"
        is_compare = "Compare Folders" in mode_text

        # Disable resume for preview and compare modes as they're not applicable
        if is_preview:
            self.resume_cb.setChecked(False)
            self.resume_cb.setEnabled(False)
            self.resume_cb.setToolTip("Resume is not available in Preview mode")
        elif is_compare:
            self.resume_cb.setChecked(False)
            self.resume_cb.setEnabled(False)
            self.resume_cb.setToolTip(
                "Compare Folders is a placeholder mode (coming soon).\n"
                "Resume is not applicable."
            )
        else:
            self.resume_cb.setEnabled(True)
            self.resume_cb.setToolTip(
                "If checked, resumes from the last saved progress.\n"
                "Checkpoints are saved roughly every 10 files.\n"
                "Stopping between checkpoints may re-process a small number of files."
            )

    def _toggle_controls(self, processing: bool) -> None:
        """
        Toggle UI controls based on processing state.

        Args:
            processing: True if processing is active (disable inputs),
                       False if idle (enable inputs).
        """
        # Buttons
        self.start_btn.setEnabled(not processing)
        self.stop_btn.setEnabled(processing)
        self.undo_btn.setEnabled(not processing)
        self.browse_btn.setEnabled(not processing)

        # Inputs
        self.mode_combo.setEnabled(not processing)
        self.verify_hash_cb.setEnabled(not processing)

        # Resume checkbox logic: only enable if not processing AND mode supports it
        if not processing:
            # Re-evaluate mode logic to set correct state
            self._on_mode_changed(self.mode_combo.currentText())
        else:
            self.resume_cb.setEnabled(False)

    @Slot()
    def _start_processing(self) -> None:
        """Start the file processing operation."""
        folder = self.source_path.text()

        # Validate folder selection
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

        # Comment 1: Ensure dry_run is explicitly True for Preview mode
        dry_run = mode == "Preview Only (Dry Run)"
        if dry_run:
            self.log_viewer.log(f"Starting in PREVIEW mode (dry_run={dry_run})", "info")

        # Guard: Compare Folders is not yet implemented - check before toggling controls
        if "Compare Folders" in self.mode_combo.currentText():
            QMessageBox.information(
                self,
                "Feature Not Available",
                "Compare Folders is currently a placeholder and not yet functional.\n\n"
                "This feature requires:\n"
                "  • A second folder selector (Folder B)\n"
                "  • Integration with FolderComparator backend\n\n"
                "It will only emit log messages in its current state.\n\n"
                "For single-folder analysis, use 'Find Duplicates' instead.",
            )
            return

        self._toggle_controls(processing=True)
        self.statusbar.showMessage("Processing...")

        # Check for invalid checkpoint
        if self.resume_cb.isChecked():
            checkpoint_mgr = CheckpointManager()
            if checkpoint_mgr.exists():
                _, _, _, is_invalid = checkpoint_mgr.load()
                if is_invalid:
                    QMessageBox.information(
                        self,
                        "Invalid Checkpoint",
                        "The existing checkpoint file is corrupted or incompatible.\n\n"
                        "Processing will start from the beginning.",
                    )
                    checkpoint_mgr.clear()

        # Check disk space (Only for Organize mode which writes files)
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
                    self.statusbar.showMessage("Ready")
                    return

        # Update UI state
        self.progress_bar.setValue(0)
        self.current_file_label.setText("Initializing...")
        self.eta_label.setText("")

        self.log_viewer.log("Starting processing...", "info")

        # Create worker with options
        self.worker = OrganizeWorker(
            folder=folder,
            mode=self.mode_combo.currentText(),
            verify_hash=self.verify_hash_cb.isChecked(),
            dry_run="Preview" in self.mode_combo.currentText(),
            resume=self.resume_cb.isChecked(),
        )

        # Connect signals
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._on_log)
        self.worker.file_processed.connect(self._on_file_processed)
        self.worker.stats_updated.connect(self.stats_widget.update_stats)
        self.worker.finished.connect(self._on_finished)

        # Start worker thread
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
        self.eta_label.setText(eta)

    @Slot(str, str)
    def _on_log(self, message: str, level: str) -> None:
        """Handle log messages from worker."""
        self.log_viewer.log(message, level)

    @Slot(str, str, str)
    def _on_file_processed(self, filename: str, destination: str, status: str) -> None:
        """Handle file processed notifications from worker."""
        self.current_file_label.setText(f"Processing: {filename}")
        self.statusbar.showMessage(f"{filename} → {destination}")

    @Slot(dict)
    def _on_finished(self, stats: dict) -> None:
        """Handle processing completion."""
        self._toggle_controls(processing=False)

        self.current_file_label.setText("Ready")
        self.eta_label.setText("")

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

        self.stats_widget.update_stats(stats)
        self._show_results_summary(stats)

    def _show_results_summary(self, stats: dict) -> None:
        """Display formatted results summary based on mode."""
        mode = stats.get("mode", "")
        stopped_by_user = stats.get("stopped_by_user", False)

        if mode == "Generate Inventory":
            # Inventory-specific summary
            summary = [
                "╔════════════════════════════════════════════════════════════╗",
                "║                   INVENTORY COMPLETE                       ║",
                "╠════════════════════════════════════════════════════════════╣",
                f"║  Total Files:        {stats.get('total_files', 0):<38}║",
                f"║  Total Size:         {stats.get('total_size_human', 'N/A'):<38}║",
                f"║  Directories:        {stats.get('directories', 0):<38}║",
                f"║  Errors:             {stats.get('errors', 0):<38}║",
                "╠════════════════════════════════════════════════════════════╣",
                "║  Output Files:                                             ║",
            ]
            if stats.get("output_txt"):
                txt_path = stats.get("output_txt", "")
                summary.append(f"║  TXT: {txt_path[:52]:<52}║")
            if stats.get("output_csv"):
                csv_path = stats.get("output_csv", "")
                summary.append(f"║  CSV: {csv_path[:52]:<52}║")
            summary.append(
                "╚════════════════════════════════════════════════════════════╝"
            )

        elif mode == "Find Duplicates":
            # Duplicate-specific summary
            summary = [
                "╔════════════════════════════════════════════════════════════╗",
                "║                 DUPLICATE DETECTION COMPLETE               ║",
                "╠════════════════════════════════════════════════════════════╣",
                f"║  Files Scanned:      {stats.get('total_files', 0):<38}║",
                f"║  Duplicate Groups:   {stats.get('duplicate_groups', 0):<38}║",
                f"║  Duplicate Files:    {stats.get('duplicate_files', 0):<38}║",
                f"║  Wasted Space:       {stats.get('wasted_space_human', 'N/A'):<38}║",
                f"║  Errors:             {stats.get('errors', 0):<38}║",
                "╠════════════════════════════════════════════════════════════╣",
                "║  Output Files:                                             ║",
            ]
            if stats.get("output_txt"):
                txt_path = stats.get("output_txt", "")
                summary.append(f"║  TXT: {txt_path[:52]:<52}║")
            if stats.get("output_csv"):
                csv_path = stats.get("output_csv", "")
                summary.append(f"║  CSV: {csv_path[:52]:<52}║")
            summary.append(
                "╚════════════════════════════════════════════════════════════╝"
            )

        else:
            # Generic summary for Organize/Preview modes
            if stopped_by_user:
                header_line = (
                    "║               PROCESSING CANCELLED (PARTIAL)               ║"
                )
            else:
                header_line = (
                    "║                    PROCESSING COMPLETE                     ║"
                )
            summary = [
                "╔════════════════════════════════════════════════════════════╗",
                header_line,
                "╠════════════════════════════════════════════════════════════╣",
                f"║  Files Moved:        {stats.get('files_moved', 0):<38}║",
                f"║  Files Renamed:      {stats.get('files_renamed', 0):<38}║",
                f"║  Errors:             {stats.get('errors', 0):<38}║",
                "╠════════════════════════════════════════════════════════════╣",
                f"║  iPhone Photos:      {stats.get('iphone_photos', 0):<38}║",
                f"║  iPhone Videos:      {stats.get('iphone_videos', 0):<38}║",
                f"║  Screenshots:        {stats.get('screenshots', 0):<38}║",
                f"║  Snapchat:           {stats.get('snapchat', 0):<38}║",
                f"║  Non-Apple:          {stats.get('non_apple', 0):<38}║",
                "╚════════════════════════════════════════════════════════════╝",
            ]

        self.results_viewer.setHtml("<pre>" + "\n".join(summary) + "</pre>")
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

        # Format manifest list for selection
        manifest_items = [
            f"{m.formatted_date} ({self._count_manifest_lines(m.path)} files)"
            for m in manifests
        ]

        # Let user select manifest
        selected, ok = QInputDialog.getItem(
            self,
            "Select Manifest to Undo",
            "Choose a manifest file to undo:",
            manifest_items,
            0,  # Default to most recent
            False,  # Not editable
        )

        if not ok or not selected:
            return

        # Find selected manifest
        selected_idx = manifest_items.index(selected)
        manifest = manifests[selected_idx]
        file_count = self._count_manifest_lines(manifest.path)

        # Confirm undo
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

        # Disable buttons during undo
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)

        # Create progress dialog
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

        # Create ErrorLogger for undo operation to persist errors to Desktop
        undo_error_logger = ErrorLogger()
        undo_error_logger.initialize()

        def on_error(context: str, file: str, error: str) -> None:
            self.log_viewer.log(f"{context}: {file} - {error}", "error")
            undo_error_logger.log_error(context, file, error)

        # Create and configure worker
        # Use separate variable to avoid overwriting main worker if we want to keep them distinct
        self.undo_worker = UndoWorker(manifest.path, undoer)

        self.undo_worker.progress.connect(progress.setValue)
        self.undo_worker.progress.connect(
            lambda c, t: progress.setLabelText(f"Restoring file {c} of {t}...")
        )
        self.undo_worker.log_message.connect(lambda m: self.log_viewer.log(m, "info"))
        self.undo_worker.error_log.connect(on_error)

        # Handle cancellation
        progress.canceled.connect(self.undo_worker.request_cancel)

        def on_finished(result: UndoResult) -> None:
            progress.close()
            undo_error_logger.close()

            # Re-enable buttons
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.undo_btn.setEnabled(True)

            # Show results
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
                    "to their original locations.",
                )

            # Clean up reference
            self.undo_worker = None

        self.undo_worker.finished.connect(on_finished)
        self.undo_worker.start()

    def _count_manifest_lines(self, manifest_path: Path) -> int:
        """Count non-comment lines in a manifest file."""
        try:
            count = 0
            with open(manifest_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "|" in line:
                        count += 1
            return count
        except OSError:
            return 0

    @Slot()
    def _view_manifests(self) -> None:
        """View available manifest files."""
        dialog = ManifestViewerDialog(self)
        dialog.exec()

    @Slot()
    def _open_settings(self) -> None:
        """Open settings dialog."""
        QMessageBox.information(
            self,
            "Settings",
            "Settings dialog is not yet implemented.\n\n"
            "Current options are available in the main window.",
        )


class ManifestViewerDialog(QDialog):
    """Dialog for viewing, previewing, and deleting manifest files."""

    def __init__(self, parent: QMainWindow = None):
        super().__init__(parent)
        self.parent_window = parent
        self.undoer = ManifestUndoer()
        self.manifests: list[ManifestInfo] = []

        self.setWindowTitle("Manifest Viewer")
        self.setMinimumSize(700, 450)
        self._setup_ui()
        self._apply_dark_theme()
        self._refresh_manifests()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Table widget
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Date", "File Count", "Path", ""])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._preview_manifest)

        # Configure column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.table)

        # Button row
        button_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self._refresh_manifests)

        self.preview_btn = QPushButton("👁 Preview")
        self.preview_btn.clicked.connect(self._preview_manifest)

        self.delete_btn = QPushButton("🗑 Delete Selected")
        self.delete_btn.clicked.connect(self._delete_selected)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)

        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.preview_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _apply_dark_theme(self) -> None:
        """Apply dark theme to match main window."""
        self.setStyleSheet(
            """
            QDialog {
                background-color: #1e1e1e;
                color: #e0e0e0;
            }
            QTableWidget {
                background-color: #2d2d2d;
                color: #e0e0e0;
                border: none;
                border-radius: 8px;
                gridline-color: #3d3d3d;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background-color: #4a9eff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #e0e0e0;
                padding: 8px;
                border: none;
            }
            QPushButton {
                background-color: #3d3d3d;
                color: #e0e0e0;
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """
        )

    def _refresh_manifests(self) -> None:
        """Refresh the manifest list."""
        self.manifests = self.undoer.list_manifests()
        self.table.setRowCount(len(self.manifests))

        for row, manifest in enumerate(self.manifests):
            # Date
            date_item = QTableWidgetItem(manifest.formatted_date)
            self.table.setItem(row, 0, date_item)

            # File count
            count = self._count_lines(manifest.path)
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, count_item)

            # Path (filename only)
            path_item = QTableWidgetItem(manifest.path.name)
            self.table.setItem(row, 2, path_item)

            # Status indicator
            status_item = QTableWidgetItem("✓" if manifest.path.exists() else "✗")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, status_item)

    def _count_lines(self, path: Path) -> int:
        """Count non-comment lines in manifest."""
        try:
            count = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "|" in line:
                        count += 1
            return count
        except OSError:
            return 0

    def _preview_manifest(self) -> None:
        """Show preview of selected manifest."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self.manifests):
            QMessageBox.information(
                self, "No Selection", "Please select a manifest to preview."
            )
            return

        manifest = self.manifests[row]
        moves = self._read_manifest_moves(manifest.path, limit=20)

        if not moves:
            QMessageBox.information(
                self,
                "Empty Manifest",
                "This manifest contains no recorded moves.",
            )
            return

        # Format preview text
        preview_lines = [
            f"Manifest: {manifest.formatted_date}",
            f"Total moves: {self._count_lines(manifest.path)}",
            "",
            "First 20 moves:",
            "─" * 60,
        ]

        for source, dest in moves:
            # Truncate long paths
            src_name = Path(source).name
            dst_folder = Path(dest).parent.name
            preview_lines.append(f"  {src_name[:40]:<40} → {dst_folder}")

        if self._count_lines(manifest.path) > 20:
            preview_lines.append("")
            preview_lines.append(
                f"... and {self._count_lines(manifest.path) - 20} more"
            )

        # Show preview dialog
        preview_dialog = QDialog(self)
        preview_dialog.setWindowTitle("Manifest Preview")
        preview_dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(preview_dialog)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("SF Mono", 11))
        text_edit.setText("\n".join(preview_lines))
        text_edit.setStyleSheet(
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
        layout.addWidget(text_edit)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(preview_dialog.accept)
        layout.addWidget(close_btn)

        preview_dialog.exec()

    def _read_manifest_moves(
        self, path: Path, limit: int = 20
    ) -> list[tuple[str, str]]:
        """Read moves from manifest file."""
        moves = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if len(moves) >= limit:
                        break
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "|" in line:
                        parts = line.split("|", 1)
                        if len(parts) == 2:
                            moves.append((parts[0], parts[1]))
        except OSError:
            pass
        return moves

    def _delete_selected(self) -> None:
        """Delete the selected manifest file."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self.manifests):
            QMessageBox.information(
                self, "No Selection", "Please select a manifest to delete."
            )
            return

        manifest = self.manifests[row]
        file_count = self._count_lines(manifest.path)

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete manifest from {manifest.formatted_date}?\n\n"
            f"This manifest contains {file_count} recorded moves.\n"
            "This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.undoer.delete_manifest(manifest.path):
            if self.parent_window:
                self.parent_window.log_viewer.log(
                    f"Deleted manifest: {manifest.path.name}", "info"
                )
            self._refresh_manifests()
        else:
            QMessageBox.warning(
                self,
                "Delete Failed",
                f"Failed to delete manifest: {manifest.path.name}",
            )


__all__ = ["MainWindow", "ManifestViewerDialog"]
