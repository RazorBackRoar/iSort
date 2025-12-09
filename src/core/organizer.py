# core/organizer.py
"""
File organization orchestration module.

Coordinates three-phase file organization:
- Phase 1: Extract files from subdirectories to top level
- Phase 2: Remove empty directories
- Phase 3: Organize files by metadata into categorized folders

Integrates with DestinationRouter for routing decisions, SmartHasher for
verification, and supports checkpoint/manifest callbacks for resume and undo.
"""

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Tuple, Union

from core.hasher import HASH_ERROR, SmartHasher
from core.metadata import Destination
from core.router import DestinationRouter


class StopRequested(Exception):
    """Exception raised when user requests stop during organization."""

    pass


logger = logging.getLogger(__name__)

# Minimum required disk space in MB
MIN_DISK_SPACE_MB = 100

# Number of files to process before saving a checkpoint
CHECKPOINT_INTERVAL = 10


def check_disk_space(folder_path: Path) -> Tuple[bool, int]:
    """
    Check available disk space for the given folder.

    Args:
        folder_path: Path to check disk space for

    Returns:
        Tuple of (is_sufficient, available_mb)
    """
    try:
        usage = shutil.disk_usage(folder_path)
        available_mb = usage.free // (1024 * 1024)
        is_sufficient = available_mb >= MIN_DISK_SPACE_MB

        if not is_sufficient:
            logger.warning(
                "Low disk space: %d MB available (minimum: %d MB)",
                available_mb,
                MIN_DISK_SPACE_MB,
            )

        return is_sufficient, available_mb
    except OSError as e:
        logger.error("Failed to check disk space: %s", e)
        return False, 0


def format_file_size(bytes_size: int) -> str:
    """
    Convert bytes to human-readable format.

    Args:
        bytes_size: Size in bytes

    Returns:
        Human-readable string (e.g., "1.5 MB")
    """
    if bytes_size >= 1073741824:  # 1 GB
        return f"{bytes_size / 1073741824:.1f} GB"
    elif bytes_size >= 1048576:  # 1 MB
        return f"{bytes_size / 1048576:.1f} MB"
    elif bytes_size >= 1024:  # 1 KB
        return f"{bytes_size / 1024:.1f} KB"
    else:
        return f"{bytes_size} B"


def generate_unique_filename(filename: str, dest_dir: Path) -> str:
    """
    Generate a unique filename by appending counter if collision exists.

    Args:
        filename: Original filename
        dest_dir: Destination directory to check for collisions

    Returns:
        Unique filename (may be same as input if no collision)
    """
    # Split name and extension
    if "." in filename:
        name = filename.rsplit(".", 1)[0]
        ext = filename.rsplit(".", 1)[1]
    else:
        name = filename
        ext = ""

    counter = 1
    new_filename = filename

    while (dest_dir / new_filename).exists():
        if ext:
            new_filename = f"{name}_{counter}.{ext}"
        else:
            new_filename = f"{name}_{counter}"
        counter += 1

    return new_filename


# Type aliases for callbacks
ProgressCallback = Callable[[int, int], None]
LogCallback = Callable[[str], None]
CheckpointCallback = Callable[[str, int, Union[str, Path]], None]
ManifestCallback = Callable[[Path, Path], None]
FileCallback = Callable[[str, str, str], None]  # filename, destination, status
ErrorLogCallback = Callable[[str, str, str], None]  # context, file, error


@dataclass
class OrganizationStats:
    """
    Statistics tracking for file organization operations.

    Note: In dry-run mode, files_moved and files_renamed count simulated
    operations (files that would be moved/renamed), not actual filesystem
    changes. Use the dry_run flag on FileOrganizer to determine context.
    """

    # General counters (includes both real and simulated operations)
    files_moved: int = 0
    files_renamed: int = 0
    dirs_removed: int = 0
    errors: int = 0

    # Phase-specific starting file counts
    phase1_file_count: int = 0  # Files in subdirectories at Phase 1 start
    phase3_file_count: int = 0  # Files at top level at Phase 3 start

    # Destination-specific counters
    files_to_snapchat: int = 0
    files_to_screenshots: int = 0
    files_to_iphone_photos: int = 0
    files_to_iphone_videos: int = 0
    files_to_iphone_screenshots: int = 0
    files_to_jpeg: int = 0
    files_to_mp4: int = 0
    files_to_non_apple: int = 0
    files_no_metadata: int = 0


class FileOrganizer:
    """
    Orchestrates three-phase file organization.

    Phase 1: Extract files from subdirectories to top level
    Phase 2: Remove empty directories
    Phase 3: Organize files by metadata into categorized folders

    Supports dry-run mode, hash verification, and callback-based integration
    for progress tracking, logging, checkpointing, and manifest recording.
    """

    def __init__(
        self,
        verify_hash: bool = False,
        dry_run: bool = False,
        progress_callback: Optional[ProgressCallback] = None,
        log_callback: Optional[LogCallback] = None,
        checkpoint_callback: Optional[CheckpointCallback] = None,
        manifest_callback: Optional[ManifestCallback] = None,
        file_callback: Optional[FileCallback] = None,
        error_log_callback: Optional[ErrorLogCallback] = None,
    ):
        """
        Initialize the FileOrganizer.

        Args:
            verify_hash: If True, verify file integrity via hash comparison
            dry_run: If True, simulate operations without making changes
            progress_callback: Called with (current, total) for progress updates
            log_callback: Called with log messages for UI display
            checkpoint_callback: Called with (phase, index) for resume support
            manifest_callback: Called with (source, dest) for undo support
            file_callback: Called with (filename, destination, status) per file
            error_log_callback: Called with (context, file, error) for persistent logging
        """
        self.router = DestinationRouter()
        self.hasher = SmartHasher()
        self.stats = OrganizationStats()

        self.verify_hash = verify_hash
        self.dry_run = dry_run

        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.checkpoint_callback = checkpoint_callback
        self.manifest_callback = manifest_callback
        self.file_callback = file_callback
        self.error_log_callback = error_log_callback

    def _log(self, message: str) -> None:
        """Log message to both logger and callback if provided."""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def _move_file(
        self,
        source: Path,
        dest: Path,
        original_filename: str,
        new_filename: str,
        destination_label: str = "",
    ) -> bool:
        """
        Move a file with optional hash verification.

        Args:
            source: Source file path
            dest: Destination file path
            original_filename: Original filename for rename tracking
            new_filename: New filename (may differ due to collision)
            destination_label: Label for the destination (e.g., folder name)

        Returns:
            True if move succeeded, False otherwise
        """
        # Pre-compute source hash if verification enabled
        source_hash = ""
        if self.verify_hash and not self.dry_run:
            source_hash = self.hasher.compute_hash(str(source))
            if source_hash == HASH_ERROR:
                logger.error("Failed to compute source hash: %s", source)
                if self.error_log_callback:
                    self.error_log_callback(
                        "HASH_ERROR", str(source), "Failed to compute source hash"
                    )
                self.stats.errors += 1
                return False

        # Dry-run mode: just validate and log
        if self.dry_run:
            self._log(f"Would move: {source} -> {dest}")
            if original_filename != new_filename:
                self.stats.files_renamed += 1
            self.stats.files_moved += 1
            # Emit file callback for dry-run
            if self.file_callback:
                self.file_callback(original_filename, destination_label, "simulated")
            return True

        # Execute the move
        try:
            # Ensure destination directory exists
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
        except (OSError, shutil.Error) as e:
            logger.error("Failed to move %s -> %s: %s", source, dest, e)
            if self.error_log_callback:
                self.error_log_callback("MOVE_FAILED", str(source), str(e))
            self.stats.errors += 1
            return False

        # Post-move verification
        if not dest.exists():
            logger.error("Destination file missing after move: %s", dest)
            if self.error_log_callback:
                self.error_log_callback(
                    "MOVE_VERIFY_FAILED", str(source), "Destination missing"
                )
            self.stats.errors += 1
            return False

        # Hash verification if enabled
        if self.verify_hash:
            dest_hash = self.hasher.compute_hash(str(dest))

            # Check for hash failure or mismatch
            if dest_hash == HASH_ERROR or source_hash != dest_hash:
                error_type = (
                    "HASH_ERROR" if dest_hash == HASH_ERROR else "HASH_MISMATCH"
                )
                error_msg = (
                    "Failed to compute dest hash"
                    if dest_hash == HASH_ERROR
                    else f"Source hash {source_hash} != Dest hash {dest_hash}"
                )

                logger.error(
                    "Hash verification failed for %s -> %s: %s", source, dest, error_msg
                )

                if self.error_log_callback:
                    self.error_log_callback(error_type, str(source), error_msg)

                # STRICT ROLLBACK: Attempt to move file back to source
                try:
                    logger.info("Attempting rollback: %s -> %s", dest, source)
                    shutil.move(str(dest), str(source))

                    if self.error_log_callback:
                        self.error_log_callback(
                            "ROLLBACK_SUCCESS",
                            str(source),
                            "File moved back to source after hash failure",
                        )
                except (OSError, shutil.Error) as rb_err:
                    logger.critical("Rollback failed: %s", rb_err)
                    if self.error_log_callback:
                        self.error_log_callback(
                            "ROLLBACK_FAILED",
                            str(source),
                            f"Failed to restore file: {rb_err}",
                        )

                self.stats.errors += 1
                return False

        # Success - record in manifest
        if self.manifest_callback:
            self.manifest_callback(source, dest)

        # Track rename
        if original_filename != new_filename:
            self.stats.files_renamed += 1

        self.stats.files_moved += 1

        # Emit file callback for successful move
        if self.file_callback:
            self.file_callback(original_filename, destination_label, "moved")

        return True

    def extract_files_to_top(
        self,
        folder_path: Path,
        resume_index: int = 0,
    ) -> None:
        """
        Phase 1: Extract files from subdirectories to top level.

        Args:
            folder_path: Root folder to process
            resume_index: Next index to process (for checkpoint support).
                          Files with index < resume_index are skipped.
        """
        self._log("Phase 1: Extracting files from subdirectories...")

        # Find all files at depth >= 2 (in subdirectories)
        all_files = [
            f for f in folder_path.rglob("*") if f.is_file() and f.parent != folder_path
        ]

        total = len(all_files)
        self.stats.phase1_file_count = total
        self._log(f"Found {total} files in subdirectories")

        if total == 0:
            self._log("No files to extract")
            return

        # Per-phase counters for accurate logging
        phase_moved = 0
        phase_renamed = 0

        for i, source in enumerate(all_files):
            # Resume support
            if i < resume_index:
                continue

            original_filename = source.name
            new_filename = generate_unique_filename(original_filename, folder_path)
            dest = folder_path / new_filename

            if self._move_file(
                source, dest, original_filename, new_filename, "top-level"
            ):
                phase_moved += 1
                if original_filename != new_filename:
                    phase_renamed += 1

            # Progress and checkpoint callbacks (every 10 files)
            # Checkpoint stores next index to process (i + 1) for correct resume
            if (i + 1) % 10 == 0 or i == total - 1:
                if self.progress_callback:
                    self.progress_callback(i + 1, total)
                if self.checkpoint_callback:
                    self.checkpoint_callback("extract", i + 1, folder_path)

        self._log(
            f"Phase 1 complete: {phase_moved} files moved, " f"{phase_renamed} renamed"
        )

    def remove_empty_directories(self, folder_path: Path) -> None:
        """
        Phase 2: Remove empty directories.

        Args:
            folder_path: Root folder to process
        """
        self._log("Phase 2: Removing empty directories...")

        # Get all directories, sorted by depth (deepest first)
        all_dirs = [d for d in folder_path.rglob("*") if d.is_dir()]
        all_dirs.sort(key=lambda p: len(p.parts), reverse=True)

        removed_count = 0

        for dir_path in all_dirs:
            # Skip if not empty
            if any(dir_path.iterdir()):
                continue

            if self.dry_run:
                self._log(f"Would remove empty directory: {dir_path}")
                removed_count += 1
            else:
                try:
                    dir_path.rmdir()
                    removed_count += 1
                    logger.debug("Removed empty directory: %s", dir_path)
                except OSError as e:
                    logger.error("Failed to remove directory %s: %s", dir_path, e)
                    if self.error_log_callback:
                        self.error_log_callback(
                            "DIR_REMOVE_FAILED", str(dir_path), str(e)
                        )
                    self.stats.errors += 1

        self.stats.dirs_removed = removed_count
        self._log(f"Phase 2 complete: {removed_count} empty directories removed")

    def _increment_destination_stat(self, destination: Destination) -> None:
        """Increment the appropriate destination counter."""
        stat_map = {
            Destination.SNAPCHAT: "files_to_snapchat",
            Destination.SCREENSHOTS: "files_to_screenshots",
            Destination.IPHONE_PHOTOS: "files_to_iphone_photos",
            Destination.IPHONE_VIDEOS: "files_to_iphone_videos",
            Destination.IPHONE_SCREENSHOTS: "files_to_iphone_screenshots",
            Destination.JPEG: "files_to_jpeg",
            Destination.MP4: "files_to_mp4",
            Destination.NON_APPLE: "files_to_non_apple",
            Destination.NO_METADATA: "files_no_metadata",
        }

        attr = stat_map.get(destination)
        if attr:
            setattr(self.stats, attr, getattr(self.stats, attr) + 1)

    def organize_files(
        self,
        folder_path: Path,
        resume_index: int = 0,
    ) -> None:
        """
        Phase 3: Organize files by metadata into categorized folders.

        Args:
            folder_path: Root folder to process
            resume_index: Next index to process (for checkpoint support).
                          Files with index < resume_index are skipped.
        """
        self._log("Phase 3: Organizing files by metadata...")

        # Find all files at top level only
        all_files = [f for f in folder_path.glob("*") if f.is_file()]

        total = len(all_files)
        self.stats.phase3_file_count = total
        self._log(f"Found {total} files to analyze")

        if total == 0:
            self._log("No files to organize")
            return

        # Create destination folders
        for dest in Destination:
            dest_folder = folder_path / dest.value
            if not self.dry_run:
                dest_folder.mkdir(parents=True, exist_ok=True)

        # Reset move counter for this phase
        phase_moved = 0

        for i, source in enumerate(all_files):
            # Resume support
            if i < resume_index:
                continue

            # Determine destination
            destination, detection_method = self.router.determine_destination(
                str(source)
            )

            # Increment destination-specific counter
            self._increment_destination_stat(destination)

            # Build destination path
            dest_folder = folder_path / destination.value
            original_filename = source.name
            new_filename = generate_unique_filename(original_filename, dest_folder)
            dest = dest_folder / new_filename

            # Log routing decision
            logger.debug(
                "Routing %s -> %s (%s)",
                original_filename,
                destination.value,
                detection_method,
            )

            # Execute move
            if self._move_file(
                source, dest, original_filename, new_filename, destination.value
            ):
                phase_moved += 1

            # Progress and checkpoint callbacks
            # Checkpoint stores next index to process (i + 1) for correct resume
            if (i + 1) % CHECKPOINT_INTERVAL == 0 or i == total - 1:
                if self.progress_callback:
                    self.progress_callback(i + 1, total)
                if self.checkpoint_callback:
                    self.checkpoint_callback("organize", i + 1, folder_path)

        self._log(f"Phase 3 complete: {phase_moved} files organized")
        self._log_destination_summary()

    def _log_destination_summary(self) -> None:
        """Log summary of files by destination."""
        summary_lines = [
            f"  Snapchat: {self.stats.files_to_snapchat}",
            f"  Screenshots: {self.stats.files_to_screenshots}",
            f"  iPhone Photos: {self.stats.files_to_iphone_photos}",
            f"  iPhone Videos: {self.stats.files_to_iphone_videos}",
            f"  iPhone Screenshots: {self.stats.files_to_iphone_screenshots}",
            f"  JPEG: {self.stats.files_to_jpeg}",
            f"  MP4: {self.stats.files_to_mp4}",
            f"  Non-Apple: {self.stats.files_to_non_apple}",
            f"  No Metadata: {self.stats.files_no_metadata}",
        ]
        self._log("Destination summary:\n" + "\n".join(summary_lines))

    def organize(
        self,
        folder_path: Union[str, Path],
        skip_extract: bool = False,
        skip_cleanup: bool = False,
        start_phase: str = "none",
        resume_index: int = 0,
    ) -> OrganizationStats:
        """
        Run the complete organization workflow.

        Args:
            folder_path: Root folder to organize
            skip_extract: If True, skip Phase 1 (extraction)
            skip_cleanup: If True, skip Phase 2 (empty dir removal)
            start_phase: Phase to resume from ("none", "extract", "organize")
            resume_index: File index to resume from within the phase

        Returns:
            OrganizationStats with operation counts
        """
        folder_path = Path(folder_path)

        # Validate folder
        if not folder_path.exists():
            raise ValueError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ValueError(f"Path is not a directory: {folder_path}")

        # Reset stats for this run (allows reusing FileOrganizer instance)
        self.stats = OrganizationStats()

        self._log(f"Starting organization of: {folder_path}")

        if self.dry_run:
            self._log("DRY RUN MODE - no changes will be made")

        if self.verify_hash:
            self._log("Hash verification enabled")

        # Check disk space (warning only, don't block)
        is_sufficient, available_mb = check_disk_space(folder_path)
        self._log(f"Available disk space: {available_mb} MB")

        # Determine which phases to run based on resume state
        # If resuming from "organize", skip extract and cleanup
        # If resuming from "extract", continue extract then proceed
        run_extract = not skip_extract and start_phase in ("none", "extract")
        run_cleanup = not skip_cleanup and start_phase in ("none", "extract")
        extract_resume_idx = resume_index if start_phase == "extract" else 0
        organize_resume_idx = resume_index if start_phase == "organize" else 0

        try:
            # Phase 1: Extract files from subdirectories
            if run_extract:
                self.extract_files_to_top(folder_path, resume_index=extract_resume_idx)
            else:
                self._log("Skipping Phase 1 (extraction)")

            # Phase 2: Remove empty directories
            if run_cleanup:
                self.remove_empty_directories(folder_path)
            else:
                self._log("Skipping Phase 2 (cleanup)")

            # Phase 3: Organize files by metadata
            self.organize_files(folder_path, resume_index=organize_resume_idx)

        except StopRequested:
            # Re-raise without logging or incrementing errors
            raise
        except Exception as e:
            logger.critical("Organization failed: %s", e)
            if self.error_log_callback:
                self.error_log_callback("FATAL_ERROR", str(folder_path), str(e))
            self.stats.errors += 1
            raise

        self._log(
            f"Organization complete. "
            f"Moved: {self.stats.files_moved}, "
            f"Errors: {self.stats.errors}"
        )

        return self.stats


__all__ = [
    "FileOrganizer",
    "OrganizationStats",
    "StopRequested",
    "check_disk_space",
    "format_file_size",
    "generate_unique_filename",
    "MIN_DISK_SPACE_MB",
]
