#!/bin/bash
set -e

# Navigate to project root
cd "$(dirname "$0")"

# Configuration
APP_NAME="iSort"
MAIN_SCRIPT="src/main.py"
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

# Clean up raw artifact folder (we only want the .app)
if [ -d "$BUILD_DIR/$APP_NAME" ]; then
    echo "🧹 Removing raw artifact folder..."
    rm -rf "$BUILD_DIR/$APP_NAME"
fi

# Verify build
if [ -d "$BUILD_DIR/$APP_NAME.app" ]; then
    echo "✅ Build successful!"
    echo "📂 App bundle location: $BUILD_DIR/$APP_NAME.app"
else
    echo "❌ Build failed. App bundle not found."
    exit 1
fi

# Build DMG
echo "💿 Building DMG..."
./build/scripts/build-dmg.sh

# Move and rename DMG
DMG_SOURCE="${APP_NAME}-1.0.0.dmg"
DMG_DEST="$BUILD_DIR/${APP_NAME}.dmg"

if [ -f "$DMG_SOURCE" ]; then
    echo "📦 Moving DMG to dist..."
    mv "$DMG_SOURCE" "$DMG_DEST"
    echo "✅ DMG available at: $DMG_DEST"

    # Clean up the App bundle as user requested only DMG to remain
    echo "🧹 Removing App bundle from dist..."
    rm -rf "$BUILD_DIR/${APP_NAME}.app"
else
    echo "❌ DMG creation failed or file not found at $DMG_SOURCE"
    exit 1
fi

# Cleanup spec file
rm -f *.spec
