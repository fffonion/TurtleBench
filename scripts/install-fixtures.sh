#!/usr/bin/env bash
set -euo pipefail

PASSWORD="123456"
EXPECTED_SHA256="c28746c7b8296a2b8eb36aef6c6cff5ae9418283409c291eaac139c772646069"
URL="https://github.com/fffonion/TurtleBench/releases/download/fixtures-v1/turtlebench-fixed-v1.zip"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DESTINATION="${1:-$PROJECT_ROOT/fixtures}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE="$TMP_DIR/turtlebench-fixed-v1.zip"

if [[ -n "${TURTLEBENCH_FIXTURE_ARCHIVE:-}" ]]; then
  cp "$TURTLEBENCH_FIXTURE_ARCHIVE" "$ARCHIVE"
else
  curl -fL "$URL" -o "$ARCHIVE"
fi

echo "$EXPECTED_SHA256  $ARCHIVE" | sha256sum -c -
mkdir -p "$DESTINATION"
unzip -q -P "$PASSWORD" -o "$ARCHIVE" -d "$DESTINATION"
echo "$DESTINATION/fixed-v1"
