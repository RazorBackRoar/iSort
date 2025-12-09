# iSort

```text
    _  _____            _
   (_)/ ____|          | |
    _| (___   ___  _ __| |_
   | |\___ \ / _ \| '__| __|
   | |____) | (_) | |  | |_
   |_|_____/ \___/|_|   \__|

   Apple Device File Organizer
```

**iSort** is a powerful macOS utility designed to organize photos and videos from Apple devices. It intelligently sorts files based on metadata, detects device origins, and manages duplicates with confidence scoring.

## ✨ Features

- **📱 Apple Device Detection**: Uses a 10-layer confidence scoring system (HEIC, Exif, mdls, GPS, etc.) to identify iPhone, iPad, and Snapchat content.
- **📂 Smart Organization**: Automatically sorts files into `iPhone/Photos`, `iPhone/Videos`, `Screenshots`, `Snapchat`, etc.
- **🔍 Duplicate Detection**: Identifies and handles duplicates with smart hashing (full MD5 for small files, partial for large videos).
- **💾 Disk Space Safety**: Checks available disk space before operations.
- **🛡️ Checkpoint & Undo**: Resumes interrupted runs and provides full rollback capability via manifest files.
- **📊 Detailed Inventory**: Generates comprehensive CSV/TXT reports of file metadata.
- **⚡ Performance**: Optimized for speed with multiprocessing and smart hashing.

## 🚀 Installation

### Prerequisites

- macOS 10.13 or later
- Python 3.10+ (if running from source)
- External tools (optional but recommended for full metadata support):

  ```bash
  brew install exiftool mediainfo
  ```

  *(mdls is built-in on macOS)*

### Running from Source

1. Clone the repository:

   ```bash
   git clone https://github.com/RazorBackRoar/isort.git
   cd isort
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:

   ```bash
   python3 main.py
   ```

## 🛠️ Build Instructions

To build a standalone macOS application bundle (`.app`):

```bash
./build/scripts/build.sh
```

To create a DMG installer:

```bash
./build/scripts/build-dmg.sh
```

## 📜 License

MIT License. See [LICENSE](LICENSE) for details.

## 👤 Author

**RazorBackRoar**

---
*Built with Python and PySide6.*
