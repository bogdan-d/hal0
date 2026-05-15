import { useToastsStore } from '../stores/toasts.js'

const BASE = ''  // dev server proxies /api and /v1 to :8080

/**
 * Minimal fetch wrapper.
 *
 * Usage:
 *   const data = await api('/api/slots')
 *   await api('/api/slots/primary/restart', { method: 'POST' })
 */
export async function api(path, options = {}) {
  const url = BASE + path
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!res.ok) {
    let message = `API error ${res.status}`
    let body = null
    try {
      body = await res.json()
      message = body?.error?.message || body?.detail || message
    } catch {
      // ignore parse failure
    }
    // Surface the full envelope (code + details map) on the Error
    // instance so callers like Settings.vue can render per-field
    // validation reasons inline next to the offending input. The
    // ``message`` stays the human-readable string for toasts.
    const err = new Error(message)
    err.status  = res.status
    err.code    = body?.error?.code ?? null
    err.details = body?.error?.details ?? null
    err.body    = body
    throw err
  }

  if (res.status === 204) return null
  return res.json()
}

/**
 * Same as api() but automatically shows a toast on error and re-throws.
 */
export function useApi() {
  const toasts = useToastsStore()

  async function call(path, options = {}) {
    try {
      return await api(path, options)
    } catch (err) {
      toasts.error(err.message)
      throw err
    }
  }

  return { call, api }
}
