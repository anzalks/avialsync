#!/usr/bin/env bash
set -euo pipefail

bundle_dir=${1:?"usage: make_dmg.sh <one-dir bundle> <output dmg>"}
output_dmg=${2:?"usage: make_dmg.sh <one-dir bundle> <output dmg>"}
staging_dir=$(mktemp -d)
trap 'rm -rf "$staging_dir"' EXIT

# Finder only treats the payload as an installable application when the ".app"
# extension survives the copy, so preserve it rather than renaming to "AvialView".
case "$bundle_dir" in
    *.app) cp -R "$bundle_dir" "$staging_dir/AvialView.app" ;;
    *) cp -R "$bundle_dir" "$staging_dir/AvialView" ;;
esac
ln -s /Applications "$staging_dir/Applications"
hdiutil create -volname AvialView -srcfolder "$staging_dir" -ov -format UDZO "$output_dmg"
