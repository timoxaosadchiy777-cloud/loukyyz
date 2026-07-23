#!/usr/bin/env bash
# Builds codebase-memory-mcp (https://github.com/DeusData/codebase-memory-mcp)
# from source and installs the binary to ~/.local/bin, matching the path
# .mcp.json expects. Building from source avoids running an unreviewed
# prebuilt binary from the project's own curl|bash installer.
set -euo pipefail

INSTALL_DIR="${CBM_INSTALL_DIR:-$HOME/.local/bin}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

git clone --depth 1 https://github.com/DeusData/codebase-memory-mcp.git "$WORKDIR/src"
(cd "$WORKDIR/src" && scripts/build.sh)

mkdir -p "$INSTALL_DIR"
cp "$WORKDIR/src/build/c/codebase-memory-mcp" "$INSTALL_DIR/codebase-memory-mcp"
chmod +x "$INSTALL_DIR/codebase-memory-mcp"

echo "Installed to $INSTALL_DIR/codebase-memory-mcp"
echo "Make sure $INSTALL_DIR is on your PATH."
