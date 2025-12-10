# core/metadata.py
"""
Metadata extraction and Apple device detection module.

Implements a 10-layer confidence scoring system for detecting Apple device origin:
- Layer 1: HEIC extension (100 points - instant win)
- Layer 2: Make = Apple (90 points)
- Layer 3: Model = iPhone/iPad/iPod (85 points)
- Layer 4: Software mentions iOS (70 points)
- Layer 5: iOS version pattern + Apple tags (60/50 points)
- Layer 6: macOS mdls Make/Model (75/70 points)
- Layer 7: MediaInfo video metadata (65/60/55 points)
- Layer 8: GPS + filename pattern correlation (40/30 points)

Threshold: 80+ points = confirmed Apple device
"""

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class Destination(Enum):
    """Target destinations for file routing."""

    IPHONE_PHOTOS = "iPhone/Photos"
    IPHONE_VIDEOS = "iPhone/Videos"
    IPHONE_SCREENSHOTS = "iPhone/Screenshots"
    SCREENSHOTS = "Screenshots"
    SNAPCHAT = "Snapchat"
    JPEG = "JPEG"
    MP4 = "MP4"
    NON_APPLE = "Non-Apple"
    NO_METADATA = "No-Metadata"


@dataclass
class DetectionResult:
    """Result of Apple device detection."""

    is_apple: bool
    confidence_score: int
    methods: List[str] = field(default_factory=list)
    destination: Destination = Destination.NO_METADATA
    detection_method: str = "none"
    video_duration: Optional[str] = None
    has_gps: bool = False

    @property
    def methods_str(self) -> str:
        return ",".join(self.methods)


@dataclass
class BatchMetadata:
    """Cached metadata from exiftool batch extraction."""

    make: str = ""
    model: str = ""
    software: str = ""
    creator_tool: str = ""
    gps_latitude: str = ""
    gps_longitude: str = ""
    raw_output: str = ""
    duration: str = ""
    resolution: str = ""
    codec: str = ""

    @property
    def has_gps(self) -> bool:
        return bool(self.gps_latitude or self.gps_longitude)

    def has_video_metadata(self) -> bool:
        """Check if video properties exist."""
        return bool(self.duration or self.resolution or self.codec)


# Video file extensions
VIDEO_EXTENSIONS = frozenset(("mov", "mp4", "m4v", "avi", "mkv", "webm"))


def get_file_extension(filepath: str) -> str:
    """
    Extract lowercase file extension from filepath.

    Shared utility function used by MetadataExtractor, AppleDetector,
    and DestinationRouter to ensure consistent extension handling.

    Args:
        filepath: Path to the file (can be full path or just filename)

    Returns:
        Lowercase extension without dot, or empty string if none
    """
    filename = os.path.basename(filepath)
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


class MetadataExtractor:
    """Handles all external tool interactions for metadata extraction."""

    def __init__(self):
        self._exiftool_available = self._check_tool("exiftool")
        self._mdls_available = self._check_tool("mdls")
        self._mediainfo_available = self._check_tool("mediainfo")

        # Log warnings for missing tools
        if not self._exiftool_available:
            logger.warning(
                "exiftool not available - metadata extraction will be limited"
            )
        if not self._mdls_available:
            logger.warning("mdls not available - macOS Spotlight metadata unavailable")
        if not self._mediainfo_available:
            logger.warning(
                "mediainfo not available - video metadata extraction limited"
            )

    def _check_tool(self, name: str) -> bool:
        """
        Check if an external tool is available.

        Uses shutil.which() and common Homebrew prefixes since macOS app
        bundles often have a restricted PATH.
        """
        if shutil.which(name):
            return True

        # Fallbacks for users with Homebrew-installed binaries not on PATH
        common_paths = (
            f"/opt/homebrew/bin/{name}",
            f"/usr/local/bin/{name}",
        )
        return any(os.access(path, os.X_OK) for path in common_paths)

    def _run_cmd(self, cmd: List[str], timeout: int = 10) -> str:
        """Run a command and return lowercase output."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
            )
            return result.stdout.strip().lower()
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
            logger.debug("Command failed: %s - %s", cmd[0], e)
            return ""

    def _run_cmd_raw(self, cmd: List[str], timeout: int = 10) -> str:
        """Run a command and return raw output (not lowercased)."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
            logger.debug("Command failed: %s - %s", cmd[0], e)
            return ""

    def extract_batch_metadata(self, filepath: str) -> BatchMetadata:
        """Single exiftool call to get all needed metadata."""
        if not self._exiftool_available:
            return BatchMetadata()

        # Get raw output for pattern matching
        cmd_raw = [
            "exiftool",
            "-s",
            "-Make",
            "-Model",
            "-Software",
            "-CreatorTool",
            "-GPSLatitude",
            "-GPSLongitude",
            "-GPSPosition",
            filepath,
        ]
        raw_output = self._run_cmd(cmd_raw)

        # Use JSON for reliable parsing
        cmd_json = [
            "exiftool",
            "-json",
            "-Make",
            "-Model",
            "-Software",
            "-CreatorTool",
            "-GPSLatitude",
            "-GPSLongitude",
            filepath,
        ]

        try:
            result = subprocess.run(
                cmd_json, capture_output=True, text=True, timeout=10, encoding="utf-8"
            )
            json_output = result.stdout
            data = json.loads(json_output)[0] if json_output else {}

            batch = BatchMetadata(
                make=str(data.get("Make", "")).lower(),
                model=str(data.get("Model", "")).lower(),
                software=str(data.get("Software", "")).lower(),
                creator_tool=str(data.get("CreatorTool", "")).lower(),
                gps_latitude=str(data.get("GPSLatitude", "")),
                gps_longitude=str(data.get("GPSLongitude", "")),
                raw_output=raw_output,
            )

            # Extract video metadata for video files
            ext = get_file_extension(filepath)
            if ext in VIDEO_EXTENSIONS:
                duration, resolution, codec = self.get_video_metadata(filepath)
                batch.duration = duration
                batch.resolution = resolution
                batch.codec = codec

            return batch

        except (json.JSONDecodeError, IndexError, subprocess.TimeoutExpired) as e:
            logger.debug("Batch metadata extraction failed: %s", e)
            return BatchMetadata(raw_output=raw_output)

    def get_video_metadata(self, filepath: str) -> Tuple[str, str, str]:
        """
        Extract video metadata: duration, resolution, codec.

        Returns:
            Tuple of (duration, resolution, codec)
        """
        duration = ""
        resolution = ""
        codec = ""

        if self._exiftool_available:
            # Duration
            duration = self._run_cmd_raw(
                ["exiftool", "-s", "-s", "-s", "-Duration", filepath]
            )

            # Resolution (width x height)
            width = self._run_cmd_raw(
                ["exiftool", "-s", "-s", "-s", "-ImageWidth", filepath]
            )
            height = self._run_cmd_raw(
                ["exiftool", "-s", "-s", "-s", "-ImageHeight", filepath]
            )
            if width and height:
                resolution = f"{width}x{height}"

            # Codec - try CompressorID first, then VideoCodec
            codec = self._run_cmd_raw(
                ["exiftool", "-s", "-s", "-s", "-CompressorID", filepath]
            )
            if not codec:
                codec = self._run_cmd_raw(
                    ["exiftool", "-s", "-s", "-s", "-VideoCodec", filepath]
                )

        # Fallback to mediainfo for codec if not found
        if not codec and self._mediainfo_available:
            codec = self._run_cmd(["mediainfo", "--Inform=Video;%Format%", filepath])

        return duration, resolution, codec

    def check_gps_comprehensive(self, filepath: str) -> bool:
        """
        Check for GPS data using both exiftool and mdls fallback.

        Returns:
            True if GPS coordinates found via either method
        """
        # First try exiftool
        if self._exiftool_available:
            gps_data = self._run_cmd_raw(
                [
                    "exiftool",
                    "-s",
                    "-s",
                    "-s",
                    "-GPSLatitude",
                    "-GPSLongitude",
                    "-GPSPosition",
                    filepath,
                ]
            )
            if gps_data:
                return True

        # Fallback to mdls
        if self._mdls_available:
            lat = self._run_cmd_raw(
                ["mdls", "-name", "kMDItemLatitude", "-raw", filepath]
            )
            lon = self._run_cmd_raw(
                ["mdls", "-name", "kMDItemLongitude", "-raw", filepath]
            )

            # Filter out "(null)" values
            if lat and lat != "(null)" and lon and lon != "(null)":
                return True

        return False

    def get_mdls_metadata(self, filepath: str) -> Tuple[str, str]:
        """Get macOS Spotlight metadata."""
        if not self._mdls_available:
            return "", ""

        make = self._run_cmd(
            ["mdls", "-name", "kMDItemAcquisitionMake", "-raw", filepath]
        )
        model = self._run_cmd(
            ["mdls", "-name", "kMDItemAcquisitionModel", "-raw", filepath]
        )

        # Filter out "(null)" values
        if make == "(null)":
            make = ""
        if model == "(null)":
            model = ""

        return make, model

    def get_mediainfo_metadata(self, filepath: str) -> Tuple[str, str, str]:
        """Get video metadata via mediainfo."""
        if not self._mediainfo_available:
            return "", "", ""

        encoded_app = self._run_cmd(
            ["mediainfo", "--Inform=General;%Encoded_Application%", filepath]
        )
        model = self._run_cmd(["mediainfo", "--Inform=General;%Model%", filepath])
        encoder = self._run_cmd(
            ["mediainfo", "--Inform=Video;%Encoded_Library_Name%", filepath]
        )

        return encoded_app, model, encoder

    def check_snapchat(self, filepath: str) -> Tuple[bool, str]:
        """
        Check if file originated from Snapchat.

        Returns:
            Tuple of (is_snapchat, detection_method)
        """
        # Check via exiftool with all metadata
        if self._exiftool_available:
            output = self._run_cmd(["exiftool", "-a", "-G1", filepath])
            if "snapchat" in output:
                return True, "exiftool-snapchat"

        # Check via mediainfo
        if self._mediainfo_available:
            output = self._run_cmd(["mediainfo", filepath])
            if "snapchat" in output:
                return True, "mediainfo-snapchat"

        return False, "none"


class AppleDetector:
    """
    10-layer confidence scoring for Apple device detection.

    Threshold: 80 points = confirmed Apple device

    Point values:
    - Layer 1: HEIC extension = 100 points (instant win)
    - Layer 2: Make = Apple = 90 points
    - Layer 3: Model = iPhone/iPad/iPod = 85 points
    - Layer 4: Software mentions iOS = 70 points
    - Layer 5: iOS version pattern = 60 points, Apple tags = 50 points
    - Layer 6: mdls Make = 75 points, mdls Model = 70 points
    - Layer 7: mediainfo make/model = 65 points, device = 60 points, encoder = 55 points
    - Layer 8: GPS data = 40 points, IMG_XXXX pattern = 30 points
    """

    def __init__(self, extractor: MetadataExtractor):
        self.extractor = extractor

    def detect(self, filepath: str) -> DetectionResult:
        """
        Detect if file originated from an Apple device.

        Args:
            filepath: Path to the file to analyze

        Returns:
            DetectionResult with confidence score and detection methods
        """
        try:
            return self._detect_internal(filepath)
        except Exception as e:
            logger.error("Apple detection failed for %s: %s", filepath, e)
            return DetectionResult(
                is_apple=False, confidence_score=0, methods=[], detection_method="error"
            )

    def _detect_internal(self, filepath: str) -> DetectionResult:
        """Internal detection logic with full error propagation."""
        filename = os.path.basename(filepath)
        ext = get_file_extension(filename)

        score = 0
        methods: List[str] = []

        def add_points(points: int, method: str):
            nonlocal score
            score += points
            methods.append(method)

        # ══════════════════════════════════════════════════════════
        # LAYER 1: HEIC = Apple-only format (100 points - instant win)
        # ══════════════════════════════════════════════════════════
        if ext in ("heic", "heif"):
            add_points(100, "heic-extension")

        # ══════════════════════════════════════════════════════════
        # LAYERS 2-5: ExifTool metadata
        # ══════════════════════════════════════════════════════════
        batch = self.extractor.extract_batch_metadata(filepath)

        if batch.raw_output:
            # Layer 2: Make = Apple (90 points)
            if "apple" in batch.make:
                add_points(90, "exiftool-make")

            # Layer 3: Model = iPhone/iPad/iPod (85 points)
            if "iphone" in batch.model:
                add_points(85, "exiftool-iphone-model")
            elif "ipad" in batch.model:
                add_points(85, "exiftool-ipad-model")
            elif "ipod" in batch.model:
                add_points(85, "exiftool-ipod-model")

            # Layer 4: Software mentions iOS (70 points)
            if "ios" in batch.software or "ios" in batch.creator_tool:
                add_points(70, "exiftool-software-ios")

            # Layer 5a: iOS version pattern detection (60 points)
            # Check both software and creator_tool for iOS version
            ios_pattern = r"(\d+\.\d+)"
            version_found = False
            for field_value in (batch.software, batch.creator_tool):
                if version_found:
                    break
                match = re.search(ios_pattern, field_value)
                if match:
                    try:
                        version = float(match.group(1))
                        if 7.0 <= version <= 20.0:  # Reasonable iOS versions
                            add_points(60, "exiftool-ios-version")
                            version_found = True
                    except ValueError:
                        pass

            # Layer 5b: Apple-specific tags (50 points)
            if "applemodelid" in batch.raw_output or "runtime" in batch.raw_output:
                add_points(50, "exiftool-apple-tags")

        # ══════════════════════════════════════════════════════════
        # LAYER 6: macOS mdls (Spotlight metadata)
        # ══════════════════════════════════════════════════════════
        mdls_make, mdls_model = self.extractor.get_mdls_metadata(filepath)

        if "apple" in mdls_make:
            add_points(75, "mdls-make")

        if any(d in mdls_model for d in ("iphone", "ipad", "ipod")):
            add_points(70, "mdls-model")

        # ══════════════════════════════════════════════════════════
        # LAYER 7: MediaInfo metadata
        # Note: ZSH script calls mediainfo unconditionally on all files,
        # not just videos. We preserve this behavior for parity.
        # ══════════════════════════════════════════════════════════
        mi_app, mi_model, mi_encoder = self.extractor.get_mediainfo_metadata(filepath)

        if "apple" in mi_app or "apple" in mi_model:
            add_points(65, "mediainfo-make-model")

        if any(d in mi_model for d in ("iphone", "ipad")):
            add_points(60, "mediainfo-device")

        if "apple" in mi_encoder:
            add_points(55, "mediainfo-encoder")

        # ══════════════════════════════════════════════════════════
        # LAYER 8: GPS + filename pattern correlation
        # ══════════════════════════════════════════════════════════
        has_gps = self.extractor.check_gps_comprehensive(filepath)

        if has_gps:
            add_points(40, "gps-data")

            # IMG_XXXX pattern common for Apple
            if re.match(r"^IMG_\d{4}\.", filename, re.IGNORECASE):
                add_points(30, "gps-img-pattern")

        # ══════════════════════════════════════════════════════════
        # FINAL DETERMINATION
        # ══════════════════════════════════════════════════════════
        is_apple = score >= 80

        return DetectionResult(
            is_apple=is_apple,
            confidence_score=score,
            methods=methods,
            detection_method=",".join(methods) if methods else "none",
            video_duration=batch.duration if batch.duration else None,
            has_gps=has_gps,
        )

    def _is_video_file(self, ext: str) -> bool:
        """Check if extension is a video format."""
        return ext in VIDEO_EXTENSIONS


__all__ = [
    "Destination",
    "DetectionResult",
    "BatchMetadata",
    "MetadataExtractor",
    "AppleDetector",
    "get_file_extension",
    "VIDEO_EXTENSIONS",
    "check_dependencies",
]


def check_dependencies() -> List[str]:
    """
    Check availability of external dependencies.

    Returns:
        List of missing tool names.
    """
    missing = []
    if shutil.which("exiftool") is None:
        missing.append("exiftool")
    if shutil.which("mdls") is None:
        missing.append("mdls")
    if shutil.which("mediainfo") is None:
        missing.append("mediainfo")
    return missing
