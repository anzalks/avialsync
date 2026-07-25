#!/usr/bin/env bash
set -euo pipefail

bundle_dir=${1:?"usage: make_dmg.sh <one-dir bundle> <output dmg>"}
output_dmg=${2:?"usage: make_dmg.sh <one-dir bundle> <output dmg>"}
staging_dir=$(mktemp -d)
trap 'rm -rf "$staging_dir"' EXIT

cp -R "$bundle_dir" "$staging_dir/AvialView"
ln -s /Applications "$staging_dir/Applications"
hdiutil create -volname AvialView -srcfolder "$staging_dir" -ov -format UDZO "$output_dmg"
