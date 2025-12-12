# core/hasher.py
"""
Smart partial hashing module for efficient duplicate detection.

For files under 100MB, computes full MD5 hash.
For files >= 100MB, computes partial hash using:
- First 1MB chunk
- Middle 1MB chunk
- Last 1MB chunk
- File size

This approach provides fast hashing for large video files while
maintaining uniqueness for duplicate detection.
"""

import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 100MB threshold for partial hashing
HASH_THRESHOLD = 100 * 1024 * 1024

# 1MB chunk size for partial hashing
CHUNK_SIZE = 1024 * 1024


# Error sentinel matching ZSH script behavior
HASH_ERROR = "ERROR"


class SmartHasher:
    """
    Smart file hasher with partial hashing for large files.

    Files < 100MB: Full MD5 hash
    Files >= 100MB: Partial hash (start + middle + end chunks + size)

    Note: Hash output is compatible with the ZSH compute_smart_hash function.
    The partial hash includes a newline after file size to match ZSH's echo behavior.
    On error, returns "ERROR" sentinel to match ZSH script behavior.
    """

    def compute_hash(self, filepath: str) -> str:
        """
        Compute hash for a file using smart partial hashing.

        Args:
            filepath: Path to the file to hash

        Returns:
            Hexadecimal MD5 hash string, or "ERROR" sentinel on failure
        """
        try:
            file_size = os.path.getsize(filepath)

            if file_size < HASH_THRESHOLD:
                return self._compute_full_hash(filepath)
            else:
                return self._compute_partial_hash(filepath, file_size)

        except FileNotFoundError:
            logger.error("File not found: %s", filepath)
            return HASH_ERROR
        except PermissionError:
            logger.error("Permission denied: %s", filepath)
            return HASH_ERROR
        except OSError as e:
            logger.error("OS error hashing %s: %s", filepath, e)
            return HASH_ERROR

    def _compute_full_hash(self, filepath: str) -> str:
        """
        Compute full MD5 hash of a file.

        Args:
            filepath: Path to the file

        Returns:
            Hexadecimal MD5 hash string
        """
        hasher = hashlib.md5()

        with open(filepath, "rb") as f:
            # Read in chunks to handle memory efficiently
            for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
                hasher.update(chunk)

        return hasher.hexdigest()

    def _compute_partial_hash(self, filepath: str, file_size: int) -> str:
        """
        Compute partial hash using three chunks plus file size.

        Reads 1MB from start, middle, and end of file, then combines
        with file size for hash computation.

        Args:
            filepath: Path to the file
            file_size: Size of the file in bytes

        Returns:
            Hexadecimal MD5 hash string
        """
        hasher = hashlib.md5()

        # Calculate offsets
        middle_offset = (file_size // 2) - (CHUNK_SIZE // 2)
        end_offset = file_size - CHUNK_SIZE

        with open(filepath, "rb") as f:
            # Read first chunk (start of file)
            start_chunk = self._read_chunk(f, 0, CHUNK_SIZE)
            hasher.update(start_chunk)

            # Read middle chunk
            middle_chunk = self._read_chunk(f, middle_offset, CHUNK_SIZE)
            hasher.update(middle_chunk)

            # Read last chunk (end of file)
            end_chunk = self._read_chunk(f, end_offset, CHUNK_SIZE)
            hasher.update(end_chunk)

            # Include file size in hash computation
            # Note: Append newline to match ZSH's echo behavior for cross-compatibility
            hasher.update(f"{file_size}\n".encode("utf-8"))

        return hasher.hexdigest()

    def _read_chunk(self, file_handle, offset: int, size: int) -> bytes:
        """
        Seek to offset and read a chunk of bytes.

        Args:
            file_handle: Open file handle
            offset: Byte offset to seek to
            size: Number of bytes to read

        Returns:
            Bytes read from file
        """
        file_handle.seek(offset)
        return file_handle.read(size)


__all__ = [
    "SmartHasher",
    "HASH_THRESHOLD",
    "CHUNK_SIZE",
    "HASH_ERROR",
]
