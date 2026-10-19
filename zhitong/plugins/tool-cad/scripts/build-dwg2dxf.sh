#!/bin/sh
# Build a static LibreDWG dwg2dxf from the pinned official source release and
# install it with its GPL compliance files into bin/<platform>-<arch>/ of this
# package (the directory the plugin searches after Config.dwg2dxfPath and
# DWG2DXF_BIN). Used on Linux and macOS; Windows uses the official win64 zip
# (see bin/README.md).
#
# Usage: sh scripts/build-dwg2dxf.sh [work-directory]
# Needs: curl, a C compiler, make, shasum or sha256sum.
set -eu

VERSION=0.14
SHA256=62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275
URL="https://github.com/LibreDWG/libredwg/releases/download/${VERSION}/libredwg-${VERSION}.tar.xz"

here=$(cd "$(dirname "$0")/.." && pwd)
work=${1:-$(mktemp -d)}
case "$(uname -s)" in
  Linux) platform=linux ;;
  Darwin) platform=darwin ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=x64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) echo "unsupported CPU: $(uname -m)" >&2; exit 2 ;;
esac
dest="$here/bin/$platform-$arch"

mkdir -p "$work"
cd "$work"
curl -fsSL -o "libredwg-$VERSION.tar.xz" "$URL"
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "libredwg-$VERSION.tar.xz" | cut -d' ' -f1)
else
  actual=$(shasum -a 256 "libredwg-$VERSION.tar.xz" | cut -d' ' -f1)
fi
if [ "$actual" != "$SHA256" ]; then
  echo "sha256 mismatch: $actual" >&2
  exit 1
fi
tar -xJf "libredwg-$VERSION.tar.xz"
cd "libredwg-$VERSION"
./configure --disable-bindings --disable-shared
make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"

mkdir -p "$dest"
cp programs/dwg2dxf "$dest/dwg2dxf"
strip "$dest/dwg2dxf"
cp COPYING "$dest/COPYING"
{
  echo "LibreDWG dwg2dxf $VERSION"
  echo "source: $URL"
  echo "source sha256: $SHA256"
  echo "build: ./configure --disable-bindings --disable-shared; make; strip"
  echo "built: $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(uname -sm)"
} > "$dest/VERSION.txt"
cp "$here/bin/SOURCE-OFFER.txt" "$dest/SOURCE-OFFER.txt"
echo "installed $dest/dwg2dxf"
