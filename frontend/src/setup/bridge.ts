// The Electron preload bridge (desktop/preload.js). `setup` exists only in the packaged app.
export type Component = {
  id: string; name: string; kind: 'archive' | 'files'; description: string; required: boolean; default: boolean
  licence: string; licence_url: string | null; auth: string | null
  download_size: number; installed_size: number; installed: boolean; partial: number
}
export type SetupStatus = {
  managed: true; version: string; home: string; free: number; margin: number; ready: boolean; busy: boolean
  components: Component[]; hfTokenFound: boolean; lastProgress: Progress | null
}
export type Progress = {
  phase: 'download' | 'extract' | 'done'; component: string | null; file: string | null
  fileBytes: number; fileSize: number; done: number; total: number; speed: number; eta: number | null
  index: number; count: number
}
export type InstallResult = { ok: boolean; cancelled?: boolean; error?: string }
export type VerifyResult = Record<string, { ok: boolean; installed: boolean; problems: string[] }>

export type SetupBridge = {
  status: () => Promise<SetupStatus>
  install: (ids: string[], opts?: { hfToken?: string; force?: boolean }) => Promise<InstallResult>
  cancel: () => Promise<void>
  verify: () => Promise<VerifyResult>
  remove: (id: string) => Promise<void>
  removeAll: () => Promise<void>
  launch: () => Promise<void>
  open: () => Promise<void>
  reveal: () => Promise<void>
  logs: () => Promise<void>
  onProgress: (cb: (p: Progress) => void) => () => void
  onRetry: (cb: (r: { file: string; attempt: number; error: string }) => void) => () => void
  onVerifyStep: (cb: (s: { id: string; file: string | null }) => void) => () => void
}

import { mockBridge } from './mock'

export const setupBridge: SetupBridge | null = (window as unknown as { tabscribe?: { setup?: SetupBridge | null } }).tabscribe?.setup
  ?? (import.meta.env.DEV && new URLSearchParams(location.search).has('mock') ? mockBridge() : null)

/** The machine's name in UI copy: the same build runs on macOS and Windows. */
export const IS_MAC = !/Windows/.test(navigator.userAgent)
export const DEVICE = IS_MAC ? 'Mac' : 'PC'

export function bytes(b: number): string {
  if (b <= 0) return '0 MB'
  if (b >= 1e9) return `${(b / 1e9).toFixed(2)} GB`
  if (b >= 1e6) return `${(b / 1e6).toFixed(b >= 1e8 ? 0 : 1)} MB`
  return `${Math.max(1, Math.round(b / 1e3))} KB`
}

export function eta(s: number | null): string {
  if (s == null || !isFinite(s)) return ''
  if (s < 60) return 'less than a minute left'
  const m = Math.round(s / 60)
  return m < 60 ? `about ${m} min left` : `about ${Math.floor(m / 60)} h ${m % 60} min left`
}
