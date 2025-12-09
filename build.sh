#!/bin/bash
set -e

# Navigate to project root
cd "$(dirname "$0")/../.."

# Configuration
APP_NAME="iSort"
MAIN_SCRIPT="main.py"
ICON_PATH="assets/icons/iSort.icns"
BUILD_DIR="build/dist"
WORK_DIR="build/work"

echo "🚀 Starting build process for $APP_NAME..."

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed."
    exit 1
fi

# Install dependencies
echo "📦 Installing/Updating dependencies..."
pip3 install -r requirements.txt

# Clean previous builds
echo "🧹 Cleaning previous build artifacts..."
rm -rf "$BUILD_DIR" "$WORK_DIR" *.spec

# Run PyInstaller
echo "🔨 Building application bundle..."
# Note: --onedir is standard for macOS .app bundles.
pyinstaller --noconfirm --clean \
    --name "$APP_NAME" \
    --icon "$ICON_PATH" \
    --windowed \
    --onedir \
    --contents-directory "." \
    --exclude-module tkinter \
    --distpath "$BUILD_DIR" \
    --workpath "$WORK_DIR" \
    "$MAIN_SCRIPT"

# Verify build
if [ -d "$BUILD_DIR/$APP_NAME.app" ]; then
    echo "✅ Build successful!"
    echo "📂 App bundle location: $BUILD_DIR/$APP_NAME.app"
else
    echo "❌ Build failed. App bundle not found."
    exit 1
fi
