/**
 * useCapabilities — capability-slot data source for the dashboard's
 * embed/voice/img cards and the NPU backend rollup beneath /slots.
 *
 * Wraps the live `/api/capabilities` endpoint (provisioned by the
 * hal0-api capability-slot service). The composable is a singleton at
 * module scope so every card shares one request/refresh cycle and a
 * single source of truth — selections changed from one card are visible
 * everywhere without further plumbing.
 *
 * Shape returned by the API (kept stable; cards bind to it directly):
 *
 *   {
 *     backends:   [{ id, label, short, provider, multiplex }],
 *     catalogs:   { embed: { embed:[…], rerank:[…] }, voice: { stt:[…], tts:[…] }, img: { img:[…] } },
 *     selections: { embed: { embed:{backend,provider,model,enabled,slot,status}, rerank:{…} }, voice:{…}, img:{…} }
 *   }
 *
 * POST `/api/capabilities/{slot}/{child}` body `{ backend?, provider?,
 * model?, enabled? }` → `{ ok, selection }`. `setSelection` does an
 * optimistic patch and reverts on failure so the dropdown / pill snap
 * back if the backend rejects the change.
 *
 * `useBackend(id)` is a separate composable for backend-level snapshots
 * (NPU memory bar, currently-loaded list). It polls `/api/backends/{id}`
 * every 5s.
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from './useApi.js'

let _state = null  // module-level singleton across consumers

export function useCapabilities() {
  if (_state) return _state

  const backends   = ref([])
  const catalogs   = ref({})
  const selections = ref({})
  const loading    = ref(true)
  const error      = ref(null)

  async function refresh() {
    loading.value = true
    try {
      const data = await api('/api/capabilities')
      backends.value   = data?.backends ?? []
      catalogs.value   = data?.catalogs ?? {}
      selections.value = data?.selections ?? {}
      error.value = null
    } catch (e) {
      error.value = e?.message ?? String(e)
    } finally {
      loading.value = false
    }
  }

  async function setSelection(slot, child, partial) {
    // Optimistic update — snapshot prior child for revert on failure.
    const before = JSON.parse(
      JSON.stringify(selections.value?.[slot]?.[child] ?? {}),
    )
    if (selections.value?.[slot]?.[child]) {
      selections.value[slot][child] = { ...selections.value[slot][child], ...partial }
    }
    try {
      const res = await api(`/api/capabilities/${slot}/${child}`, {
        method: 'POST',
        body: JSON.stringify(partial),
      })
      if (res?.selection && selections.value?.[slot]) {
        selections.value[slot][child] = res.selection
      }
      return res
    } catch (e) {
      // Revert
      if (selections.value?.[slot]) {
        selections.value[slot][child] = before
      }
      throw e
    }
  }

  function backendById(id) {
    return backends.value.find((b) => b.id === id) ?? null
  }

  function modelsForCapability(slot, capability) {
    return catalogs.value?.[slot]?.[capability] ?? []
  }

  // Used by the NPU backend card's local-extras list. The live "loaded"
  // array comes from /api/backends/{id} — this helper only filters the
  // current `selections` map by backend so we can render which slot
  // children point at a given backend.
  function childrenOnBackend(allSelections, backendId) {
    const out = []
    for (const slot of Object.keys(allSelections || {})) {
      const slotSel = allSelections[slot] || {}
      for (const child of Object.keys(slotSel)) {
        if (slotSel[child]?.backend === backendId) {
          out.push({ slot, child, modelId: slotSel[child].model })
        }
      }
    }
    return out
  }

  _state = {
    backends, catalogs, selections, loading, error,
    refresh, setSelection,
    backendById, modelsForCapability, childrenOnBackend,
  }
  refresh()
  return _state
}

/**
 * useBackend(id) — poll /api/backends/{id} every 5s.
 *
 * Shape:
 *   { id, hardware, driver, state,
 *     memUsedMb, memTotalMb, totalReqPerSec,
 *     loaded: [{ slot, child, modelId, sizeMb }] }
 *
 * Returns `{ data, error, refresh }`. Errors are kept available rather
 * than silenced so the NPU card can dim its memory bar on backend
 * outage.
 */
export function useBackend(id) {
  const data = ref(null)
  const error = ref(null)
  let timer = null

  async function poll() {
    try {
      data.value = await api(`/api/backends/${id}`)
      error.value = null
    } catch (e) {
      error.value = e?.message ?? String(e)
    }
  }

  onMounted(() => {
    poll()
    timer = setInterval(poll, 5000)
  })
  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { data, error, refresh: poll }
}
