# utils/error_log.py
"""
Centralized error logging utilities.

Ports error logging logic from isort.zsh lines 200-220.

Provides timestamped error logging to Desktop file for debugging
and user review. Thread-safe via append mode.

Usage:
    # As standalone logger
    with ErrorLogger() as error_log:
        error_log.log_error("HASH_MISMATCH", "/path/to/file.jpg", "src=abc dst=def")

    # As callback for operations
    error_logger = ErrorLogger()
    error_logger.initialize()
    undoer.undo_manifest(manifest_path, error_log_callback=error_logger.log_error)
    error_logger.close()
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default error log directory
DEFAULT_ERROR_LOG_DIR = Path.home() / "Desktop"


class ErrorLogger:
    """
    Centralized error logging to timestamped Desktop file.

    Creates timestamped log files on Desktop, recording errors with
    context, file path, and error message for debugging.

    Format:
        [YYYY-MM-DD HH:MM:SS] CONTEXT: /path/to/file - Error message

    Note:
        By default, empty log files (no errors logged) are removed on close()
        to reduce clutter. Set keep_empty=True in constructor to preserve
        empty logs for audit trails.
    """

    def __init__(
        self,
        log_path: Path | str | None = None,
        log_dir: Path | str | None = None,
        keep_empty: bool = False,
    ):
        """
        Initialize the ErrorLogger.

        Args:
            log_path: Explicit path to log file (overrides log_dir)
            log_dir: Directory for log files (default: ~/Desktop)
            keep_empty: If True, preserve empty log files on close; if False
                        (default), remove log files with no errors for cleanliness
        """
        if log_path is not None:
            self.log_path = Path(log_path)
        else:
            if log_dir is None:
                log_dir = DEFAULT_ERROR_LOG_DIR
            else:
                log_dir = Path(log_dir)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_path = log_dir / f"isort_errors_{timestamp}.log"

        self._initialized = False
        self._error_count = 0
        self._keep_empty = keep_empty

    def initialize(self) -> None:
        """
        Create error log file with header.

        Called automatically by context manager or manually before logging.
        """
        if self._initialized:
            return

        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f"=== iSort Error Log - {date_str} ===\n\n"

            self.log_path.write_text(header, encoding="utf-8")
            self._initialized = True
            logger.info("Error log initialized: %s", self.log_path)

        except OSError as e:
            logger.warning("Failed to initialize error log: %s", e)
            # Continue without file logging - will fall back to stderr

    def log_error(self, context: str, file: str, error: str) -> None:
        """
        Log an error to the error log file.

        Args:
            context: Error context/type (e.g., "HASH_MISMATCH", "ROLLBACK_FAILED")
            file: File path associated with the error
            error: Error message/description
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {context}: {file} - {error}\n"

        self._error_count += 1

        # Try to write to file
        if self._initialized:
            try:
                # Append mode for thread-safety
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(log_line)
                return
            except OSError as e:
                logger.warning("Failed to write to error log: %s", e)

        # Fallback to stderr if file logging fails
        print(log_line.strip(), file=sys.stderr)

    @property
    def error_count(self) -> int:
        """Return the number of errors logged."""
        return self._error_count

    def close(self) -> None:
        """
        Finalize the error log file.

        Adds footer with error count if any errors were logged.
        Called automatically by context manager or manually after logging.
        """
        if self._initialized and self._error_count > 0:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n=== Total errors: {self._error_count} ===\n")
                logger.info(
                    "Error log finalized: %s (%d errors)",
                    self.log_path,
                    self._error_count,
                )
            except OSError as e:
                logger.warning("Failed to finalize error log: %s", e)
        elif self._initialized and self._error_count == 0:
            if self._keep_empty:
                # Preserve empty log for audit trail
                logger.debug("Keeping empty error log: %s", self.log_path)
            else:
                # Remove empty log file to reduce clutter
                try:
                    self.log_path.unlink()
                    logger.debug("Removed empty error log: %s", self.log_path)
                except OSError:
                    pass

    def __enter__(self) -> "ErrorLogger":
        """Context manager entry - initialize error log."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close error log."""
        self.close()


__all__ = ["ErrorLogger", "DEFAULT_ERROR_LOG_DIR"]
