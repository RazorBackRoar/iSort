# core/router.py
"""
Priority-based file routing module.

Implements a 4-priority routing system:
1. Snapchat detection (overrides everything)
2. PNG files → Screenshots folder
3. Apple device detection → iPhone/* folders
4. Non-Apple fallback by extension

Integrates with MetadataExtractor and AppleDetector for
comprehensive file origin detection.
"""

import os
from typing import Tuple

from isort_app.core.metadata import (
    AppleDetector,
    Destination,
    MetadataExtractor,
    get_file_extension,
)


class DestinationRouter:
    """
    Priority-based file routing logic.

    Routes files to appropriate destinations based on:
    1. Snapchat origin detection
    2. PNG extension (screenshots)
    3. Apple device metadata detection
    4. Non-Apple fallback by extension
    """

    def __init__(self):
        self.extractor = MetadataExtractor()
        self.detector = AppleDetector(self.extractor)

    def determine_destination(self, filepath: str) -> Tuple[Destination, str]:
        """
        Determine the destination folder for a file.

        Args:
            filepath: Path to the file to route

        Returns:
            Tuple of (Destination enum, detection_method string)
        """
        filename = os.path.basename(filepath)
        ext = get_file_extension(filepath)

        # ══════════════════════════════════════════════════════════
        # PRIORITY 1: Snapchat detection (overrides everything)
        # ══════════════════════════════════════════════════════════
        is_snap, snap_method = self.extractor.check_snapchat(filepath)
        if is_snap:
            return Destination.SNAPCHAT, snap_method

        # ══════════════════════════════════════════════════════════
        # PRIORITY 2: All PNGs go to Screenshots
        # ══════════════════════════════════════════════════════════
        if ext == "png":
            return Destination.SCREENSHOTS, "png-extension"

        # ══════════════════════════════════════════════════════════
        # PRIORITY 3: Apple device detection
        # ══════════════════════════════════════════════════════════
        detection = self.detector.detect(filepath)

        if detection.is_apple:
            # Determine specific Apple subfolder based on file type
            if ext in ("heic", "heif"):
                # Reuse GPS result from AppleDetector to avoid redundant subprocess calls
                if detection.has_gps:
                    return Destination.IPHONE_PHOTOS, detection.detection_method
                return Destination.IPHONE_SCREENSHOTS, detection.detection_method

            if ext in ("mov", "mp4", "m4v"):
                return Destination.IPHONE_VIDEOS, detection.detection_method

            if ext in ("jpg", "jpeg"):
                return Destination.IPHONE_PHOTOS, detection.detection_method

            # Default Apple destination
            return Destination.IPHONE_PHOTOS, detection.detection_method

        # ══════════════════════════════════════════════════════════
        # PRIORITY 4: Non-Apple fallback by extension
        # ══════════════════════════════════════════════════════════
        if ext in ("jpg", "jpeg"):
            return Destination.JPEG, "non-apple-jpeg"

        if ext in ("mp4", "mov", "m4v"):
            return Destination.MP4, "non-apple-video"

        return Destination.NON_APPLE, "no-apple-metadata"


__all__ = [
    "DestinationRouter",
]
