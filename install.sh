#!/usr/bin/env sh
# tuitter installer â€” macOS / Linux / WSL
# Downloads a prebuilt binary â€” no Python, git, or pip required.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tuitter/tuitter/main/install.sh | sh

set -e

REPO="tuitter/tuitter"
INSTALL_DIR="$HOME/.local/bin"
BINARY_NAME="tuitter"

###############################################################################
# Helpers
###############################################################################
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n'  "$*"; }
die()    { red "Error: $*"; exit 1; }

###############################################################################
# Detect OS / arch â†’ pick the right binary asset name
###############################################################################
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
    case "$ARCH" in
      x86_64) ASSET="tuitter-macos-x86_64" ;;
      arm64)  ASSET="tuitter-macos-arm64" ;;
      *)      ASSET="" ;;
    esac ;;
  *) ASSET="" ;;
esac

###############################################################################
# Main
###############################################################################
bold "tuitter installer"
echo ""

# â”€â”€ 1. Try prebuilt binary (preferred â€” no Python required) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [ -n "$ASSET" ] && (command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1); then
  green "Detected: $OS / $ARCH  â†’  fetching $ASSET from latest release..."

  API="https://api.github.com/repos/${REPO}/releases/latest"

  if command -v curl >/dev/null 2>&1; then
    DOWNLOAD_URL=$(curl -fsSL "$API" \
      | grep '"browser_download_url"' \
      | grep "$ASSET" \
      | head -1 \
      | sed 's/.*"browser_download_url": "\([^"]*\)".*/\1/')
  else
    DOWNLOAD_URL=$(wget -qO- "$API" \
      | grep '"browser_download_url"' \
      | grep "$ASSET" \
      | head -1 \
      | sed 's/.*"browser_download_url": "\([^"]*\)".*/\1/')
  fi

  if [ -n "$DOWNLOAD_URL" ]; then
    mkdir -p "$INSTALL_DIR"
    DEST="$INSTALL_DIR/$BINARY_NAME"
    green "Downloading..."
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL --progress-bar -o "$DEST" "$DOWNLOAD_URL"
    else
      wget -q --show-progress -O "$DEST" "$DOWNLOAD_URL"
    fi
    chmod +x "$DEST"

    if [ "${PATH#*"$INSTALL_DIR"}" = "$PATH" ]; then
      yellow ""
      yellow "  \$HOME/.local/bin is not on your PATH."
      yellow "  Add this line to your shell profile (~/.bashrc, ~/.zshrc) and restart:"
      yellow ""
      yellow "    export PATH=\"\$HOME/.local/bin:\$PATH\""
      yellow ""
    fi

    echo ""
    green "âœ“ tuitter installed to $DEST"
    bold "Run: tuitter"
    exit 0
  else
    yellow "No prebuilt binary found for $ASSET â€” falling back to pip install."
  fi
else
  yellow "No prebuilt binary available for this platform â€” falling back to pip install."
fi

# â”€â”€ 2. Fallback: pip / pipx install (requires Python 3.10+) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
yellow ""
yellow "Falling back to pip-based install (requires Python 3.10+)."
echo ""

PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    _minor=$("$cmd" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)
    _major=$("$cmd" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)
    if [ "$_major" -eq 3 ] && [ "$_minor" -ge 10 ]; then
      PYTHON="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  die "Python 3.10+ not found and no prebuilt binary is available for your platform ($OS/$ARCH).

Install Python from https://www.python.org/downloads/
or use your system package manager:
  macOS:  brew install python@3.12
  Ubuntu: sudo apt install python3.12
  Arch:   sudo pacman -S python

Or download a binary directly from:
  https://github.com/${REPO}/releases/latest"
fi

green "âœ“ Found Python: $($PYTHON --version)"

if command -v pipx >/dev/null 2>&1; then
  pipx install "git+https://github.com/${REPO}.git" --force
elif "$PYTHON" -m pipx --version >/dev/null 2>&1; then
  "$PYTHON" -m pipx install "git+https://github.com/${REPO}.git" --force
else
  yellow "pipx not found â€” installing into ~/.local/tuitter venv..."
  VENV="$HOME/.local/tuitter/.venv"
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install "git+https://github.com/${REPO}.git"
  mkdir -p "$INSTALL_DIR"
  printf '#!/bin/sh\nexec "%s/bin/tuitter" "$@"\n' "$VENV" > "$INSTALL_DIR/tuitter"
  chmod +x "$INSTALL_DIR/tuitter"
  if [ "${PATH#*"$INSTALL_DIR"}" = "$PATH" ]; then
    yellow "Add to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
fi

echo ""
green "âœ“ tuitter installed!"
bold "Run: tuitter"

