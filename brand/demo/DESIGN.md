# Tabscribe README demo

## Style Prompt
A silent 28-second film for the README that shows the real Tabscribe, in English, the way
people use it. Each feature opens on a title in the middle of the screen, the app blurred and
dimmed behind it, then the camera moves over the real UI: a recording trimmed, the guitar
isolated from the band, the transcription running on the Mac, the pipeline, the score and tab
with chord boxes, playback synced to the original recording, the capo suggestion and the guitar
sounds. Then three "100%" promises and the Tabscribe lockup, whose frets drift like a waveform,
with "Stop transcribing. Start playing." Near-black canvas lit by one teal glow.

## Colors
- `#060908` canvas (ink)
- `#19C08F` Tabscribe teal: the brand (glow, highlight rings)
- `#7BE8C6` teal light: emphasis words on black
- `#FFFFFF` type on black
- Everything inside a capture is the app's own colours.

## Typography
- Plus Jakarta Sans 500/700/800 for titles and copy
- JetBrains Mono 400 for the HUD

## What NOT to Do
- No hand-drawn app screens: every Tabscribe screen is a capture of the real app (`capture.mjs`).
- No titles in a corner: feature titles sit in the middle of the screen.
- No real songs, artists or people: demo projects get invented titles.
- No `background-clip: text`, no emoji glyphs (grey boxes in capture), no `Math.random()`.
