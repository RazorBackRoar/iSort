# utils/checkpoint.py
"""
Checkpoint save/load/clear system for resume functionality.

Ports checkpoint logic from isort.zsh lines 127-160.

Enables resuming interrupted operations by persisting phase and index to disk.
Default checkpoint file: ~/Desktop/isort.checkpoint

Usage:
    # As callback for FileOrganizer
    checkpoint_mgr = CheckpointManager()
    organizer = FileOrganizer(checkpoint_callback=checkpoint_mgr.save)

    # With context manager (auto-clear on success)
    with CheckpointManager() as checkpoint_mgr:
        organizer = FileOrganizer(checkpoint_callback=checkpoint_mgr.save)
        organizer.organize(folder_path)
    # Checkpoint automatically cleared on successful exit

    # Manual load/clear
    phase, index = checkpoint_mgr.load()
    checkpoint_mgr.clear()
"""

import logging
import tempfile
from pathlib import Path
from typing import Tuple, Optional, Union

logger = logging.getLogger(__name__)

# Default checkpoint location on Desktop
DEFAULT_CHECKPOINT_PATH = Path.home() / "Desktop" / "isort.checkpoint"


class CheckpointManager:
    """
    Manages checkpoint persistence for resuming interrupted operations.

    Saves phase and index to a pipe-delimited file, enabling resume
    after crashes or interruptions.
    """

    def __init__(self, checkpoint_path: Path | str | None = None):
        """
        Initialize the CheckpointManager.

        Args:
            checkpoint_path: Path to checkpoint file (default: ~/Desktop/isort.checkpoint)
        """
        if checkpoint_path is None:
            self.checkpoint_path = DEFAULT_CHECKPOINT_PATH
        else:
            self.checkpoint_path = Path(checkpoint_path)

    def save(self, phase: str, index: int, folder_path: Path | str) -> None:
        """
        Save checkpoint to disk.

        Uses atomic write (temp file + rename) to prevent corruption.

        Args:
            phase: Current phase name (e.g., "extract", "organize")
            index: Current file index within the phase
            folder_path: Path of the folder being processed (to prevent stale resume)
        """
        try:
            # Atomic write: write to temp file, then rename
            temp_path = self.checkpoint_path.with_suffix(".tmp")
            temp_path.write_text(
                f"{phase}|{index}|{str(folder_path)}\n", encoding="utf-8"
            )
            temp_path.rename(self.checkpoint_path)
            logger.debug("Checkpoint saved: %s|%d|%s", phase, index, folder_path)
        except OSError as e:
            logger.warning("Failed to save checkpoint: %s", e)

    def load(self) -> Tuple[str, int, str | None, bool]:
        """
        Load checkpoint from disk.

        Returns:
            Tuple of (phase, index, saved_folder, is_invalid), or ("none", 0, None, False) if no checkpoint exists.
            is_invalid is True if the checkpoint file exists but is corrupted/incompatible.
        """
        if not self.checkpoint_path.exists():
            return ("none", 0, None, False)

        try:
            content = self.checkpoint_path.read_text(encoding="utf-8").strip()
            if "|" not in content:
                logger.warning("Invalid checkpoint format: %s", content)
                return ("none", 0, None, True)

            parts = content.split("|")
            if len(parts) < 2:
                return ("none", 0, None, True)

            phase = parts[0]
            index = int(parts[1])

            # Handle legacy checkpoints without folder path
            saved_folder = parts[2] if len(parts) > 2 else None

            logger.info("Loaded checkpoint: %s|%d|%s", phase, index, saved_folder)
            return (phase, index, saved_folder, False)

        except (OSError, ValueError) as e:
            logger.warning("Failed to load checkpoint: %s", e)
            return ("none", 0, None, True)

    def clear(self) -> None:
        """
        Remove checkpoint file from disk.

        Called after successful completion to prevent stale resume.
        """
        try:
            if self.checkpoint_path.exists():
                self.checkpoint_path.unlink()
                logger.info("Checkpoint cleared")
        except OSError as e:
            logger.warning("Failed to clear checkpoint: %s", e)

    def exists(self) -> bool:
        """
        Check if a checkpoint file exists.

        Returns:
            True if checkpoint file exists on disk
        """
        return self.checkpoint_path.exists()

    def __enter__(self) -> "CheckpointManager":
        """Context manager entry - returns self for use."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - auto-clear checkpoint on success."""
        if exc_type is None:
            # No exception occurred, clear checkpoint
            self.clear()
        # Don't suppress exceptions


__all__ = ["CheckpointManager", "DEFAULT_CHECKPOINT_PATH"]
