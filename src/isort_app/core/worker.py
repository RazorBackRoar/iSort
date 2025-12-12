# core/worker.py
"""
Background worker thread for file organization operations.

Provides a mode-aware QThread that dispatches to appropriate core modules
(FileOrganizer, DuplicateDetector, FolderComparator, InventoryGenerator)
based on selected mode, integrating checkpoint/manifest managers via callbacks,
and emitting PySide6 signals for real-time UI updates.

Usage:
    worker = OrganizeWorker(folder, mode, verify_hash, dry_run, resume)
    worker.progress.connect(on_progress)
    worker.log_message.connect(on_log)
    worker.finished.connect(on_finished)
    worker.start()
"""

import logging
import time
from typing import Dict, Optional

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from isort_app.core.duplicates import DuplicateDetector
from isort_app.core.inventory import InventoryGenerator
from isort_app.core.organizer import (
    FileOrganizer,
    OrganizationStats,
    StopRequested,
    format_file_size,
)
from isort_app.utils.checkpoint import CheckpointManager
from isort_app.utils.error_log import ErrorLogger
from isort_app.utils.manifest import ManifestManager

logger = logging.getLogger(__name__)


class OrganizeWorker(QThread):
    """
    Mode-aware worker thread for file organization operations.

    Dispatches to appropriate core modules based on selected mode:
    - Organize Files / Preview Only: FileOrganizer
    - Generate Inventory: InventoryGenerator
    - Find Duplicates: DuplicateDetector
    - Compare Folders: FolderComparator

    Emits signals for progress, logging, and completion.
    """

    # Signals for UI communication
    progress = Signal(int, int, str)  # current, total, ETA string
    log_message = Signal(
        str, str
    )  # message, level ("info"/"warning"/"error"/"success")
    file_processed = Signal(str, str, str)  # filename, destination, status
    stats_updated = Signal(dict)  # stats dict with UI keys
    finished = Signal(dict)  # final stats dict

    def __init__(
        self,
        folder: str,
        mode: str,
        verify_hash: bool = False,
        dry_run: bool = False,
        resume: bool = False,
    ):
        """
        Initialize the OrganizeWorker.

        Args:
            folder: Path to folder to process
            mode: Operation mode (e.g., "Organize Files", "Find Duplicates")
            verify_hash: If True, verify file integrity via hash comparison
            dry_run: If True, simulate operations without making changes
            resume: If True, attempt to resume from checkpoint
        """
        super().__init__()

        self.folder = folder
        self.mode = mode
        self.verify_hash = verify_hash
        self.dry_run = dry_run
        self.resume = resume

        self._stop_requested = False
        self._start_time: float = 0.0

        # Initialize stats dict with all UI keys
        # UI widgets expect "files_moved" and "files_renamed" keys
        self.stats: Dict[str, any] = {
            "mode": mode,
            "stopped_by_user": False,
            "files_moved": 0,
            "files_renamed": 0,
            "errors": 0,
            "iphone_photos": 0,
            "iphone_videos": 0,
            "iphone_screenshots": 0,
            "screenshots": 0,
            "snapchat": 0,
            "jpeg": 0,
            "mp4": 0,
            "non_apple": 0,
            "no_metadata": 0,
        }

        # Reference to organizer for incremental stats (set during organize mode)
        self._organizer: Optional[FileOrganizer] = None

        # Checkpoint manager (always initialized to allow saving progress)
        self.checkpoint_mgr = CheckpointManager()

        # Manifest manager (if not dry_run)
        self.manifest_mgr: Optional[ManifestManager] = None
        if not dry_run:
            self.manifest_mgr = ManifestManager()

        # Error logger (initialized in run if not dry_run)
        self.error_logger: Optional[ErrorLogger] = None

    def request_stop(self) -> None:
        """Request graceful stop of current operation."""
        self._stop_requested = True
        self.log_message.emit("Stop requested by user...", "warning")

    def run(self) -> None:
        """Main execution method - dispatches to appropriate mode handler."""
        self._start_time = time.time()

        # Comment 1: Verify dry_run correctness
        if self.mode == "Preview Only (Dry Run)" and not self.dry_run:
            logger.error(
                "Configuration Error: Preview mode selected but dry_run is False"
            )
            # Force dry_run to True to be safe
            self.dry_run = True

        # Ensure manifest manager is disabled if dry_run is True (even if set after init)
        if self.dry_run:
            self.manifest_mgr = None

        if self.dry_run:
            self.log_message.emit(
                f"Worker started in DRY RUN mode (mode={self.mode})", "info"
            )

        # Initialize error logger if not dry run
        if not self.dry_run:
            self.error_logger = ErrorLogger()
            self.error_logger.initialize()

        try:
            if self.mode == "Organize Files":
                self._run_organize_mode()
            elif self.mode == "Preview Only (Dry Run)":
                self._run_organize_mode()  # Same as organize but dry_run=True
            elif self.mode == "Generate Inventory":
                self._run_inventory_mode()
            elif self.mode == "Find Duplicates":
                self._run_duplicates_mode()
            elif "Compare Folders" in self.mode:
                self._run_compare_mode()
            else:
                self.log_message.emit(f"Unknown mode: {self.mode}", "error")
                self.stats["errors"] += 1
        except StopRequested:
            self.stats["stopped_by_user"] = True
            self.log_message.emit("Operation stopped by user", "warning")
            # Emit partial stats on stop (don't lose progress)
            self.log_message.emit(
                f"Partial progress: {self.stats['files_moved']} files processed", "info"
            )
        except PermissionError as e:
            logger.exception("Permission error in worker")
            self.log_message.emit(f"Permission denied: {e}", "error")
            self.stats["errors"] += 1
        except OSError as e:
            logger.exception("OS error in worker")
            self.log_message.emit(f"File system error: {e}", "error")
            self.stats["errors"] += 1
        except Exception as e:
            logger.exception("Fatal error in worker")
            self.log_message.emit(f"Fatal error: {e}", "error")
            self.log_message.emit(
                "Processing failed unexpectedly. Check logs for details.", "error"
            )
            self.stats["errors"] += 1
        finally:
            if self.error_logger:
                self.error_logger.close()
            self.finished.emit(self.stats.copy())

    def _run_organize_mode(self) -> None:
        """Execute file organization (Phase 1-3)."""
        # Checkpoint/Manifest setup
        phase = "none"
        resume_index = 0

        # Comment 1: Preview mode should never interact with checkpoints
        use_checkpoint = not self.dry_run

        # Check for existing checkpoint even if resume is False
        checkpoint_exists = self.checkpoint_mgr.exists()

        if not self.resume and checkpoint_exists and use_checkpoint:
            self.log_message.emit(
                "Notice: Existing checkpoint ignored (Resume option unchecked). "
                "Previous progress will be overwritten.",
                "info",
            )

        if self.resume and checkpoint_exists and use_checkpoint:
            phase, resume_index, saved_folder, is_invalid = self.checkpoint_mgr.load()

            if is_invalid:
                self.log_message.emit(
                    "Checkpoint ignored: File is corrupted or incompatible. Starting fresh.",
                    "warning",
                )
                self.checkpoint_mgr.clear()
                phase, resume_index = "none", 0
            # Validate checkpoint folder matches current folder
            elif saved_folder and str(saved_folder) != str(self.folder):
                self.log_message.emit(
                    f"Checkpoint ignored: Folder mismatch ({saved_folder} != {self.folder})",
                    "warning",
                )
                phase, resume_index = "none", 0
            else:
                self.log_message.emit(
                    f"Resuming from checkpoint: phase={phase}, index={resume_index}",
                    "info",
                )
        else:
            phase, resume_index = "none", 0

        # Note: Manifest initialization is deferred to first record_move() call
        # to avoid creating empty manifests for runs that fail before any moves.

        # Create FileOrganizer with callbacks and store reference for incremental stats
        organizer = FileOrganizer(
            verify_hash=self.verify_hash,
            dry_run=self.dry_run,
            progress_callback=self._on_organizer_progress,
            log_callback=self._on_organizer_log,
            checkpoint_callback=(self.checkpoint_mgr.save if use_checkpoint else None),
            manifest_callback=(
                self.manifest_mgr.record_move if self.manifest_mgr else None
            ),
            file_callback=self._on_file_moved,
            error_log_callback=(
                self.error_logger.log_error if self.error_logger else None
            ),
        )
        self._organizer = organizer

        try:
            # Execute organization with resume support
            organizer.organize(
                self.folder,
                skip_extract=False,
                skip_cleanup=False,
                start_phase=phase,
                resume_index=resume_index,
            )

            # Map OrganizationStats to UI dict
            self._map_organization_stats(organizer.stats)

            # Clear checkpoint on success
            if not self._stop_requested and self.checkpoint_mgr and use_checkpoint:
                self.checkpoint_mgr.clear()
                self.log_message.emit("Checkpoint cleared", "info")

            # Finalize manifest only if files were actually moved
            if self.manifest_mgr and not self.dry_run:
                if organizer.stats.files_moved > 0:
                    self.manifest_mgr.close()
                    self.log_message.emit(
                        f"Manifest saved: {self.manifest_mgr.manifest_path}", "success"
                    )
                else:
                    # No files moved - don't create/finalize empty manifest
                    self.log_message.emit(
                        "No files moved, manifest not created", "info"
                    )

        except StopRequested:
            # Re-raise to be handled by run()
            raise
        except Exception as e:
            logger.exception("Organization failed")
            self.log_message.emit(f"Organization error: {e}", "error")
            self.stats["errors"] += 1

    def _map_organization_stats(self, org_stats: OrganizationStats) -> None:
        """Map OrganizationStats dataclass to UI stats dict."""
        self.stats["files_moved"] = org_stats.files_moved
        self.stats["files_renamed"] = org_stats.files_renamed
        self.stats["errors"] = org_stats.errors
        self.stats["iphone_photos"] = org_stats.files_to_iphone_photos
        self.stats["iphone_videos"] = org_stats.files_to_iphone_videos
        self.stats["iphone_screenshots"] = org_stats.files_to_iphone_screenshots
        self.stats["screenshots"] = org_stats.files_to_screenshots
        self.stats["snapchat"] = org_stats.files_to_snapchat
        self.stats["jpeg"] = org_stats.files_to_jpeg
        self.stats["mp4"] = org_stats.files_to_mp4
        self.stats["non_apple"] = org_stats.files_to_non_apple
        self.stats["no_metadata"] = org_stats.files_no_metadata

    def _run_inventory_mode(self) -> None:
        """Execute inventory generation."""
        self.log_message.emit("Starting inventory generation...", "info")

        generator = InventoryGenerator(
            progress_callback=self._on_inventory_progress,
            error_log_callback=(
                self.error_logger.log_error if self.error_logger else None
            ),
        )

        # Output reports to Desktop (consistent with ZSH script)
        output_dir = Path.home() / "Desktop"

        try:
            result = generator.generate_inventory(self.folder, output_dir=output_dir)

            # Map stats with inventory-specific keys
            self.stats["total_files"] = result.total_files
            self.stats["total_size_bytes"] = result.total_size_bytes
            self.stats["total_size_human"] = format_file_size(result.total_size_bytes)
            self.stats["directories"] = result.directories_count
            self.stats["errors"] = result.errors
            self.stats["output_txt"] = (
                str(result.output_txt) if result.output_txt else None
            )
            self.stats["output_csv"] = (
                str(result.output_csv) if result.output_csv else None
            )
            # Also set files_moved for compatibility
            self.stats["files_moved"] = result.total_files

            # Log output paths
            self.log_message.emit(
                f"Inventory complete: {result.total_files} files processed", "success"
            )
            if result.output_txt:
                self.log_message.emit(f"TXT report: {result.output_txt}", "info")
            if result.output_csv:
                self.log_message.emit(f"CSV report: {result.output_csv}", "info")

        except StopRequested:
            raise
        except Exception as e:
            logger.exception("Inventory generation failed")
            self.log_message.emit(f"Inventory error: {e}", "error")
            self.stats["errors"] += 1

    def _run_duplicates_mode(self) -> None:
        """Execute duplicate detection."""
        self.log_message.emit("Starting duplicate detection...", "info")

        detector = DuplicateDetector(
            progress_callback=self._on_duplicates_progress,
            error_log_callback=(
                self.error_logger.log_error if self.error_logger else None
            ),
        )

        # Output reports to Desktop (consistent with ZSH script)
        output_dir = Path.home() / "Desktop"

        try:
            result = detector.find_duplicates(self.folder, output_dir=output_dir)

            # Map stats with duplicate-specific keys
            self.stats["total_files"] = result.total_files
            self.stats["duplicate_groups"] = result.duplicate_groups
            self.stats["duplicate_files"] = result.duplicate_files
            self.stats["wasted_space_bytes"] = result.wasted_space_bytes
            self.stats["wasted_space_human"] = format_file_size(
                result.wasted_space_bytes
            )
            self.stats["errors"] = result.errors
            self.stats["output_txt"] = (
                str(result.output_txt) if result.output_txt else None
            )
            self.stats["output_csv"] = (
                str(result.output_csv) if result.output_csv else None
            )
            # Also set files_moved for compatibility
            self.stats["files_moved"] = result.total_files

            # Log results
            self.log_message.emit(
                f"Duplicate detection complete: {result.duplicate_groups} groups found",
                "success",
            )
            self.log_message.emit(
                f"Wasted space: {format_file_size(result.wasted_space_bytes)}", "info"
            )
            if result.output_txt:
                self.log_message.emit(f"TXT report: {result.output_txt}", "info")
            if result.output_csv:
                self.log_message.emit(f"CSV report: {result.output_csv}", "info")

        except StopRequested:
            raise
        except Exception as e:
            logger.exception("Duplicate detection failed")
            self.log_message.emit(f"Duplicate detection error: {e}", "error")
            self.stats["errors"] += 1

    # TODO: Integrate FolderComparator and real progress/file events once a second
    # folder selector exists in the UI; currently Compare mode is intentionally stubbed.
    def _run_compare_mode(self) -> None:
        """
        Execute cross-folder comparison (INTENTIONALLY STUBBED).

        Compare Folders is disabled until a second folder selector is added to the UI.
        Currently logs a message and exits.
        """
        # Compare Folders is explicitly deferred to a later phase.
        # The UI currently only supports single folder selection.
        self.log_message.emit(
            "Compare Folders is not yet implemented. "
            "This feature requires a second folder picker in the UI.",
            "warning",
        )
        self.log_message.emit(
            "Scheduled for a future release. Use 'Find Duplicates' for single-folder analysis.",
            "info",
        )

    def _calculate_eta(self, current: int, total: int) -> str:
        """Calculate estimated time remaining."""
        if current == 0 or total == 0:
            return "Calculating..."

        elapsed = time.time() - self._start_time
        if elapsed < 1:
            return "Calculating..."

        rate = current / elapsed
        remaining_files = total - current
        remaining_seconds = remaining_files / rate

        mins = int(remaining_seconds // 60)
        secs = int(remaining_seconds % 60)

        if mins > 0:
            return f"ETA: {mins}m {secs}s"
        else:
            return f"ETA: {secs}s"

    def _on_organizer_progress(self, current: int, total: int) -> None:
        """Handle progress callback from FileOrganizer."""
        if self._stop_requested:
            raise StopRequested()

        eta = self._calculate_eta(current, total)
        self.progress.emit(current, total, eta)

        # Emit incremental stats every 25 files for live Statistics tab updates
        if current % 25 == 0 and self._organizer is not None:
            self._map_organization_stats(self._organizer.stats)
            self.stats_updated.emit(self.stats.copy())

    def _on_organizer_log(self, message: str) -> None:
        """Handle log callback from FileOrganizer."""
        self.log_message.emit(message, "info")

    def _on_file_moved(self, filename: str, destination: str, status: str) -> None:
        """Handle per-file callback from FileOrganizer."""
        self.file_processed.emit(filename, destination, status)

    def _on_inventory_progress(self, current: int, total: int) -> None:
        """Handle progress callback from InventoryGenerator."""
        if self._stop_requested:
            raise StopRequested()

        eta = self._calculate_eta(current, total)
        self.progress.emit(current, total, eta)

        # Emit file_processed for every file in inventory mode
        self.file_processed.emit(f"File {current}", "inventory", "processed")

        # Batch stats updates every 25 files
        if current % 25 == 0:
            self.stats["files_moved"] = current
            self.stats_updated.emit(self.stats.copy())

    def _on_duplicates_progress(self, current: int, total: int) -> None:
        """Handle progress callback from DuplicateDetector."""
        if self._stop_requested:
            raise StopRequested()

        eta = self._calculate_eta(current, total)
        self.progress.emit(current, total, eta)

        # Emit file_processed for every file in duplicates mode
        self.file_processed.emit(f"File {current}", "duplicates", "hashed")

        # Batch stats updates every 25 files
        if current % 25 == 0:
            self.stats["files_moved"] = current
            self.stats_updated.emit(self.stats.copy())


__all__ = ["OrganizeWorker", "StopRequested"]
