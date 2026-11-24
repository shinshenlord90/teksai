#!/bin/sh
# Bina pakej .deb dari packaging/teksai ke dist/
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^Version: //p' packaging/teksai/DEBIAN/control)
find packaging -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
chmod 755 packaging/teksai/DEBIAN/postinst packaging/teksai/DEBIAN/postrm packaging/teksai/usr/bin/teksai
chmod -R go-w packaging/teksai
mkdir -p dist
dpkg-deb --root-owner-group --build packaging/teksai "dist/teksai_${VERSION}_all.deb"
