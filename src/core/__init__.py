# Core business logic modules
# - metadata: MetadataExtractor, AppleDetector
# - router: Routing logic for file organization
# - hasher: File hashing and duplicate detection
# - organizer: File organization operations
# - duplicates: Duplicate detection and handling
# - inventory: File inventory management
# - worker: Background worker threads

from core.duplicates import (
    ComparisonResult,
    DuplicateDetector,
    DuplicateGroup,
    DuplicateResult,
    FolderComparator,
)
from core.hasher import HASH_ERROR, SmartHasher
from core.inventory import FileInventoryEntry, InventoryGenerator, InventoryResult
from core.metadata import (
    VIDEO_EXTENSIONS,
    AppleDetector,
    BatchMetadata,
    Destination,
    DetectionResult,
    MetadataExtractor,
    get_file_extension,
)
from core.organizer import FileOrganizer, OrganizationStats
from core.router import DestinationRouter
from core.worker import OrganizeWorker

__all__ = [
    # Metadata extraction
    "Destination",
    "DetectionResult",
    "BatchMetadata",
    "MetadataExtractor",
    "AppleDetector",
    # Utilities
    "get_file_extension",
    "VIDEO_EXTENSIONS",
    # Routing
    "DestinationRouter",
    # Organization
    "FileOrganizer",
    "OrganizationStats",
    # Duplicates
    "DuplicateDetector",
    "FolderComparator",
    "DuplicateGroup",
    "DuplicateResult",
    "ComparisonResult",
    # Inventory
    "InventoryGenerator",
    "FileInventoryEntry",
    "InventoryResult",
    # Hashing
    "SmartHasher",
    "HASH_ERROR",
    # Worker
    "OrganizeWorker",
]
