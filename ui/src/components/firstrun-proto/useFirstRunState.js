/**
 * useFirstRunState — singleton form state shared by FirstRun prototype variants.
 *
 * THROWAWAY. Lives only while the three variants on /firstrun?variant=A|B|C
 * compete. Pick a winner, fold its render into FirstRun.vue, delete this file
 * (and the sibling Variant*.vue + PrototypeSwitcher.vue).
 *
 * Reads (live):
 *   GET /api/hardware           — backends, npu, disk_free_mb
 *   GET /api/install/state      — first_run flag
 *   GET /api/install/curated-models  — primary chat picker source
 *   GET /api/capabilities       — backends + catalogs + current selections
 *
 * Writes (STUBBED — do not point at real install endpoints from a prototype):
 *   applyAll()  — fakes a multi-bar pull with setTimeout. Real wiring lands
 *                 when a variant wins.
 */
import { reactive, computed, ref } from 'vue'
import { api } from '../../composables/useApi.js'

let _state = null

const SMART_DEFAULTS = {
  embed: {
    npu: { model: 'embed-gemma-300m-npu', backend: 'npu', enabled: true },
    vulkan: { model: 'nomic-embed-text-v1.5', backend: 'gpu-vulkan', enabled: true },
    rocm: { model: 'nomic-embed-text-v1.5', backend: 'gpu-rocm', enabled: true },
    cpu: { model: null, backend: 'cpu', enabled: false },
  },
  rerank: { enabled: false },
  stt: {
    npu: { model: 'whisper-v3-npu', backend: 'npu', enabled: true },
    other: { model: null, enabled: false },
  },
  tts: { enabled: false },
  img: { enabled: false },
}

function pickBackend(hw) {
  if (hw?.npu_present) return 'npu'
  const g = hw?.gpu_vendor || ''
  if (g === 'amd' && !hw?.is_uma) return 'rocm'
  if (g === 'nvidia') return 'rocm'
  if (hw?.gpus?.some?.((x) => x.vulkan_capable)) return 'vulkan'
  return 'cpu'
}

export function useFirstRunState() {
  if (_state) return _state

  const loading = ref(true)
  const error = ref(null)
  const firstRun = ref(true)

  const hardware = ref(null)
  const curated = ref([])
  const customAllowed = ref(false)
  const capsData = ref({ backends: [], catalogs: {}, selections: {} })

  const form = reactive({
    password: '',
    skipPassword: false,
    passwordAlreadySet: false,
    modelDir: '/var/lib/hal0/models',
    primaryId: null,
    primaryCustom: null,
    caps: {
      embed:  { enabled: false, backend: null, model: null, provider: null },
      rerank: { enabled: false, backend: null, model: null, provider: null },
      stt:    { enabled: false, backend: null, model: null, provider: null },
      tts:    { enabled: false, backend: null, model: null, provider: null },
      img:    { enabled: false, backend: null, model: null, provider: null },
    },
    hfToken: '',
    licenseAccepted: false,
  })

  const pull = reactive({
    started: false,
    items: [],
    done: false,
  })

  async function load() {
    loading.value = true
    try {
      const [hw, st, cur, caps, auth] = await Promise.all([
        api('/api/hardware').catch(() => null),
        api('/api/install/state').catch(() => ({ first_run: true })),
        api('/api/install/curated-models').catch(() => ({ models: [], custom_allowed: false })),
        api('/api/capabilities').catch(() => ({ backends: [], catalogs: {}, selections: {} })),
        api('/api/auth/status').catch(() => ({ password_set: false })),
      ])
      hardware.value = hw
      firstRun.value = !!st?.first_run
      curated.value = cur?.models || []
      customAllowed.value = !!cur?.custom_allowed
      capsData.value = caps
      form.passwordAlreadySet = !!auth?.password_set

      if (firstRun.value) {
        applySmartDefaults()
      } else {
        hydrateFromSelections()
      }
    } catch (e) {
      error.value = e?.message ?? String(e)
    } finally {
      loading.value = false
    }
  }

  function applySmartDefaults() {
    const hw = hardware.value || {}
    const tier = pickBackend(hw)
    const e = SMART_DEFAULTS.embed[tier] || SMART_DEFAULTS.embed.cpu
    form.caps.embed = { ...form.caps.embed, ...e }
    form.caps.rerank.enabled = SMART_DEFAULTS.rerank.enabled
    const s = tier === 'npu' ? SMART_DEFAULTS.stt.npu : SMART_DEFAULTS.stt.other
    form.caps.stt = { ...form.caps.stt, ...s }
    form.caps.tts.enabled = SMART_DEFAULTS.tts.enabled
    form.caps.img.enabled = SMART_DEFAULTS.img.enabled
    pickFirstAvailableModels()
  }

  function pickFirstAvailableModels() {
    const cats = capsData.value?.catalogs || {}
    const guess = (slot, child) => {
      const opts = cats?.[slot]?.[child] || []
      return opts[0] || null
    }
    if (!form.caps.embed.model) {
      const o = guess('embed', 'embed')
      if (o) Object.assign(form.caps.embed, { model: o.id, backend: o.backend, provider: o.provider })
    }
    if (!form.caps.rerank.model) {
      const o = guess('embed', 'rerank')
      if (o) Object.assign(form.caps.rerank, { model: o.id, backend: o.backend, provider: o.provider })
    }
    if (!form.caps.stt.model) {
      const o = guess('voice', 'stt')
      if (o) Object.assign(form.caps.stt, { model: o.id, backend: o.backend, provider: o.provider })
    }
    if (!form.caps.tts.model) {
      const o = guess('voice', 'tts')
      if (o) Object.assign(form.caps.tts, { model: o.id, backend: o.backend, provider: o.provider })
    }
    if (!form.caps.img.model) {
      const o = guess('img', 'img')
      if (o) Object.assign(form.caps.img, { model: o.id, backend: o.backend, provider: o.provider })
    }
  }

  function hydrateFromSelections() {
    const s = capsData.value?.selections || {}
    const get = (slot, child) => s?.[slot]?.[child] || {}
    const map = [
      ['embed',  ['embed',  'embed']],
      ['rerank', ['embed',  'rerank']],
      ['stt',    ['voice',  'stt']],
      ['tts',    ['voice',  'tts']],
      ['img',    ['img',    'img']],
    ]
    for (const [key, [slot, child]] of map) {
      const sel = get(slot, child)
      form.caps[key] = {
        enabled: !!sel.enabled,
        backend: sel.backend ?? null,
        model:   sel.model   ?? null,
        provider: sel.provider ?? null,
      }
    }
    pickFirstAvailableModels()
  }

  const optionsFor = (slot, child) => capsData.value?.catalogs?.[slot]?.[child] || []

  function setCapModel(key, slot, child, key2) {
    const opts = optionsFor(slot, child)
    const opt = opts.find((o) => `${o.backend}::${o.id}` === key2)
    if (opt) Object.assign(form.caps[key], { backend: opt.backend, model: opt.id, provider: opt.provider })
  }

  const sizeFor = (key, slot, child) => {
    const o = optionsFor(slot, child).find((x) => x.id === form.caps[key].model && x.backend === form.caps[key].backend)
    return o?.size_gb ?? 0
  }

  const primaryModel = computed(() => {
    if (form.primaryCustom) return form.primaryCustom
    return curated.value.find((m) => m.id === form.primaryId) || null
  })

  const totalDownloadGb = computed(() => {
    let total = primaryModel.value?.size_gb || 0
    if (form.caps.embed.enabled)  total += sizeFor('embed',  'embed', 'embed')
    if (form.caps.rerank.enabled) total += sizeFor('rerank', 'embed', 'rerank')
    if (form.caps.stt.enabled)    total += sizeFor('stt',    'voice', 'stt')
    if (form.caps.tts.enabled)    total += sizeFor('tts',    'voice', 'tts')
    if (form.caps.img.enabled)    total += sizeFor('img',    'img',   'img')
    return total
  })

  const diskFreeGb = computed(() => (hardware.value?.disk_free_mb || 0) / 1024)
  const fits = computed(() => totalDownloadGb.value <= diskFreeGb.value)

  const gatedModels = computed(() => {
    const out = []
    if (primaryModel.value?.gated || /llama|whisper-v3/i.test(primaryModel.value?.id || '')) {
      out.push(primaryModel.value)
    }
    return out
  })

  const enabledList = computed(() => {
    const list = []
    if (primaryModel.value) list.push({ kind: 'primary', label: primaryModel.value.display_name, size_gb: primaryModel.value.size_gb })
    if (form.caps.embed.enabled)  list.push({ kind: 'embed',  label: `embed → ${form.caps.embed.model}`,   size_gb: sizeFor('embed',  'embed', 'embed') })
    if (form.caps.rerank.enabled) list.push({ kind: 'rerank', label: `rerank → ${form.caps.rerank.model}`, size_gb: sizeFor('rerank', 'embed', 'rerank') })
    if (form.caps.stt.enabled)    list.push({ kind: 'stt',    label: `stt → ${form.caps.stt.model}`,       size_gb: sizeFor('stt',    'voice', 'stt') })
    if (form.caps.tts.enabled)    list.push({ kind: 'tts',    label: `tts → ${form.caps.tts.model}`,       size_gb: sizeFor('tts',    'voice', 'tts') })
    if (form.caps.img.enabled)    list.push({ kind: 'img',    label: `img → ${form.caps.img.model}`,       size_gb: sizeFor('img',    'img',   'img') })
    return list
  })

  async function applyAll() {
    pull.started = true
    pull.done = false
    pull.items = enabledList.value.map((x) => ({ ...x, pct: 0 }))
    for (let pct = 0; pct <= 100; pct += 10) {
      await new Promise((r) => setTimeout(r, 220))
      pull.items.forEach((it) => { it.pct = Math.min(100, pct + Math.floor(Math.random() * 10)) })
    }
    pull.items.forEach((it) => { it.pct = 100 })
    pull.done = true
  }

  _state = {
    loading, error, firstRun,
    hardware, curated, customAllowed, capsData,
    form, pull,
    primaryModel, totalDownloadGb, diskFreeGb, fits, gatedModels, enabledList,
    load, applyAll, optionsFor, setCapModel, sizeFor,
    pickBackend,
  }
  load()
  return _state
}
