# Releasing Tabscribe (maintainers)

## Running from source

```bash
git clone --recurse-submodules https://github.com/AdamPomposelli/tabscribe
cd tabscribe
./run.sh          # first run creates .venv, builds the UI → http://127.0.0.1:8765
```

Dev mode: backend `uvicorn tabscribe.server:app --app-dir backend --port 8765 --reload`
and `npm --prefix frontend run dev` (http://127.0.0.1:5173, proxies `/api`).
From a checkout, `cd desktop && npm install && npm start` runs the desktop app on this checkout's
`.venv` (`npm run start:managed` tries the installer instead).


Two GitHub releases per version: `assets-YYYY.MM.N` holds the heavy files the app downloads on
first run (re-used across app versions while they don't change), `vX.Y.Z` holds the DMG.
Requires an Apple-silicon Mac, Xcode command line tools, `gh` logged in, ~10 GB free.

1. **Build the assets** (python-build-standalone CPython 3.11 + every package of
   `release/requirements-macos-arm64.lock`, a static LGPL ffmpeg compiled from source, the model
   weights, then `manifest.json` with size + sha256 + licence of every file):
   ```bash
   python3 release/build_assets.py --repo AdamPomposelli/tabscribe --tag assets-2026.11.1
   ```
   Outputs `release/out/<tag>/` and copies the manifest to `desktop/manifest.json` (it ships in the
   app). The runtime is smoke-tested (imports, ffmpeg) and checked for links outside itself.
   `--skip-runtime` reuses the last runtime; `--host-muscriptor` re-hosts the gated weights (only if
   their licence allows it for you).
2. **Test the release locally** before uploading anything (GitHub-like server with redirects and
   Range; `--rate 30` slows it down to watch progress, `--drop-after 50` cuts every file once):
   ```bash
   python3 release/serve_local.py assets-2026.11.1 --drop-after 50
   ```
   ```bash
   npm --prefix desktop run pack && TABSCRIBE_ASSETS_URL=http://127.0.0.1:8899/download/ TABSCRIBE_DATA_DIR=/tmp/ts-test desktop/dist/mac-arm64/Tabscribe.app/Contents/MacOS/Tabscribe
   ```
   `npm --prefix desktop test` runs the installer tests (resume, checksum, repair, disk space).
3. **Upload the assets** (creates a draft release, uploads, checks sizes, then asks before publishing;
   the repository must be public): `release/publish_assets.sh assets-2026.11.1`
4. **Build the DMG**: `npm --prefix desktop run dist` → `desktop/dist/Tabscribe-0.1.0-arm64.dmg`.
   - With a *Developer ID Application* certificate in the keychain, electron-builder signs with
     it (hardened runtime) and, when `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD` and `APPLE_TEAM_ID`
     (or `APPLE_API_KEY`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER`) are set, notarizes it.
   - Without one, the app is signed ad hoc: macOS says it "cannot verify" Tabscribe; users open it
     with right-click → Open, or System Settings → Privacy & Security → Open Anyway.
5. **Publish the app**: `release/publish_app.sh` (draft release `vX.Y.Z` with the DMG; publish it on GitHub).

## Windows

The models are shared: Windows only adds its own engine runtime to the same assets release, and
its own manifest (`desktop/manifest-win32-x64.json`, built into the Windows app).

1. **Build and test on GitHub Actions** (`.github/workflows/windows.yml`, runs on `windows-latest`):
   `release/build_runtime_windows.py` (CPython 3.11 + the lock minus macOS-only packages, PyTorch
   CPU, an LGPL ffmpeg from BtbN/FFmpeg-Builds), then `npm --prefix desktop run dist:win` (NSIS
   installer), then `release/e2e_test.js` against the unpacked app: first-run install from a local
   asset server and a full transcription of `bench/YeuEm.wav`. Outputs are workflow artifacts.
2. **Publish a passing run** server side: put its id and the target releases in
   `.github/windows-publish.json` and push it; `.github/workflows/windows-publish.yml` checks that
   the runtime matches the installer's manifest, then uploads the runtime (+ manifest) to the
   assets release and `Tabscribe-Setup-<version>-x64.exe` + `Tabscribe-Setup.exe` to the app release.
3. Commit the published `manifest-win32-x64.json` (download it from the assets release).

The installer is not code-signed: SmartScreen shows "Windows protected your PC" (More info → Run anyway).

Bump `version` in `desktop/package.json` for each app release. Rebuild the assets (new tag) only
when the lock file, a model or ffmpeg changes; unchanged components are not re-downloaded by users
who already have them (the installer compares checksums, not tags).
