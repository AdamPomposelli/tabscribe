export type Note = { pitch: number; tick: number; end_tick: number; time: number; end_time: number; string: number; fret: number; voice: number; velocity: number; arpeggio?: 'up' | 'down' | null }
export type RawNote = { pitch: number; time: number; end_time: number; velocity: number }
export type Result = {
  title: string; artist: string; engine: string; duration: number; tempo: number
  key: { tonic: number; mode: string; name: string; accidentals: number }
  beats_per_bar: number; tuning: number[]; capo: number
  options: Options
  grid: { beats: number[]; first_beat_index: number; beats_per_bar: number; bpm: number; tpq: number }
  notes: Note[]; raw_notes: RawNote[]
  chords: { tick: number; name: string; frets: number[] }[]
  stats: Record<string, number>
  arranger?: string
  capo_suggestion?: { capo: number; shapes: string[]; key_shape: string | null; ranking: { capo: number; cost: number; lost_notes: number; shape_cost: number; open_string_share: number }[] }
}
export type Options = { engine: string; muscriptor_size: string; separate: boolean; difficulty: string; transpose: number; tuning: string; capo: number; beats_per_bar?: number; key?: string }
export type Meta = { id: string; title: string; artist: string; state: string; created: number; updated: number; error?: string; options: Options; engine?: string; filename?: string; trim?: [number, number | null] | null }
export type Status = { state: string; progress?: number; stage?: string; message?: string; started?: number; stages?: string[] }
export type CreateOpts = {
  title?: string; separate?: boolean; engine?: string; start?: number; end?: number
  beats_per_bar?: number; tuning?: string; capo?: number; key?: string; difficulty?: string
}
export type Engines = Record<string, { available: boolean; label: string; help?: string }> & { tunings: string[] }

export type Prefs = { guitar_sound?: string }

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail ?? msg } catch { /* not json */ }
    throw new Error(msg)
  }
  return r.json()
}

export const api = {
  projects: (q = '') => fetch(`/api/projects?q=${encodeURIComponent(q)}`).then(j<Meta[]>),
  project: (id: string) => fetch(`/api/projects/${id}`).then(j<{ meta: Meta; status: Status; result: Result | null }>),
  status: (id: string) => fetch(`/api/projects/${id}/status`).then(j<Status>),
  engines: () => fetch('/api/engines').then(j<Engines>),
  create: (file: File, opts: CreateOpts) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('title', opts.title ?? '')
    fd.append('separate', String(!!opts.separate))
    fd.append('engine', opts.engine ?? 'auto')
    if (opts.start) fd.append('start', String(opts.start))
    if (opts.end) fd.append('end', String(opts.end))
    for (const k of ['beats_per_bar', 'tuning', 'capo', 'key', 'difficulty'] as const) {
      if (opts[k] !== undefined && opts[k] !== '') fd.append(k, String(opts[k]))
    }
    return fetch('/api/projects', { method: 'POST', body: fd }).then(j<Meta>)
  },
  arrange: (id: string, body: Partial<Options> & { title?: string; artist?: string }) =>
    fetch(`/api/projects/${id}/arrange`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(j<{ ok: boolean }>),
  rename: (id: string, title: string) =>
    fetch(`/api/projects/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }).then(j<{ ok: boolean; meta: Meta }>),
  prefs: () => fetch('/api/prefs').then(j<Prefs>),
  savePrefs: (p: Prefs) =>
    fetch('/api/prefs', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) }).then(j<Prefs>),
  remove: (id: string) => fetch(`/api/projects/${id}`, { method: 'DELETE' }).then(j<{ ok: boolean }>),
  file: (id: string, name: string, bust = '') => `/api/projects/${id}/files/${name}${bust ? `?v=${bust}` : ''}`,
}
