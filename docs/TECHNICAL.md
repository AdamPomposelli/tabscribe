# How Tabscribe works

The technical side of Tabscribe: every stage of the pipeline, how it was measured, and the
licence of every model and sound it uses. For installing and using the app, see the
[README](../README.md).

## Pipeline

| Stage | Model / method | Taken from |
|---|---|---|
| Decode | ffmpeg → 44.1 kHz PCM | all |
| Guitar isolation (optional, songs with vocals or a band) | **BS-RoFormer SW** 6-stem model, guitar stem (9.3 s windows, 2× overlap, MPS/CUDA); Demucs **htdemucs_6s** as fallback. Picked by blind listening against htdemucs_6s, MelBand-RoFormer guitar and their ensemble (`guitar-extract-research/REPORT.md`) | python-audio-separator (inference), autotab-rust (6-stem idea), autotabber (normalisation) |
| Transcription | **Majority vote of 7 models**: Tsumugi default / guitar / guitar v1.5 / other v1.5, Transkun v2, MuScriptor medium, Basic Pitch. Onsets from MuScriptor (best rhythm), offsets from Transkun (best durations) | all repos + Transkun, Tsumugi (via voidtrackr) |
| Cleanup | overtone suppression, re-attack merge, relative-level gate, cut-in removal | new (tuned with mir_eval) + autotabber ideas |
| Beats & downbeats | **Beat This!** (CPJKU, ISMIR 2024) + madmom **DBN** post-processing, then **onset-guided correction** (`beatfix.py`, dynamic programme over note attacks with a smooth-tempo penalty) for live / no-metronome playing, gap repair, tempo map | chosen among 7 trackers (beat_this ± DBN, beat_this_live, madmom, md_beat_this, wavebeat, Mixxx) on a tempo-warped stress test — see below |
| Quantization | beat-relative 16ths / 8th-triplets, chosen per beat | new |
| Fingering | **Open-Fret** (Fretting-Transformer T5 trained on ~188k Guitar Pro tracks, anchored decoding → per-note position priors) + **tab-labeler v3** CNN emission + beam search: one note per string, held-string awareness, span cap, span/move costs, open-string preference | autotab-rust (model), riffforge (exact DP), fixes for tab-agent-pro's chord bug |
| Harmony | Krumhansl key + attack-weighted chord templates (maj7/9/13/sus…) per bar on MuScriptor's full output | new |
| Engraving | 2 voices, ties across bars, dotted/tuplet durations, chord diagrams, **rolled chords** (3+ staggered attacks ≤130 ms apart, one direction, ringing together → one chord with an arpeggio ↑/↓ sign; MIDI keeps the real stagger) | autotab-rust GP5 ideas |
| Output | Guitar Pro 5 (rendered by alphaTab), MIDI (score + performance), JSON | |

## Accuracy (two reference songs)

`python bench/full.py` runs the real pipeline on both songs and scores the exported `score.mid` against hand-checked reference transcriptions
(mir_eval, 50 ms onsets) plus chords and rolled chords.

| | Notes F1 | Rhythm F1 | Durations F1 (20 %) | Chords | Meter |
|---|---|---|---|---|---|
| YeuEm (30 s) | **0.987** | **0.985** | 0.63 | 13/15 roots | 4/4 auto |
| hoadanhdanhguitar (83 s) | **0.858** | **0.887** | 0.36 | **79 % roots / 77 % root+quality** (was 52 / 36) | 4/4 auto (was 2/4) |

What moved the numbers on the second song (each change validated on BOTH songs):
* onsets from Tsumugi instead of MuScriptor (MuScriptor drifts ~90 ms on some 5 s chunk edges);
* chord notes aligned on one onset (60 ms), rolled chords excluded;
* score MIDI keeps deliberate off-grid attacks (> 35 ms from the grid) instead of snapping them;
* chords, key and meter from Tsumugi's MIDI-frame beat/chord/key model, spelled in the key (E# in F#, Bb in F);
* chord boxes = standard playable grips near the hand position (`voicings.py`);
* engraving: legato upper voice, bass held to the next bass note within the half bar, values that
  start on their own grid and don't cross the middle of the bar, triplets only when clearly played.

Known limits: on hoa the reference keeps part of the performance timing and writes rolled chords
the audio does not always show (rolls agree 6/11); durations remain notation choices.

## Live performances (tempo drift)

The score is never built on a fixed BPM: every note is placed by interpolating between the
*tracked* beats, so a drifting tempo is already normalised in the symbolic domain. Time-stretching
the audio to a constant tempo before transcription was measured and rejected: the stretch
artefacts cost the transcription 7–12 points of note F1, and re-tracking a stretched file just
re-uses the first tracker's mistakes. What matters is that the beats are right, so
`bench/tempo/` simulates live takes (±14–27 % smooth tempo drift, WSOLA, exact time map so the
reference MIDI is warped too) and compares trackers:

| Tracker (8 cases: 2 originals + 6 live) | beat F orig | beat F live | live + onset fix | downbeats | s / min |
|---|---|---|---|---|---|
| beat_this (previous) | 0.998 | 0.894 | 0.943 | 0.88 | 2.0 |
| **beat_this + DBN (now)** | **0.998** | **0.949** | **0.969** | **1.00** | 3.6 |
| madmom RNN+DBN (non-commercial models) | 0.994 | 0.965 | 0.962 | 0.99 | 4.7 |
| md_beat_this (non-commercial) | 0.998 | 0.952 | 0.959 | 0.99 | 36.4 |
| wavebeat | 0.867 | 0.721 | 0.707 | 0.72 | 4.1 |
| Mixxx (qm-dsp) | 0.394 | 0.360 | 0.516 | 0.58 | 0.3 |
| beat_this_live (causal) | 0.976 | 0.490 | 0.593 | 0.81 | 6.8 |

Notation F1 (notes written in the right 16th slot) on live takes went from 0.31–0.50 to
0.66–0.73; originals unchanged (0.75 / 0.79). Downbeats are scored against where the chords change.

## MuScriptor (optional 7th model)

Weights are gated on Hugging Face (CC BY-NC 4.0, non-commercial). Without them the vote uses the
other 6 models with the same 4-vote threshold, which gives the same note F1 on both reference
songs (0.975 / 0.857), so the app does not need them. In the desktop app, tick **MuScriptor** in
Settings → Components: it uses your `hf auth login` token if there is one, otherwise asks for a
read token, and downloads from Hugging Face (accept the licence on
https://huggingface.co/MuScriptor/muscriptor-medium first). In a checkout: `hf auth login` once.

## Guitar sounds (playback)

The score plays through a guitar SoundFont you pick under **Guitar sound** in the project panel.
The choice is saved in `data/prefs.json`, so it survives restarts. The default is the
community favourite among free, properly licensed guitar SoundFonts:

| Sound | Source | Licence |
|---|---|---|
| Steel-string acoustic (default) | FreePats "FSS Steel String Guitar" (Seagull samples by FlameStudios) | GPL-3.0 + FreePats exception |
| Spanish classical (nylon) | FreePats "Spanish Classical Guitar" | CC0 |
| GeneralUser GS steel / nylon | GeneralUser GS 2.0 (S. Christian Collins) | free, incl. commercial |
| Sonivox (classic) | Sonivox EAS GM bank (the previous sound) | Android AOSP |

Each file in `frontend/public/soundfont/guitars/` holds only the guitar preset at program 24
(the program the scores use). They were built with `tools/sf2_extract.py`, with levels matched
(`--gain`, `--preset-att`). Licences are in `frontend/public/soundfont/guitars/licenses/`.
Rips of commercial libraries (Pianoteq, RealGuitar, GarageBand...) were left out on purpose.

## Licences of bundled/downloaded models

Basic Pitch (Apache-2.0), Open-Fret code + weights (MIT, `vendor/open_fret_pkg`, `mylonasc/open-fret-tab`), Transkun (MIT), Tsumugi (MIT; vendored in `vendor/tsumugi`, own venv `.venv-tsumugi` with torch 2.13), Beat This! weights (MIT, `safe-models/beat-this-final0`
safetensors mirror), tab-labeler (CC BY 4.0), Demucs (MIT), MuScriptor weights (CC BY-NC 4.0).
BS-RoFormer SW: model code vendored in `backend/tabscribe/roformer` from python-audio-separator (MIT) with
rotary-embedding-torch 0.6.5 (MIT); the weights (`enerjazzer/BS-ROFO-SW-Fixed`, a mirror of jarredou's checkpoint)
carry **no stated licence** (Hugging Face card: "unknown"; one third-party list says CC BY-NC-SA 4.0), so they are
not re-hosted: the app downloads them from Hugging Face. Check this before any commercial distribution.

