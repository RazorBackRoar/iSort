from pathlib import Path
from typing import Dict, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon


class ResourceManager:
    _instance = None
    _pixmap_cache: Dict[str, QPixmap] = {}
    _icon_cache: Dict[str, QIcon] = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get_image_path(cls, filename: str) -> Path:
        # Assumes images are in the root directory as per observations
        root_dir = Path(__file__).parent.parent
        return root_dir / filename

    @classmethod
    def get_pixmap(cls, filename: str) -> QPixmap:
        if filename in cls._pixmap_cache:
            return cls._pixmap_cache[filename]

        image_path = cls.get_image_path(filename)
        pixmap = QPixmap(str(image_path))

        if pixmap.isNull():
            print(f"Warning: Failed to load image resource at {image_path}")
            # Create a placeholder if image load fails
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.red)

        cls._pixmap_cache[filename] = pixmap
        return pixmap

    @classmethod
    def get_icon(cls, filename: str) -> QIcon:
        if filename in cls._icon_cache:
            return cls._icon_cache[filename]

        pixmap = cls.get_pixmap(filename)
        icon = QIcon(pixmap)

        cls._icon_cache[filename] = icon
        return icon
