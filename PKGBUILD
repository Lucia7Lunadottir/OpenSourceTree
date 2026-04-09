# Maintainer: Lucia <bordiyan20035@gmail.com>
pkgname=opensourcetree-git
pkgver=1.2.10
pkgrel=1
pkgdesc="SourceTree-inspired Git GUI built with PyQt6"
arch=('x86_64')
url="https://github.com/Lucia7Lunadottir/OpenSourceTree"
license=('GPL-3.0-only')

# ── Runtime dependencies ───────────────────────────────────────────────────────
# Qt6 native libs and system libs are NOT bundled in the PyInstaller binary;
# they are linked at runtime from these packages.
depends=(
    'qt6-base'          # libQt6{Core,Gui,Widgets,Network,DBus,PrintSupport}.so
    'qt6-svg'           # libQt6{Svg,SvgWidgets}.so
    'python-numpy'      # numpy (used in graph layout)
    'git'
    'libxcb'            # Qt XCB platform plugin
    'libx11'
)
optdepends=(
    'git-lfs: Git Large File Storage support'
    'konsole: for interactive SSH authentication in terminal'
    'xterm: alternative terminal for SSH auth'
)

# ── Build dependencies ─────────────────────────────────────────────────────────
makedepends=(
    'git'
    'python-pyqt6'         # needed at build time for PyInstaller analysis
    'python-numpy'
    'python-pygments'
)
# Note: PyInstaller must be installed separately (e.g. via pipx install pyinstaller)

provides=('opensourcetree')
conflicts=('opensourcetree')
source=("opensourcetree::git+$url.git")
sha256sums=('SKIP')

pkgver() {
    cd "$srcdir/opensourcetree"
    git describe --tags --long 2>/dev/null \
        | sed 's/^v//;s/-[0-9]*-g[0-9a-f]*//' \
        || printf "r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

build() {
    cd "$srcdir/opensourcetree"
    pyinstaller opensourcetree.spec \
        --distpath "$srcdir/dist" \
        --workpath "$srcdir/build" \
        --noconfirm
}

package() {
    local _bundle="$srcdir/dist/opensourcetree"
    local _dest="$pkgdir/opt/opensourcetree"

    # Install the PyInstaller bundle
    install -dm755 "$_dest"
    cp -r "$_bundle/." "$_dest/"
    chmod -R u=rwX,go=rX "$_dest"

    # The main executable must be executable
    chmod 755 "$_dest/opensourcetree"

    # Application icon
    install -Dm644 "$srcdir/opensourcetree/OpenSourceTreeIcon.png" \
        "$pkgdir/usr/share/pixmaps/opensourcetree.png"

    # .desktop file
    install -Dm644 "$srcdir/opensourcetree/opensourcetree.desktop" \
        "$pkgdir/usr/share/applications/opensourcetree.desktop"

    # Launcher wrapper (handles LD_LIBRARY_PATH for xcb platform plugin)
    install -Dm755 /dev/stdin "$pkgdir/usr/bin/opensourcetree" << 'LAUNCHER'
#!/bin/bash
exec /opt/opensourcetree/opensourcetree "$@"
LAUNCHER
}
