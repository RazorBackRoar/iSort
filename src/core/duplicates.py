# core/duplicates.py
"""
Duplicate detection and cross-folder comparison module.

Ports duplicate detection logic from isort.zsh lines 961-1124 and
cross-folder comparison from lines 1126-1310.

Provides:
- DuplicateDetector: Single-folder duplicate detection with hash-based grouping
- FolderComparator: Cross-folder comparison to find matching/unique files

Usage:
    detector = DuplicateDetector()
    result = detector.find_duplicates("/path/to/folder", "/path/to/output")

    comparator = FolderComparator()
    result = comparator.compare_folders("/path/a", "/path/b", "/path/to/output")
"""

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from core.hasher import HASH_ERROR, SmartHasher
from core.metadata import VIDEO_EXTENSIONS, MetadataExtractor, get_file_extension
from core.organizer import format_file_size

logger = logging.getLogger(__name__)

# Type aliases for callbacks
ProgressCallback = Callable[[int, int], None]
ProgressCallbackWithLabel = Callable[[int, int, str], None]
ErrorLogCallback = Callable[[str, str, str], None]  # context, file, error


@dataclass
class DuplicateGroup:
    """Represents a group of duplicate files sharing the same hash."""

    hash: str
    file_size: int
    file_paths: List[Path] = field(default_factory=list)
    video_durations: List[Optional[str]] = field(default_factory=list)

    @property
    def count(self) -> int:
        """Number of files in this duplicate group."""
        return len(self.file_paths)

    @property
    def wasted_space(self) -> int:
        """Space wasted by duplicates (all but one copy)."""
        return self.file_size * (self.count - 1) if self.count > 1 else 0


@dataclass
class DuplicateResult:
    """Result statistics from duplicate detection."""

    total_files: int = 0
    duplicate_groups: int = 0
    duplicate_files: int = 0
    wasted_space_bytes: int = 0
    errors: int = 0
    output_txt: Optional[Path] = None
    output_csv: Optional[Path] = None


@dataclass
class ComparisonResult:
    """Result statistics from cross-folder comparison."""

    count_a: int = 0
    count_b: int = 0
    size_a: int = 0
    size_b: int = 0
    match_count: int = 0
    match_size_bytes: int = 0
    unique_a_count: int = 0
    unique_b_count: int = 0
    errors: int = 0
    output_txt: Optional[Path] = None
    output_csv: Optional[Path] = None


class DuplicateDetector:
    """
    Single-folder duplicate detection using hash-based grouping.

    Scans a folder recursively, computes smart hashes for all files,
    groups files by hash, and generates TXT/CSV reports of duplicates.
    """

    def __init__(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        error_log_callback: Optional[ErrorLogCallback] = None,
    ):
        """
        Initialize the DuplicateDetector.

        Args:
            progress_callback: Called with (current, total) every 50 files
            error_log_callback: Called with (context, file, error) for persistent logging
        """
        self.hasher = SmartHasher()
        self.extractor = MetadataExtractor()
        self.progress_callback = progress_callback
        self.error_log_callback = error_log_callback

    def find_duplicates(
        self,
        folder_path: str | Path,
        output_dir: str | Path,
    ) -> DuplicateResult:
        """
        Find duplicate files in a folder.

        Args:
            folder_path: Folder to scan for duplicates
            output_dir: Directory to write output reports

        Returns:
            DuplicateResult with statistics and output file paths
        """
        folder_path = Path(folder_path)
        output_dir = Path(output_dir)

        # Validate inputs
        if not folder_path.exists():
            raise ValueError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ValueError(f"Path is not a directory: {folder_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        result = DuplicateResult()

        # Scan all files
        logger.info("Scanning folder for duplicates: %s", folder_path)
        all_files = [f for f in folder_path.rglob("*") if f.is_file()]
        total = len(all_files)
        result.total_files = total

        # Build hash-to-files mapping (may be empty if no files)
        hash_map: Dict[str, List[Tuple[Path, int, Optional[str]]]] = {}

        for i, filepath in enumerate(all_files):
            try:
                # Compute hash
                file_hash = self.hasher.compute_hash(str(filepath))
                if file_hash == HASH_ERROR:
                    logger.error("Failed to hash file: %s", filepath)
                    if self.error_log_callback:
                        self.error_log_callback(
                            "HASH_ERROR", str(filepath), "Failed to compute MD5 hash"
                        )
                    result.errors += 1
                    continue

                # Get file size
                file_size = filepath.stat().st_size

                # Get video duration if applicable
                ext = get_file_extension(str(filepath))
                duration: Optional[str] = None
                if ext in VIDEO_EXTENSIONS:
                    dur, _, _ = self.extractor.get_video_metadata(str(filepath))
                    duration = dur if dur else None

                # Add to hash map
                if file_hash not in hash_map:
                    hash_map[file_hash] = []
                hash_map[file_hash].append((filepath, file_size, duration))

            except (OSError, PermissionError) as e:
                logger.error("Error processing file %s: %s", filepath, e)
                if self.error_log_callback:
                    self.error_log_callback("FILE_ERROR", str(filepath), str(e))
                result.errors += 1
                continue

            # Progress callback every 50 files
            if self.progress_callback and ((i + 1) % 50 == 0 or i == total - 1):
                self.progress_callback(i + 1, total)

        # Filter to only duplicates (2+ files with same hash)
        duplicate_groups: List[DuplicateGroup] = []
        for file_hash, files in hash_map.items():
            if len(files) >= 2:
                group = DuplicateGroup(
                    hash=file_hash,
                    file_size=files[0][1],  # All files have same size
                    file_paths=[f[0] for f in files],
                    video_durations=[f[2] for f in files],
                )
                duplicate_groups.append(group)
                result.duplicate_files += len(files)
                result.wasted_space_bytes += group.wasted_space

        result.duplicate_groups = len(duplicate_groups)

        # Generate reports (always when files were scanned, even if no duplicates)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = folder_path.name or "root"
        base_name = f"duplicates_{folder_name}_{timestamp}"

        result.output_txt = output_dir / f"{base_name}.txt"
        result.output_csv = output_dir / f"{base_name}.csv"

        self._write_duplicate_report(
            duplicate_groups,
            result,
            folder_path,
            result.output_txt,
            result.output_csv,
        )

        logger.info(
            "Duplicate detection complete: %d groups, %s wasted",
            result.duplicate_groups,
            format_file_size(result.wasted_space_bytes),
        )

        return result

    def _write_duplicate_report(
        self,
        groups: List[DuplicateGroup],
        result: DuplicateResult,
        folder_path: Path,
        txt_path: Path,
        csv_path: Path,
    ) -> None:
        """Write duplicate detection reports in TXT and CSV formats."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Write TXT report
        with open(txt_path, "w", encoding="utf-8") as f:
            # Header
            f.write(
                "╔════════════════════════════════════════════════════════════════════════════════╗\n"
            )
            f.write(
                "║                          🔍 DUPLICATE FILE REPORT                              ║\n"
            )
            f.write(
                "╠════════════════════════════════════════════════════════════════════════════════╣\n"
            )
            f.write(f"║  Generated: {timestamp:<66}║\n")
            f.write(f"║  Source:    {str(folder_path):<66}║\n")
            f.write(f"║  Files:     {result.total_files:<66}║\n")
            f.write(
                "╚════════════════════════════════════════════════════════════════════════════════╝\n\n"
            )

            # Duplicate groups (may be empty)
            if not groups:
                f.write("No duplicate files found.\n\n")

            for i, group in enumerate(groups, 1):
                hash_short = group.hash[:12]
                f.write(
                    "┌────────────────────────────────────────────────────────────────────────────────┐\n"
                )
                f.write(
                    f"│  📦 Duplicate Group #{i} (MD5: {hash_short}){' ' * (46 - len(str(i)) - len(hash_short))}│\n"
                )
                f.write(
                    "├────────────────────────────────────────────────────────────────────────────────┤\n"
                )

                for j, (filepath, duration) in enumerate(
                    zip(group.file_paths, group.video_durations)
                ):
                    f.write(f"│  {filepath.name}\n")
                    size_str = format_file_size(group.file_size)
                    dur_str = duration if duration else "N/A"
                    f.write(f"│    Size: {size_str:<15} Duration: {dur_str}\n")
                    f.write(f"│    Path: {filepath}\n")
                    if j < len(group.file_paths) - 1:
                        f.write("│\n")

                f.write(
                    "└────────────────────────────────────────────────────────────────────────────────┘\n\n"
                )

            # Footer summary
            f.write(
                "╔════════════════════════════════════════════════════════════════════════════════╗\n"
            )
            f.write(
                "║                                   SUMMARY                                      ║\n"
            )
            f.write(
                "╠════════════════════════════════════════════════════════════════════════════════╣\n"
            )
            f.write(f"║  Total files scanned:    {result.total_files:<53}║\n")
            f.write(f"║  Duplicate groups found: {result.duplicate_groups:<53}║\n")
            f.write(f"║  Total duplicate files:  {result.duplicate_files:<53}║\n")
            f.write(
                f"║  Wasted space:           {format_file_size(result.wasted_space_bytes):<53}║\n"
            )
            f.write(
                "╚════════════════════════════════════════════════════════════════════════════════╝\n\n"
            )

            # Legend
            f.write("Legend:\n")
            f.write("  📦 = Duplicate group (files with identical content)\n")
            f.write(
                "  Wasted space = Size of all duplicates minus one copy per group\n"
            )

        # Write CSV report
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(
                [
                    "MD5 Hash",
                    "File Size",
                    "Duration",
                    "Filename",
                    "Full Path",
                    "Duplicate Group",
                ]
            )

            for i, group in enumerate(groups, 1):
                for filepath, duration in zip(group.file_paths, group.video_durations):
                    writer.writerow(
                        [
                            group.hash,
                            group.file_size,
                            duration or "N/A",
                            filepath.name,
                            str(filepath),
                            i,
                        ]
                    )

        logger.info("Wrote duplicate reports: %s, %s", txt_path, csv_path)


class FolderComparator:
    """
    Cross-folder comparison to find matching and unique files.

    Compares two folders by computing hashes for all files and
    identifying files that exist in both, only in A, or only in B.
    """

    def __init__(
        self,
        progress_callback: Optional[ProgressCallbackWithLabel] = None,
        error_log_callback: Optional[ErrorLogCallback] = None,
    ):
        """
        Initialize the FolderComparator.

        Args:
            progress_callback: Called with (current, total, label) every 100 files
            error_log_callback: Called with (context, file, error) for persistent logging
        """
        self.hasher = SmartHasher()
        self.progress_callback = progress_callback
        self.error_log_callback = error_log_callback

    def compare_folders(
        self,
        folder_a: str | Path,
        folder_b: str | Path,
        output_dir: str | Path,
    ) -> ComparisonResult:
        """
        Compare two folders to find matching and unique files.

        Args:
            folder_a: First folder to compare
            folder_b: Second folder to compare
            output_dir: Directory to write output reports

        Returns:
            ComparisonResult with statistics and output file paths
        """
        folder_a = Path(folder_a)
        folder_b = Path(folder_b)
        output_dir = Path(output_dir)

        # Validate inputs
        for folder, name in [(folder_a, "Folder A"), (folder_b, "Folder B")]:
            if not folder.exists():
                raise ValueError(f"{name} does not exist: {folder}")
            if not folder.is_dir():
                raise ValueError(f"{name} is not a directory: {folder}")

        output_dir.mkdir(parents=True, exist_ok=True)

        result = ComparisonResult()

        # Scan folder A
        logger.info("Scanning Folder A: %s", folder_a)
        hashes_a, result.count_a, result.size_a, errors_a = self._scan_folder(
            folder_a, "Folder A"
        )
        result.errors += errors_a

        # Scan folder B
        logger.info("Scanning Folder B: %s", folder_b)
        hashes_b, result.count_b, result.size_b, errors_b = self._scan_folder(
            folder_b, "Folder B"
        )
        result.errors += errors_b

        # Find common and unique hashes
        common_hashes = set(hashes_a.keys()) & set(hashes_b.keys())
        unique_a = set(hashes_a.keys()) - set(hashes_b.keys())
        unique_b = set(hashes_b.keys()) - set(hashes_a.keys())

        result.match_count = len(common_hashes)
        result.unique_a_count = len(unique_a)
        result.unique_b_count = len(unique_b)

        # Calculate match size
        for h in common_hashes:
            result.match_size_bytes += hashes_a[h][1]  # Use size from folder A

        # Generate reports
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_a = folder_a.name or "root_a"
        name_b = folder_b.name or "root_b"
        base_name = f"compare_{name_a}_vs_{name_b}_{timestamp}"

        result.output_txt = output_dir / f"{base_name}.txt"
        result.output_csv = output_dir / f"{base_name}.csv"

        self._write_comparison_report(
            hashes_a,
            hashes_b,
            common_hashes,
            result,
            folder_a,
            folder_b,
            result.output_txt,
            result.output_csv,
        )

        logger.info(
            "Comparison complete: %d matches, %d unique to A, %d unique to B",
            result.match_count,
            result.unique_a_count,
            result.unique_b_count,
        )

        return result

    def _scan_folder(
        self,
        folder_path: Path,
        label: str,
    ) -> Tuple[Dict[str, Tuple[Path, int]], int, int, int]:
        """
        Scan a folder and build hash-to-file mapping.

        Returns:
            Tuple of (hash_map, file_count, total_size, error_count)
        """
        hash_map: Dict[str, Tuple[Path, int]] = {}
        total_size = 0
        errors = 0

        all_files = [f for f in folder_path.rglob("*") if f.is_file()]
        total = len(all_files)

        for i, filepath in enumerate(all_files):
            try:
                file_hash = self.hasher.compute_hash(str(filepath))
                if file_hash == HASH_ERROR:
                    logger.error("Failed to hash file: %s", filepath)
                    if self.error_log_callback:
                        self.error_log_callback(
                            "HASH_ERROR", str(filepath), "Failed to compute MD5 hash"
                        )
                    errors += 1
                    continue

                file_size = filepath.stat().st_size
                total_size += file_size

                # Store first occurrence of each hash
                if file_hash not in hash_map:
                    hash_map[file_hash] = (filepath, file_size)

            except (OSError, PermissionError) as e:
                logger.error("Error processing file %s: %s", filepath, e)
                if self.error_log_callback:
                    self.error_log_callback("FILE_ERROR", str(filepath), str(e))
                errors += 1
                continue

            # Progress callback every 100 files
            if self.progress_callback and ((i + 1) % 100 == 0 or i == total - 1):
                self.progress_callback(i + 1, total, label)

        return hash_map, total, total_size, errors

    def _write_comparison_report(
        self,
        hashes_a: Dict[str, Tuple[Path, int]],
        hashes_b: Dict[str, Tuple[Path, int]],
        common_hashes: Set[str],
        result: ComparisonResult,
        folder_a: Path,
        folder_b: Path,
        txt_path: Path,
        csv_path: Path,
    ) -> None:
        """Write comparison reports in TXT and CSV formats."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Write TXT report
        with open(txt_path, "w", encoding="utf-8") as f:
            # Header
            f.write(
                "╔════════════════════════════════════════════════════════════════════════════════╗\n"
            )
            f.write(
                "║                      🔄 CROSS-FOLDER COMPARISON REPORT                         ║\n"
            )
            f.write(
                "╠════════════════════════════════════════════════════════════════════════════════╣\n"
            )
            f.write(f"║  Generated:  {timestamp:<65}║\n")
            f.write(f"║  Folder A:   {str(folder_a):<65}║\n")
            f.write(f"║  Folder B:   {str(folder_b):<65}║\n")
            f.write(
                "╚════════════════════════════════════════════════════════════════════════════════╝\n\n"
            )

            # Matching files section
            f.write(
                "┌────────────────────────────────────────────────────────────────────────────────┐\n"
            )
            f.write(
                "│              🔗 MATCHING FILES (exist in BOTH folders)                         │\n"
            )
            f.write(
                "└────────────────────────────────────────────────────────────────────────────────┘\n\n"
            )

            for i, file_hash in enumerate(sorted(common_hashes), 1):
                path_a, size = hashes_a[file_hash]
                path_b, _ = hashes_b[file_hash]
                hash_short = file_hash[:16]

                f.write(
                    "┌────────────────────────────────────────────────────────────────────────────────┐\n"
                )
                f.write(
                    f"│  Match #{i} | Size: {format_file_size(size):<12} | Hash: {hash_short}{' ' * (30 - len(hash_short))}│\n"
                )
                f.write(
                    "├────────────────────────────────────────────────────────────────────────────────┤\n"
                )
                f.write(f"│  A: {path_a.name}\n")
                f.write(f"│     {path_a}\n")
                f.write(f"│  B: {path_b.name}\n")
                f.write(f"│     {path_b}\n")
                f.write(
                    "└────────────────────────────────────────────────────────────────────────────────┘\n\n"
                )

            # Summary footer
            f.write(
                "╔════════════════════════════════════════════════════════════════════════════════╗\n"
            )
            f.write(
                "║                                   SUMMARY                                      ║\n"
            )
            f.write(
                "╠════════════════════════════════════════════════════════════════════════════════╣\n"
            )
            f.write(
                f"║  Folder A files:    {result.count_a:<10} ({format_file_size(result.size_a):<20}){' ' * 26}║\n"
            )
            f.write(
                f"║  Folder B files:    {result.count_b:<10} ({format_file_size(result.size_b):<20}){' ' * 26}║\n"
            )
            f.write(
                "║  ──────────────────────────────────────────────────────────────────────────────║\n"
            )
            f.write(
                f"║  Matching files:    {result.match_count:<10} ({format_file_size(result.match_size_bytes):<20}){' ' * 26}║\n"
            )
            f.write(f"║  Unique to A:       {result.unique_a_count:<58}║\n")
            f.write(f"║  Unique to B:       {result.unique_b_count:<58}║\n")
            f.write(
                "╚════════════════════════════════════════════════════════════════════════════════╝\n"
            )

        # Write CSV report
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(["Hash", "Size", "Folder A Path", "Folder B Path"])

            for file_hash in sorted(common_hashes):
                path_a, size = hashes_a[file_hash]
                path_b, _ = hashes_b[file_hash]
                writer.writerow([file_hash, size, str(path_a), str(path_b)])

        logger.info("Wrote comparison reports: %s, %s", txt_path, csv_path)


__all__ = [
    "DuplicateGroup",
    "DuplicateResult",
    "DuplicateDetector",
    "ComparisonResult",
    "FolderComparator",
]
