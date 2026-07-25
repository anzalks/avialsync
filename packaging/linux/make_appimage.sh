#!/usr/bin/env bash
set -euo pipefail

bundle_dir=${1:?"usage: make_appimage.sh <one-dir bundle> <output AppImage>"}
output_appimage=${2:?"usage: make_appimage.sh <one-dir bundle> <output AppImage>"}
: "${APPIMAGETOOL:?Set APPIMAGETOOL to a verified appimagetool binary path.}"

appdir=$(mktemp -d)
trap 'rm -rf "$appdir"' EXIT
mkdir -p "$appdir/usr/avialview"
cp -R "$bundle_dir/." "$appdir/usr/avialview/"
cat > "$appdir/AppRun" <<'EOF'
#!/usr/bin/env sh
exec "$(dirname "$0")/usr/avialview/avialview" "$@"
EOF
chmod +x "$appdir/AppRun"
cat > "$appdir/avialview.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=AvialView
Exec=avialview
Categories=Science;Video;
Terminal=false
EOF
"$APPIMAGETOOL" "$appdir" "$output_appimage"
