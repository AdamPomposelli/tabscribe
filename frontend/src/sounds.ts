/** Guitar sound libraries for playback (SoundFonts in public/soundfont/guitars).
 *
 * Each file holds a single guitar preset at bank 0 / program 24, the program the scores use,
 * so switching sound is just loading another file (built with tools/sf2_extract.py).
 * Licences are in public/soundfont/guitars/licenses.
 */
export type GuitarSound = {
  id: string
  label: string
  short: string
  hint: string
  url: string
}

export const GUITAR_SOUNDS: GuitarSound[] = [
  {
    id: 'fss-steel',
    label: 'Steel acoustic · Recommended',
    short: 'Steel',
    hint: 'Real steel-string, sampled',
    url: '/soundfont/guitars/fss-steel.sf2',
  },
  {
    id: 'freepats-classical',
    label: 'Classical nylon',
    short: 'Nylon',
    hint: 'Real nylon, warm and soft',
    url: '/soundfont/guitars/freepats-classical.sf2',
  },
  {
    id: 'generaluser-steel',
    label: 'GeneralUser GS · Steel',
    short: 'GU steel',
    hint: 'Light and bright steel',
    url: '/soundfont/guitars/generaluser-steel.sf2',
  },
  {
    id: 'generaluser-nylon',
    label: 'GeneralUser GS · Nylon',
    short: 'GU nylon',
    hint: 'Light, rounder nylon',
    url: '/soundfont/guitars/generaluser-nylon.sf2',
  },
  {
    id: 'sonivox',
    label: 'Sonivox (classic)',
    short: 'Sonivox',
    hint: 'Synthetic, loads instantly',
    url: '/soundfont/guitars/sonivox-nylon.sf2',
  },
]

export const DEFAULT_SOUND = 'fss-steel'

export const soundById = (id?: string | null) => GUITAR_SOUNDS.find(s => s.id === id) ?? GUITAR_SOUNDS.find(s => s.id === DEFAULT_SOUND)!
