#!/usr/bin/env bash
set -euo pipefail

version=3.12.16
prefix="${NSO_PYTHON_PREFIX:-$PWD/.runtime/python-$version}"
if [ -x "$prefix/bin/python3.12" ] && [ "$("$prefix/bin/python3.12" -c 'import platform; print(platform.python_version())')" = "$version" ]; then
  printf '%s\n' "$prefix/bin/python3.12"
  exit 0
fi
if command -v python3.12 >/dev/null && [ "$(python3.12 -c 'import platform; print(platform.python_version())')" = "$version" ]; then
  command -v python3.12
  exit 0
fi
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/nso-python312.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 "https://www.python.org/ftp/python/$version/Python-$version.tar.xz" -o "$build_dir/python.tar.xz" >&2
printf '%s  %s\n' b5796915dc45ff745cfb4e990a7e7c93d6f546328a102ce31448d69ebc37575c "$build_dir/python.tar.xz" | shasum -a 256 -c - >&2
tar -xJf "$build_dir/python.tar.xz" -C "$build_dir"
cd "$build_dir/Python-$version"
if [ "$(uname -s)" = Darwin ]; then
  ./configure --prefix="$prefix" --with-openssl=/opt/homebrew/opt/openssl@3 --with-ensurepip=install >&2
else
  ./configure --prefix="$prefix" --with-ensurepip=install >&2
fi
make -j 4 >&2
make install >&2
"$prefix/bin/python3.12" -c 'import ssl, sqlite3, bz2, lzma, ctypes' >&2
printf '%s\n' "$prefix/bin/python3.12"
