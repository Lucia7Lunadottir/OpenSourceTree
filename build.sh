#!/usr/bin/env bash
# build.sh — быстрая локальная сборка OpenSourceTree через PyInstaller
#
# Использование:
#   ./build.sh            — собрать бандл в dist/opensourcetree/
#   ./build.sh --run      — собрать и запустить
#   ./build.sh --size     — показать размер собранного бандла
#   ./build.sh --pkg      — собрать .pkg.tar.zst через makepkg (Arch Linux)
#   ./build.sh --clean    — удалить build/ и dist/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DIST="$SCRIPT_DIR/dist/opensourcetree"

case "${1:-}" in
    --clean)
        echo "Cleaning build artifacts..."
        rm -rf build/ dist/
        echo "Done."
        exit 0
        ;;
    --size)
        if [[ -d "$DIST" ]]; then
            du -sh "$DIST"
            echo ""
            echo "Top 10 largest files:"
            find "$DIST" -type f -printf '%s %p\n' | sort -rn | head -10 \
                | awk '{printf "  %6.1f MB  %s\n", $1/1048576, $2}'
        else
            echo "Bundle not found. Run ./build.sh first."
        fi
        exit 0
        ;;
    --pkg)
        echo "Building Arch package with makepkg..."
        makepkg -sf --noconfirm
        echo ""
        echo "Package ready:"
        ls -lh ./*.pkg.tar.zst 2>/dev/null || true
        exit 0
        ;;
esac

# ── Build ──────────────────────────────────────────────────────────────────────
echo "==> Building OpenSourceTree bundle..."
echo ""

pyinstaller opensourcetree.spec \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    --noconfirm

echo ""
echo "==> Bundle size:"
du -sh "$DIST"

if [[ "${1:-}" == "--run" ]]; then
    echo ""
    echo "==> Launching..."
    exec "$DIST/opensourcetree"
fi

echo ""
echo "Done. To run:    $DIST/opensourcetree"
echo "      To check:  ./build.sh --size"
echo "      To clean:  ./build.sh --clean"
