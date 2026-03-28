# Maintainer: Lucia <bordiyan20035@gmail.com>
pkgname=opensourcetree-git
pkgver=v1.2.4
pkgrel=1
pkgdesc="SourceTree-inspired Git GUI built with PyQt6"
arch=('any')
url="https://github.com/7Lucia7Lokidottir7/OpenSourceTree"
license=('GPL-3.0-only')
depends=(
    'python'
    'python-pyqt6'
    'python-numpy'
    'python-pygments'
    'git'
)
optdepends=(
    'git-lfs: Git Large File Storage support'
)
makedepends=('git')
provides=('opensourcetree')
conflicts=('opensourcetree')
source=("opensourcetree::git+$url.git")
sha256sums=('SKIP')

pkgver() {
    cd "$srcdir/opensourcetree"
    printf "r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
    cd "$srcdir/opensourcetree"

    local _dest="$pkgdir/opt/opensourcetree"
    install -dm755 "$_dest"

    # Основные файлы приложения
    install -m644 main.py   "$_dest/"
    install -m644 style.qss "$_dest/"

    # Python-пакет, ресурсы и локали
    cp -r app     "$_dest/"
    cp -r assets  "$_dest/"
    cp -r locales "$_dest/"

    # Иконка
    install -m644 OpenSourceTreeIcon.png "$_dest/"
    install -Dm644 OpenSourceTreeIcon.png \
        "$pkgdir/usr/share/pixmaps/opensourcetree.png"

    # .desktop-файл
    install -Dm644 opensourcetree.desktop \
        "$pkgdir/usr/share/applications/opensourcetree.desktop"

    # Лаунчер
    install -Dm755 /dev/stdin "$pkgdir/usr/bin/opensourcetree" << 'EOF'
#!/bin/bash
exec python3 /opt/opensourcetree/main.py "$@"
EOF
}
