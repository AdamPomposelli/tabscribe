#!/usr/bin/env bash
# Upload the built DMG (desktop/dist) as the app release vX.Y.Z. Run after `npm --prefix desktop run dist`.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(node -p "require('./desktop/package.json').version")
DMG="desktop/dist/Tabscribe-$VERSION-arm64.dmg"
[ -f "$DMG" ] || { echo "missing $DMG (npm --prefix desktop run dist)"; exit 1; }
REPO=$(python3 -c "import json;u=json.load(open('desktop/manifest.json'))['base_url'];print(u.split('github.com/')[1].split('/releases')[0])")
ASSETS=$(python3 -c "import json;print(json.load(open('desktop/manifest.json'))['version'])")
gh release view "$ASSETS" --repo "$REPO" --json isDraft -q .isDraft 2>/dev/null | grep -q false \
  || echo "WARNING: assets release $ASSETS is missing or still a draft: the app's setup would fail. Run release/publish_assets.sh $ASSETS"
shasum -a 256 "$DMG"
read -r -p "Create DRAFT release v$VERSION on $REPO with $(du -h "$DMG" | cut -f1) DMG? [y/N] " ok
[ "$ok" = "y" ] || exit 1
gh release create "v$VERSION" "$DMG" --repo "$REPO" --draft --title "Tabscribe $VERSION" \
  --notes "Download **Tabscribe-$VERSION-arm64.dmg** (Apple silicon, macOS 12+), drag Tabscribe to Applications and open it. On first launch it downloads its engine and AI models (about $(python3 -c "import json;m=json.load(open('desktop/manifest.json'));print(round(sum(c['download_size'] for c in m['components'] if c['required'])/1e9,1))") GB) from this repository, with progress, then works offline."
echo "Draft created: review it on GitHub, then publish it there (or: gh release edit v$VERSION --repo $REPO --draft=false)."
