#!/usr/bin/env bash
# Upload the assets built by build_assets.py to a GitHub release (the app's installer downloads them).
#   release/publish_assets.sh assets-2026.11.1            # asks before every step that touches GitHub
#   release/publish_assets.sh assets-2026.11.1 --dry-run  # only show what would happen
# The release is created as a draft, assets are uploaded and checked (size + sha256 in the manifest),
# then you're asked whether to publish it. Draft assets are NOT downloadable by users.
set -euo pipefail
cd "$(dirname "$0")"
TAG="${1:?usage: publish_assets.sh TAG [--dry-run]}"
DRY="${2:-}"
OUT="out/$TAG"
MAN="$OUT/manifest.json"
[ -f "$MAN" ] || { echo "no $MAN: run build_assets.py --tag $TAG first"; exit 1; }
REPO=$(python3 -c "import json,sys;u=json.load(open('$MAN'))['base_url'];print(u.split('github.com/')[1].split('/releases')[0])")
FILES=$(python3 - "$MAN" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for c in m["components"]:
    for f in c["files"]:
        if "url" not in f:  # hosted on GitHub (not fetched from upstream with the user's own token)
            print(f["name"])
PY
)
TOTAL=$(cd "$OUT" && du -ch $FILES | tail -1 | cut -f1)
echo "Repository : $REPO   (must be PUBLIC for anonymous downloads)"
echo "Release    : $TAG"
echo "Assets     : $(echo "$FILES" | wc -l | tr -d ' ') files, $TOTAL"
echo "$FILES" | sed 's/^/   /'
gh auth status >/dev/null || { echo "gh is not logged in (gh auth login)"; exit 1; }
if ! gh repo view "$REPO" --json visibility -q .visibility >/dev/null 2>&1; then
  echo "Repository $REPO does not exist (or you can't see it). Create it first, e.g.:"
  echo "   gh repo create $REPO --public --source .. --remote origin"
  exit 1
fi
VIS=$(gh repo view "$REPO" --json visibility -q .visibility)
[ "$VIS" = "PUBLIC" ] || echo "WARNING: $REPO is $VIS — users will get HTTP 404 on every download."
[ "$DRY" = "--dry-run" ] && { echo "(dry run: nothing uploaded)"; exit 0; }

read -r -p "Create/update the DRAFT release $TAG on $REPO and upload $TOTAL? [y/N] " ok
[ "$ok" = "y" ] || exit 1
if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release create "$TAG" --repo "$REPO" --draft --latest=false --title "Tabscribe engine & models ($TAG)" \
    --notes "Runtime and model files downloaded by the Tabscribe app on first run (see manifest.json). Not meant to be downloaded by hand."
fi
for f in $FILES manifest.json; do
  echo "uploading $f"
  gh release upload "$TAG" "$OUT/$f" --repo "$REPO" --clobber
done
# check what GitHub has against the manifest
gh release view "$TAG" --repo "$REPO" --json assets -q '.assets[] | "\(.name) \(.size)"' > "$OUT/.uploaded.txt"
python3 - "$MAN" "$OUT/.uploaded.txt" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])); up = dict(l.split() for l in open(sys.argv[2]) if l.strip())
bad = [f["name"] for c in m["components"] for f in c["files"] if "url" not in f and int(up.get(f["name"], -1)) != f["size"]]
sys.exit("size mismatch / missing on GitHub: " + ", ".join(bad)) if bad else print("all assets present with the right sizes")
PY
read -r -p "Publish $TAG now (makes the files downloadable by everyone)? [y/N] " ok
[ "$ok" = "y" ] && gh release edit "$TAG" --repo "$REPO" --draft=false --latest=false && echo "published."
