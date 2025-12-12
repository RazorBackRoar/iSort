# core/inventory.py
"""
Comprehensive file inventory generation module.

Ports inventory logging logic from isort.zsh lines 653-809.

Provides:
- InventoryGenerator: Generates detailed metadata inventory with TXT/CSV outputs

Extracts 17 metadata fields per file:
- Directory, Filename, Size (bytes), Size (human), Created, Modified
- MD5 Hash, Has Camera, Make, Model, Has GPS, GPS Latitude, GPS Longitude
- Duration, Resolution, Codec, Full Path

Usage:
    generator = InventoryGenerator()
    result = generator.generate_inventory("/path/to/folder", "/path/to/output")
"""

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from isort_app.core.hasher import HASH_ERROR, SmartHasher
from isort_app.core.metadata import MetadataExtractor
from isort_app.core.organizer import format_file_size

logger = logging.getLogger(__name__)

# Type alias for progress callback
ProgressCallback = Callable[[int, int], None]
ErrorLogCallback = Callable[[str, str, str], None]  # context, file, error


@dataclass
class FileInventoryEntry:
    """Represents metadata for a single file in the inventory."""

    directory: str
    filename: str
    size_bytes: int
    size_human: str
    created: str
    modified: str
    md5_hash: str
    has_camera: bool
    make: str
    model: str
    has_gps: bool
    gps_latitude: str
    gps_longitude: str
    duration: str
    resolution: str
    codec: str
    full_path: str


@dataclass
class InventoryResult:
    """Result statistics from inventory generation."""

    total_files: int = 0
    total_size_bytes: int = 0
    directories_count: int = 0
    errors: int = 0
    output_txt: Optional[Path] = None
    output_csv: Optional[Path] = None


class InventoryGenerator:
    """
    Generates comprehensive file inventory with metadata extraction.

    Scans a folder recursively, extracts detailed metadata for each file,
    and generates formatted TXT/CSV reports grouped by directory.
    """

    def __init__(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        error_log_callback: Optional[ErrorLogCallback] = None,
    ):
        """
        Initialize the InventoryGenerator.

        Args:
            progress_callback: Called with (current, total) every 10 files
            error_log_callback: Called with (context, file, error) for persistent logging
        """
        self.hasher = SmartHasher()
        self.extractor = MetadataExtractor()
        self.progress_callback = progress_callback
        self.error_log_callback = error_log_callback

    def generate_inventory(
        self,
        folder_path: str | Path,
        output_dir: str | Path,
    ) -> InventoryResult:
        """
        Generate a comprehensive file inventory.

        Args:
            folder_path: Folder to inventory
            output_dir: Directory to write output reports

        Returns:
            InventoryResult with statistics and output file paths
        """
        folder_path = Path(folder_path)
        output_dir = Path(output_dir)

        # Validate inputs
        if not folder_path.exists():
            raise ValueError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ValueError(f"Path is not a directory: {folder_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        result = InventoryResult()

        # Scan all files
        logger.info("Generating inventory for: %s", folder_path)
        all_files = sorted(
            [f for f in folder_path.rglob("*") if f.is_file()],
            key=lambda p: (p.parent, p.name),
        )
        total = len(all_files)
        result.total_files = total

        # Group entries by directory
        entries_by_dir: Dict[str, List[FileInventoryEntry]] = {}

        for i, filepath in enumerate(all_files):
            try:
                entry, hash_error = self._extract_file_metadata(filepath, folder_path)
                result.total_size_bytes += entry.size_bytes

                # Count hash failures as errors
                if hash_error:
                    result.errors += 1

                # Group by directory
                if entry.directory not in entries_by_dir:
                    entries_by_dir[entry.directory] = []
                entries_by_dir[entry.directory].append(entry)

            except (OSError, PermissionError) as e:
                logger.error("Error processing file %s: %s", filepath, e)
                if self.error_log_callback:
                    self.error_log_callback("FILE_ERROR", str(filepath), str(e))
                result.errors += 1
                continue

            # Progress callback every 10 files
            if self.progress_callback and ((i + 1) % 10 == 0 or i == total - 1):
                self.progress_callback(i + 1, total)

        result.directories_count = len(entries_by_dir)

        # Generate reports
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = folder_path.name or "root"
        base_name = f"inventory_{folder_name}_{timestamp}"

        result.output_txt = output_dir / f"{base_name}.txt"
        result.output_csv = output_dir / f"{base_name}.csv"

        self._write_inventory_report(
            entries_by_dir, result, folder_path, result.output_txt, result.output_csv
        )

        logger.info(
            "Inventory complete: %d files, %s total",
            result.total_files,
            format_file_size(result.total_size_bytes),
        )

        return result

    def _extract_file_metadata(
        self,
        filepath: Path,
        root_folder: Path,
    ) -> tuple[FileInventoryEntry, bool]:
        """
        Extract comprehensive metadata for a single file.

        Returns:
            Tuple of (FileInventoryEntry, hash_error_occurred)
        """
        # File stats
        stat = filepath.stat()
        size_bytes = stat.st_size
        size_human = format_file_size(size_bytes)

        # Timestamps
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        # st_birthtime is macOS-specific; fall back to mtime on other platforms
        birthtime = getattr(stat, "st_birthtime", None)
        if birthtime is not None:
            created = datetime.fromtimestamp(birthtime).strftime("%Y-%m-%d %H:%M")
        else:
            logger.debug("st_birthtime not available, using mtime for: %s", filepath)
            created = modified

        # Compute hash
        hash_error = False
        md5_hash = self.hasher.compute_hash(str(filepath))
        if md5_hash == HASH_ERROR:
            logger.error("Failed to compute hash: %s", filepath)
            if self.error_log_callback:
                self.error_log_callback(
                    "HASH_ERROR", str(filepath), "Failed to compute MD5 hash"
                )
            md5_hash = "ERROR"
            hash_error = True

        # Extract batch metadata
        batch = self.extractor.extract_batch_metadata(str(filepath))

        # Camera metadata
        has_camera = bool(batch.make or batch.model)
        make = batch.make if batch.make else ""
        model = batch.model if batch.model else ""

        # GPS metadata
        has_gps = bool(batch.gps_latitude and batch.gps_longitude)
        gps_latitude = batch.gps_latitude if batch.gps_latitude else ""
        gps_longitude = batch.gps_longitude if batch.gps_longitude else ""

        # Video metadata (reuse from batch metadata, avoid redundant external tool calls)
        duration = batch.duration if batch.duration else ""
        resolution = batch.resolution if batch.resolution else ""
        codec = batch.codec if batch.codec else ""

        # Directory relative to root
        try:
            rel_dir = filepath.parent.relative_to(root_folder)
            directory = "/" + str(rel_dir) if str(rel_dir) != "." else "/"
        except ValueError:
            directory = str(filepath.parent)

        entry = FileInventoryEntry(
            directory=directory,
            filename=filepath.name,
            size_bytes=size_bytes,
            size_human=size_human,
            created=created,
            modified=modified,
            md5_hash=md5_hash,
            has_camera=has_camera,
            make=make,
            model=model,
            has_gps=has_gps,
            gps_latitude=gps_latitude,
            gps_longitude=gps_longitude,
            duration=duration,
            resolution=resolution,
            codec=codec,
            full_path=str(filepath),
        )
        return entry, hash_error

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _write_inventory_report(
        self,
        entries_by_dir: Dict[str, List[FileInventoryEntry]],
        result: InventoryResult,
        folder_path: Path,
        txt_path: Path,
        csv_path: Path,
    ) -> None:
        """Write inventory reports in TXT and CSV formats."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Write TXT report
        with open(txt_path, "w", encoding="utf-8") as f:
            # Header
            f.write(
                "╔═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗\n"
            )
            f.write(
                "║                                                    📁 FILE INVENTORY LOG                                                      ║\n"
            )
            f.write(
                "╠═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╣\n"
            )
            f.write(f"║  Generated:  {timestamp:<115}║\n")
            f.write(f"║  Source:     {str(folder_path):<115}║\n")
            f.write(f"║  Purpose:    {'Duplicate Detection & File Inventory':<115}║\n")
            f.write(
                "╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝\n\n"
            )

            # Process each directory (may be empty)
            if not entries_by_dir:
                f.write("No files found in folder.\n\n")

            for directory in sorted(entries_by_dir.keys()):
                entries = entries_by_dir[directory]

                # Directory header
                f.write(
                    "┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐\n"
                )
                f.write(f"│  📂 {directory:<123}│\n")
                f.write(
                    "├──────────────────────────────────────────┬────────────┬──────────────────┬──────────────────┬────────────┬────────┬────────────────────────┬──────────────────────┤\n"
                )
                f.write(
                    "│  FILENAME                                │ SIZE       │ CREATED          │ MODIFIED         │ MD5        │ CAM    │ MAKE/MODEL             │ GPS                  │\n"
                )
                f.write(
                    "├──────────────────────────────────────────┼────────────┼──────────────────┼──────────────────┼────────────┼────────┼────────────────────────┼──────────────────────┤\n"
                )

                for entry in entries:
                    filename = self._truncate(entry.filename, 40)
                    size = entry.size_human[:10]
                    created = entry.created[:16]
                    modified = entry.modified[:16]
                    md5_short = (
                        entry.md5_hash[:8] if entry.md5_hash != "ERROR" else "ERROR"
                    )
                    cam = "📸" if entry.has_camera else "✗"
                    make_model = (
                        self._truncate(f"{entry.make} {entry.model}".strip(), 22)
                        if entry.has_camera
                        else "✗"
                    )
                    gps = "✅" if entry.has_gps else "✗"
                    if entry.has_gps:
                        gps = self._truncate(
                            f"{entry.gps_latitude},{entry.gps_longitude}", 20
                        )

                    f.write(
                        f"│  {filename:<40}│ {size:<10} │ {created:<16} │ {modified:<16} │ {md5_short:<10} │ {cam:<6} │ {make_model:<22} │ {gps:<20} │\n"
                    )

                f.write(
                    "└──────────────────────────────────────────┴────────────┴──────────────────┴──────────────────┴────────────┴────────┴────────────────────────┴──────────────────────┘\n\n"
                )

            # Footer summary
            f.write(
                "╔═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗\n"
            )
            f.write(
                "║                                                       SUMMARY                                                                 ║\n"
            )
            f.write(
                "╠═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╣\n"
            )
            f.write(f"║  Total files logged:    {result.total_files:<104}║\n")
            f.write(
                f"║  Total size:            {format_file_size(result.total_size_bytes):<104}║\n"
            )
            f.write(f"║  Directories:           {result.directories_count:<104}║\n")
            f.write(f"║  Generated:             {timestamp:<104}║\n")
            f.write(
                "╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝\n\n"
            )

            # Legend
            f.write("Legend:\n")
            f.write("  📂 = Directory section\n")
            f.write("  📸 = Has camera metadata (Make/Model)\n")
            f.write("  ✅ = Has GPS coordinates\n")
            f.write("  ✗  = No data available\n")

        # Write CSV report
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(
                [
                    "Directory",
                    "Filename",
                    "Size (bytes)",
                    "Size (human)",
                    "Created",
                    "Modified",
                    "MD5 Hash",
                    "Has Camera",
                    "Make",
                    "Model",
                    "Has GPS",
                    "GPS Latitude",
                    "GPS Longitude",
                    "Duration",
                    "Resolution",
                    "Codec",
                    "Full Path",
                ]
            )

            for directory in sorted(entries_by_dir.keys()):
                for entry in entries_by_dir[directory]:
                    writer.writerow(
                        [
                            entry.directory,
                            entry.filename,
                            entry.size_bytes,
                            entry.size_human,
                            entry.created,
                            entry.modified,
                            entry.md5_hash,
                            "📸" if entry.has_camera else "✗",
                            entry.make,
                            entry.model,
                            "✅" if entry.has_gps else "✗",
                            entry.gps_latitude,
                            entry.gps_longitude,
                            entry.duration if entry.duration else "N/A",
                            entry.resolution if entry.resolution else "N/A",
                            entry.codec if entry.codec else "N/A",
                            entry.full_path,
                        ]
                    )

        logger.info("Wrote inventory reports: %s, %s", txt_path, csv_path)


__all__ = [
    "FileInventoryEntry",
    "InventoryResult",
    "InventoryGenerator",
]
