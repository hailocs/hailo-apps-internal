#!/bin/bash

# Set the project directory name
PROJECT_DIR="."

# Enable strict error handling
set -e

# Check if Meson and Ninja are installed
if ! command -v meson &> /dev/null; then
    echo "Error: Meson is not installed. Please install it and try again."
    exit 1
fi

if ! command -v ninja &> /dev/null; then
    echo "Error: Ninja is not installed. Please install it and try again."
    exit 1
fi

# Get the build mode from the command line (default to release)
if [ "$1" = "debug" ]; then
    BUILD_MODE="debug"
elif [ "$1" = "clean" ]; then
    BUILD_MODE="release"  # Default to release for cleanup
    CLEAN=true
else
    BUILD_MODE="release"
fi

# Set up the build directory
BUILD_DIR="$PROJECT_DIR/build.$BUILD_MODE"

# Handle cleanup
if [ "$CLEAN" = true ]; then
    echo "Cleaning build directory..."
    rm -rf "$BUILD_DIR"
    exit 0
fi

# Create the build directory
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Configure the project with Meson if not already configured
if [ ! -f "build.ninja" ]; then
    echo "Configuring project with Meson..."
    meson setup .. --buildtype="$BUILD_MODE"
else
    echo "Build directory already configured. Skipping setup."
fi

# Compile the project using Ninja with parallel jobs
echo "Building project with Ninja..."
ninja -j$(nproc)

# Install the project. The build step above runs as the calling user so
# build artifacts are user-owned, but `meson install` writes to system
# locations (e.g. /usr/lib/.../gstreamer-1.0 for the GStreamer plugins
# vendored under postprocess/cpp/). Detect whether we already have write
# access — if not, escalate just the install step with sudo.
echo "Installing project..."
GST_DIR=$(pkg-config --variable=pluginsdir gstreamer-1.0 2>/dev/null || true)
GST_DIR=${GST_DIR:-/usr/lib/gstreamer-1.0}
if [ -w "$GST_DIR" ] && [ -w "/usr/local/hailo/resources/so" ]; then
    ninja install
elif [ "$(id -u)" = "0" ]; then
    # Already root — install as-is.
    ninja install
elif sudo -n true 2>/dev/null; then
    echo "  (passwordless sudo available — using sudo for install step)"
    sudo meson install --no-rebuild
else
    echo "  (system directories are root-owned — re-prompting for sudo for the install step)"
    echo "  GStreamer plugins dir: $GST_DIR"
    sudo meson install --no-rebuild
fi

echo "Build completed successfully!"