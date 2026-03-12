#!/usr/bin/env sh
# tuitter installer - macOS / Linux / WSL
# Downloads a prebuilt binary - no Python, git, or pip required.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tuitter/tuitter/dev/install.sh | sh

set -e

REPO="tuitter/tuitter"
INSTALL_DIR="$HOME/.local/bin"
BINARY_NAME="tuitter"

# Helpers
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n'  "$*"; }
die()    { red "Error: $*"; exit 1; }

# Detect OS / arch -> pick the right binary asset name
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux*)
    case "$ARCH" in
      x86_64)        ASSET="tuitter-linux-x86_64" ;;
      aarch64|arm64) ASSET="tuitter-linux-arm64" ;;
      *)             ASSET="" ;;
    esac ;;
  Darwin*)
    # arm64 binary runs on both Apple Silicon and Intel Macs (via Rosetta 2)
    ASSET="tuitter-macos-arm64" ;;
  *) ASSET="" ;;
esac

bold "tuitter installer"
echo ""

if [ -z "$ASSET" ]; then
  die "No prebuilt binary available for $OS/$ARCH. Download manually from:
  https://github.com/${REPO}/releases"
fi

if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  die "curl or wget is required. Install one and try again."
fi

# Fetch download URL - tries stable release first, then falls back to pre-releases
fetch_url() {
  if command -v curl >/dev/null 2>&1; then
    _get() { curl -fsSL "$1" 2>/dev/null; }
  else
    _get() { wget -qO- "$1" 2>/dev/null; }
  fi

  # Try stable release first
  DOWNLOAD_URL=$(_get "https://api.github.com/repos/${REPO}/releases/latest" \
    | grep '"browser_download_url"' | grep "$ASSET" | head -1 \
    | sed 's/.*"browser_download_url": "\([^"]*\)".*/\1/')

  # Fall back to most recent release including pre-releases
  if [ -z "$DOWNLOAD_URL" ]; then
    DOWNLOAD_URL=$(_get "https://api.github.com/repos/${REPO}/releases" \
      | grep '"browser_download_url"' | grep "$ASSET" | head -1 \
      | sed 's/.*"browser_download_url": "\([^"]*\)".*/\1/')
  fi

  echo "$DOWNLOAD_URL"
}

green "Detected: $OS / $ARCH -> fetching $ASSET..."
DOWNLOAD_URL=$(fetch_url)

if [ -z "$DOWNLOAD_URL" ]; then
  die "No release binary found for $ASSET. Download manually from:
  https://github.com/${REPO}/releases"
fi

mkdir -p "$INSTALL_DIR"
DEST="$INSTALL_DIR/$BINARY_NAME"

echo ""
yellow "NOTE: Security software may block unsigned executables."
yellow "If this script crashes, download the binary directly in your browser:"
printf '  %s\n' "$DOWNLOAD_URL"
echo ""

green "Downloading..."
if command -v curl >/dev/null 2>&1; then
  if ! curl -fsSL --progress-bar -o "$DEST" "$DOWNLOAD_URL"; then
    red "Download failed. Download manually from:"
    printf '  %s\n' "$DOWNLOAD_URL"
    exit 1
  fi
else
  if ! wget -q --show-progress -O "$DEST" "$DOWNLOAD_URL"; then
    red "Download failed. Download manually from:"
    printf '  %s\n' "$DOWNLOAD_URL"
    exit 1
  fi
fi
chmod +x "$DEST"

if [ "${PATH#*"$INSTALL_DIR"}" = "$PATH" ]; then
  yellow ""
  yellow "  ~/.local/bin is not on your PATH."
  yellow "  Add this to your shell profile (~/.bashrc, ~/.zshrc) and restart:"
  yellow ""
  yellow "    export PATH=\"\$HOME/.local/bin:\$PATH\""
  yellow ""
fi

echo ""
green "tuitter installed to $DEST"
bold "Done! Open a new terminal and run: tuitter"
