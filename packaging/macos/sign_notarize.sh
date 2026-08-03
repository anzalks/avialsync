#!/usr/bin/env bash
# Sign an AvialView .app, or notarize and staple a built disk image.
#
# Release CI runs this only when the signing secrets exist, so an unsigned
# build stays possible for forks and for local work (BLUEPRINT.md Phase 5:
# "signing/notarization steps stubbed behind secrets-present conditionals").
# Every credential arrives through the environment; nothing is read from a
# developer's login keychain, because CI has none.
#
#   sign_notarize.sh sign     dist/AvialView.app
#   sign_notarize.sh notarize installer-output/AvialView.dmg
#
# Environment:
#   MACOS_CERTIFICATE_P12       base64 of a Developer ID Application .p12
#   MACOS_CERTIFICATE_PASSWORD  password for that .p12
#   MACOS_SIGNING_IDENTITY      e.g. "Developer ID Application: Name (TEAMID)"
#   MACOS_NOTARY_APPLE_ID       Apple ID for notarytool          (notarize)
#   MACOS_NOTARY_PASSWORD       app-specific password            (notarize)
#   MACOS_NOTARY_TEAM_ID        team identifier                  (notarize)
set -euo pipefail

action=${1:?"usage: sign_notarize.sh <sign|notarize> <path>"}
target=${2:?"usage: sign_notarize.sh <sign|notarize> <path>"}

require_env() {
    for name in "$@"; do
        if [ -z "${!name:-}" ]; then
            echo "sign_notarize.sh: $name is not set; refusing to continue." >&2
            exit 1
        fi
    done
}

sign_app() {
    require_env MACOS_CERTIFICATE_P12 MACOS_CERTIFICATE_PASSWORD MACOS_SIGNING_IDENTITY
    local keychain certificate
    keychain="$RUNNER_TEMP/avialview-signing.keychain-db"
    certificate="$RUNNER_TEMP/avialview-certificate.p12"
    # A throwaway keychain, removed on exit however this script ends: the
    # certificate must not outlive the job that imported it.
    trap 'security delete-keychain "$keychain" 2>/dev/null || true; rm -f "$certificate"' EXIT

    printf '%s' "$MACOS_CERTIFICATE_P12" | base64 --decode > "$certificate"
    security create-keychain -p "$MACOS_CERTIFICATE_PASSWORD" "$keychain"
    security set-keychain-settings -lut 21600 "$keychain"
    security unlock-keychain -p "$MACOS_CERTIFICATE_PASSWORD" "$keychain"
    security import "$certificate" -k "$keychain" \
        -P "$MACOS_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
    security set-key-partition-list -S apple-tool:,apple: \
        -s -k "$MACOS_CERTIFICATE_PASSWORD" "$keychain" > /dev/null
    security list-keychain -d user -s "$keychain" login.keychain-db

    # --deep is deprecated and skips nested code; sign inner Mach-O files
    # first, then the bundle, so every signature is the outer one's dependency.
    find "$target/Contents" -type f \( -name '*.dylib' -o -name '*.so' \) -print0 |
        xargs -0 -r codesign --force --timestamp --options runtime \
            --sign "$MACOS_SIGNING_IDENTITY"
    codesign --force --timestamp --options runtime \
        --sign "$MACOS_SIGNING_IDENTITY" "$target"
    codesign --verify --strict --verbose=2 "$target"
}

notarize_dmg() {
    require_env MACOS_NOTARY_APPLE_ID MACOS_NOTARY_PASSWORD MACOS_NOTARY_TEAM_ID
    xcrun notarytool submit "$target" \
        --apple-id "$MACOS_NOTARY_APPLE_ID" \
        --password "$MACOS_NOTARY_PASSWORD" \
        --team-id "$MACOS_NOTARY_TEAM_ID" \
        --wait
    # Stapling is what lets the image open without a network round trip.
    xcrun stapler staple "$target"
    xcrun stapler validate "$target"
}

case "$action" in
    sign) sign_app ;;
    notarize) notarize_dmg ;;
    *)
        echo "sign_notarize.sh: unknown action '$action'; use sign or notarize." >&2
        exit 1
        ;;
esac
