# README demo

The source of `brand/readme/tabscribe-demo.webp`, the animation at the top of the README. Every
screen in it is the real Tabscribe UI, captured from the app on invented demo projects: a
recording trimmed, the guitar isolated from the band, the real transcription job running, the
pipeline in Settings, the score and tab with chord boxes, playback synced to the original, the
capo suggestion and the guitar sounds. Then three "100%" promises and the Tabscribe lockup with
"Stop transcribing. Start playing."

It is a [HyperFrames](https://github.com/heygen-com/hyperframes) composition, built with the
[Herk Edit Kit](https://github.com/nateherkai/herk-edit-kit) and its motion rules. Nothing here
is part of the app.

| File | What it is |
|---|---|
| `capture.mjs` | Drives the real app with Playwright and writes `captures/*.png` plus `captures/boxes.json` (where the elements the camera aims at are). |
| `index.template` | The composition: scenes, camera over the captures, centred titles, timeline. |
| `build.py` | Fills the template from the captures and writes `index.html`. |
| `DESIGN.md` | Palette, type and what not to do. |
| `../hero.py` | Draws the README lockups, and with `--inline` the animated lockup for the video. |

## Re-render

You need Node 22+, FFmpeg, Google Chrome, Python 3 with fontTools, `img2webp` (Homebrew `webp`),
and Plus Jakarta Sans 500/700/800 + JetBrains Mono 400 as woff2.

1. **Demo data:** copy a few finished projects into a folder of their own and give them invented
   titles (`meta.json` and `result.json`), then serve the built UI on it:
   `TABSCRIBE_DATA=<demo data> .venv/bin/python -m uvicorn tabscribe.server:app --app-dir backend --port 8790`.
2. **Captures:** in a folder with `npm i playwright` (no browser download needed),
   `node brand/demo/capture.mjs <playwright dir> <kit>/video-projects/tabscribe-demo/captures <a guitar recording>`.
   It starts a real transcription for the processing shot. Look at the PNGs.
3. **Kit project:** in a Herk Edit Kit checkout, `npm ci`, `npx hyperframes telemetry disable`,
   `npm run new-video -- tabscribe-demo`. Copy `index.template` and `build.py` into it, the fonts
   into `assets/fonts/`, `node_modules/gsap/dist/gsap.min.js` into `assets/`, and the lockup:
   `python3 brand/hero.py --font <PlusJakartaSans-800.woff2> --out <project>/assets --inline`.
4. **Render:** `python3 build.py`, `npx hyperframes lint` (0 warnings),
   `npx hyperframes render --quality high --fps 30 --output renders/tabscribe-demo.mp4`, and
   review contact sheets around every transition.
5. **Export** (under 5 MB):

   ```bash
   mkdir frames && ffmpeg -i renders/tabscribe-demo.mp4 -vf "fps=15,scale=960:-1:flags=lanczos" frames/f%04d.png
   img2webp -loop 0 -lossy -q 68 -m 6 -d 67 frames/f*.png -o brand/readme/tabscribe-demo.webp
   ```

An animated WebP rather than a video, so the README plays it on its own with no play button, and
rather than a GIF, which is several times heavier.
