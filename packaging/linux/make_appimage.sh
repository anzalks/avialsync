#!/usr/bin/env bash
# Keep this file LF-terminated; Bash on a Windows checkout rejects CRLF options.
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bundle_dir=${1:?"usage: make_appimage.sh <one-dir bundle> <output AppImage>"}
output_appimage=${2:?"usage: make_appimage.sh <one-dir bundle> <output AppImage>"}
: "${APPIMAGETOOL:?Set APPIMAGETOOL to a verified appimagetool binary path.}"

appdir=$(mktemp -d)
trap 'rm -rf "$appdir"' EXIT
mkdir -p "$appdir/usr/avialsync"
cp -R "$bundle_dir/." "$appdir/usr/avialsync/"
cat > "$appdir/AppRun" <<'EOF'
#!/usr/bin/env sh
exec "$(dirname "$0")/usr/avialsync/avialsync" "$@"
EOF
chmod +x "$appdir/AppRun"
cat > "$appdir/avialsync.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=AvialSync
Exec=avialsync
Icon=avialsync
Categories=Science;Video;
Terminal=false
EOF
install -m 644 "$script_dir/avialsync.png" "$appdir/avialsync.png"
ln -s avialsync.png "$appdir/.DirIcon"
desktop-file-validate "$appdir/avialsync.desktop"
"$APPIMAGETOOL" "$appdir" "$output_appimage"
