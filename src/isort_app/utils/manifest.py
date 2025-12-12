# utils/manifest.py
"""
File move tracking and undo system.

Ports manifest/undo logic from isort.zsh lines 161-248.

Tracks all file moves for rollback/undo, supporting interactive manifest
selection and reversal. Manifests are stored on Desktop with timestamps.

Usage:
    # Recording moves during organization
    with ManifestManager() as manifest:
        organizer = FileOrganizer(manifest_callback=manifest.record_move)
        organizer.organize(folder_path)

    # Listing and undoing manifests
    undoer = ManifestUndoer()
    manifests = undoer.list_manifests()
    if manifests:
        result = undoer.undo_manifest(manifests[0].path)
        print(f"Restored {result.success_count} files")
"""

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Default manifest directory
DEFAULT_MANIFEST_DIR = Path.home() / "Desktop"


@dataclass
class ManifestInfo:
    """Information about a manifest file."""

    path: Path
    timestamp: int
    formatted_date: str


@dataclass
class UndoResult:
    """Result statistics from undo operation."""

    success_count: int
    failed_count: int
    total_count: int


# Type aliases for callbacks
ProgressCallback = Callable[[int, int], None]
LogCallback = Callable[[str], None]
ErrorLogCallback = Callable[[str, str, str], None]
ShouldCancelCallback = Callable[[], bool]


class ManifestManager:
    """
    Manages manifest file creation and move recording.

    Creates timestamped manifest files on Desktop, recording all file
    moves in pipe-delimited format for later undo.
    """

    def __init__(
        self,
        manifest_path: Path | str | None = None,
        manifest_dir: Path | str | None = None,
    ):
        """
        Initialize the ManifestManager.

        Args:
            manifest_path: Explicit path to manifest file (overrides manifest_dir)
            manifest_dir: Directory for manifest files (default: ~/Desktop)
        """
        if manifest_path is not None:
            self.manifest_path = Path(manifest_path)
        else:
            if manifest_dir is None:
                manifest_dir = DEFAULT_MANIFEST_DIR
            else:
                manifest_dir = Path(manifest_dir)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.manifest_path = manifest_dir / f"isort_manifest_{timestamp}.txt"

        self._initialized = False

    def initialize(self) -> None:
        """
        Create manifest file with header.

        Called automatically by context manager or manually before recording.
        """
        if self._initialized:
            return

        try:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f"# iSort Manifest - {date_str}\n# Format: SOURCE|DESTINATION\n"

            self.manifest_path.write_text(header, encoding="utf-8")
            self._initialized = True
            logger.info("Manifest initialized: %s", self.manifest_path)

        except OSError as e:
            logger.error("Failed to initialize manifest: %s", e)
            raise

    def record_move(self, source: Path, dest: Path) -> None:
        """
        Record a file move to the manifest.

        Args:
            source: Original file path (before move)
            dest: New file path (after move)
        """
        if not self._initialized:
            self.initialize()

        try:
            with open(self.manifest_path, "a", encoding="utf-8") as f:
                f.write(f"{source}|{dest}\n")
        except OSError as e:
            logger.error("Failed to record move: %s", e)

    def close(self) -> None:
        """
        Finalize the manifest file.

        Currently performs no resource cleanup since record_move() uses
        append mode without persistent file handles. Retained for API
        stability and future extensibility.

        Called automatically by context manager or manually after recording.
        """
        if self._initialized:
            logger.info("Manifest finalized: %s", self.manifest_path)

    def __enter__(self) -> "ManifestManager":
        """Context manager entry - initialize manifest."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close manifest."""
        self.close()


class ManifestUndoer:
    """
    Handles listing and undoing manifest files.

    Scans Desktop for manifest files, allows selection, and reverses
    all recorded moves to restore original file locations.
    """

    def __init__(self, manifest_dir: Path | str | None = None):
        """
        Initialize the ManifestUndoer.

        Args:
            manifest_dir: Directory to scan for manifests (default: ~/Desktop)
        """
        if manifest_dir is None:
            self.manifest_dir = DEFAULT_MANIFEST_DIR
        else:
            self.manifest_dir = Path(manifest_dir)

    def list_manifests(self) -> List[ManifestInfo]:
        """
        List all available manifest files.

        Returns:
            List of ManifestInfo sorted by timestamp (newest first)
        """
        manifests: List[ManifestInfo] = []

        try:
            for path in self.manifest_dir.glob("isort_manifest_*.txt"):
                # Extract timestamp from filename: isort_manifest_YYYYMMDD_HHMMSS.txt
                try:
                    name = path.stem  # isort_manifest_YYYYMMDD_HHMMSS
                    timestamp_str = name.replace("isort_manifest_", "")
                    dt = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    timestamp = int(dt.timestamp())
                    formatted_date = dt.strftime("%Y-%m-%d %H:%M:%S")

                    manifests.append(
                        ManifestInfo(
                            path=path,
                            timestamp=timestamp,
                            formatted_date=formatted_date,
                        )
                    )
                except ValueError:
                    # Skip files with invalid timestamp format
                    logger.debug("Skipping invalid manifest filename: %s", path)
                    continue

        except OSError as e:
            logger.error("Failed to list manifests: %s", e)

        # Sort by timestamp, newest first
        manifests.sort(key=lambda m: m.timestamp, reverse=True)
        return manifests

    def undo_manifest(
        self,
        manifest_path: Path | str,
        progress_callback: Optional[ProgressCallback] = None,
        log_callback: Optional[LogCallback] = None,
        error_log_callback: Optional[ErrorLogCallback] = None,
        should_cancel: Optional[ShouldCancelCallback] = None,
    ) -> UndoResult:
        """
        Undo all moves recorded in a manifest file.

        Reads the manifest and reverses each move (dest → source),
        recreating source directories as needed.

        Args:
            manifest_path: Path to manifest file to undo
            progress_callback: Called with (current, total) for each file
            log_callback: Called with status messages
            error_log_callback: Called with (context, file, error) on failures
            should_cancel: Optional callable returning True to stop early

        Returns:
            UndoResult with success/failed/total counts
        """
        manifest_path = Path(manifest_path)
        result = UndoResult(success_count=0, failed_count=0, total_count=0)

        if not manifest_path.exists():
            if log_callback:
                log_callback(f"Manifest not found: {manifest_path}")
            return result

        # Read and parse manifest
        moves: List[tuple[Path, Path]] = []
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Parse source|dest format (works with both POSIX and Windows paths)
                    if "|" not in line:
                        continue

                    parts = line.split("|", 1)
                    if len(parts) != 2:
                        continue

                    source = Path(parts[0])
                    dest = Path(parts[1])
                    moves.append((source, dest))

        except OSError as e:
            logger.error("Failed to read manifest: %s", e)
            if log_callback:
                log_callback(f"Failed to read manifest: {e}")
            return result

        result.total_count = len(moves)

        if log_callback:
            log_callback(f"Undoing {result.total_count} moves from manifest")

        # Reverse each move (dest → source)
        for i, (source, dest) in enumerate(moves):
            # Check for cancellation before each file
            if should_cancel is not None and should_cancel():
                if log_callback:
                    log_callback(f"Undo cancelled after {result.success_count} files")
                break

            try:
                # Check if destination file exists
                if not dest.exists():
                    logger.warning("Destination file missing, skipping: %s", dest)
                    if error_log_callback:
                        error_log_callback("UNDO_MISSING", str(dest), "File not found")
                    result.failed_count += 1
                    continue

                # Recreate source directory if needed
                source.parent.mkdir(parents=True, exist_ok=True)

                # Move file back to original location
                shutil.move(str(dest), str(source))
                result.success_count += 1
                logger.debug("Restored: %s -> %s", dest, source)

            except (OSError, shutil.Error) as e:
                logger.error("Failed to restore %s: %s", dest, e)
                if error_log_callback:
                    error_log_callback("UNDO_FAILED", str(dest), str(e))
                result.failed_count += 1

            # Progress callback
            if progress_callback:
                progress_callback(i + 1, result.total_count)

        if log_callback:
            log_callback(
                f"Undo complete: {result.success_count} restored, "
                f"{result.failed_count} failed"
            )

        return result

    def delete_manifest(self, manifest_path: Path | str) -> bool:
        """
        Delete a manifest file.

        Args:
            manifest_path: Path to manifest file to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        manifest_path = Path(manifest_path)

        try:
            if manifest_path.exists():
                manifest_path.unlink()
                logger.info("Deleted manifest: %s", manifest_path)
                return True
            return False
        except OSError as e:
            logger.error("Failed to delete manifest: %s", e)
            return False


__all__ = [
    "ManifestManager",
    "ManifestUndoer",
    "ManifestInfo",
    "UndoResult",
    "DEFAULT_MANIFEST_DIR",
    "ShouldCancelCallback",
]
