<script setup>
/**
 * Models.vue
 *
 * Design decisions:
 * - Table layout > cards. Models have many attributes; a dense table lets you
 *   scan all of them without scrolling. Card-per-model requires too many clicks.
 * - Pull flow: a "Pull model" button opens a modal with (a) curated presets and
 *   (b) a raw HF URL input. Curated list shows size + VRAM requirements.
 * - Delete confirmation warns how many slots depend on the model ("3 slots use
 *   this model — they will be unassigned"). Impact > 1 requires typing the model
 *   name to prevent accidents.
 * - Slot assignment column shows which slot is using each model inline, with a
 *   quick "Assign to" dropdown — no page navigation required.
 * - `n` to open Pull form, `/` to focus search.
 */
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { useSystemStore } from '../stores/system.js'
import { useToastsStore } from '../stores/toasts.js'
import { api } from '../composables/useApi.js'
import { usePullJob, fmtBytes, fmtSpeed, fmtEta } from '../composables/usePullJob.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import EmptyState from '../components/EmptyState.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const system = useSystemStore()
const toasts = useToastsStore()

// ── State ──────────────────────────────────────────────────────────────
const models   = ref([])
const loading  = ref(true)
const error    = ref(null)
const search   = ref('')
const searchEl = ref(null)

// Pull model modal
const showPull   = ref(false)
const pullTab    = ref('curated')   // 'curated' | 'hf' | 'manual'
const pullForm   = ref({ hf_url: '', name: '', quant: 'Q4_K_M' })
const pullErrors = ref({})
const pulling    = ref(false)

// Per-model active pull jobs. Each row that goes into a "downloading"
// substate gets its own usePullJob instance so multiple pulls can run
// in parallel and the inline progress bars are independent (Team I
// gap #3).
const pullJobs = reactive({})  // { [modelId]: usePullJob() }

function ensureJob(modelId) {
  if (!pullJobs[modelId]) {
    pullJobs[modelId] = usePullJob()
  }
  return pullJobs[modelId]
}

function jobFor(modelId) {
  return pullJobs[modelId] ?? null
}

// Curated presets (shown in pull modal)
const CURATED = [
  { id: 'qwen3-4b',    name: 'Qwen3 4B',    size_gb: 4.1,  license: 'Apache 2.0', desc: 'Fast, multilingual, vision-capable' },
  { id: 'llama32-3b',  name: 'Llama 3.2 3B', size_gb: 2.0, license: 'Llama',      desc: 'General purpose, small' },
  { id: 'phi3-mini',   name: 'Phi-3 Mini',   size_gb: 2.4, license: 'MIT',        desc: 'Efficient reasoning' },
]

// Edit metadata
const editingModel   = ref(null)
const editForm       = ref({ name: '' })
const editSubmitting = ref(false)

// Delete confirm
const deletingModel = ref(null)
const deleting      = ref(false)

// ── Loaders ────────────────────────────────────────────────────────────
async function loadModels() {
  loading.value = true
  error.value = null
  try {
    const data = await api('/api/models')
    models.value = Array.isArray(data) ? data : (data?.models ?? [])
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// ── Filtering ──────────────────────────────────────────────────────────
const filteredModels = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return models.value
  return models.value.filter(
    (m) => (m.name ?? m.id ?? '').toLowerCase().includes(q) ||
            (m.architecture ?? '').toLowerCase().includes(q)
  )
})

// ── Slot assignment helpers ────────────────────────────────────────────
function slotsForModel(modelId) {
  return system.slots.filter((s) => s.model === modelId)
}

// ── Pull model ─────────────────────────────────────────────────────────
async function pullCurated(preset) {
  pulling.value = true
  const job = ensureJob(preset.id)
  try {
    await job.start(preset.id)
    toasts.success(`Pulling "${preset.name}" — progress shown inline`)
    showPull.value = false
    // Make sure the row exists so the user can watch progress. The
    // backend will register the model in its registry; until then we
    // optimistically insert a placeholder row.
    if (!models.value.some((m) => m.id === preset.id)) {
      models.value = [
        ...models.value,
        { id: preset.id, name: preset.name, size_gb: preset.size_gb, _pending: true },
      ]
    }
  } catch (e) {
    toasts.error(e.message)
  } finally {
    pulling.value = false
  }
}

function validatePullHF() {
  const errs = {}
  if (!pullForm.value.hf_url.trim()) errs.hf_url = 'Required'
  else if (!pullForm.value.hf_url.includes('/')) errs.hf_url = 'Enter a HuggingFace repo path (org/model)'
  pullErrors.value = errs
  return Object.keys(errs).length === 0
}

async function submitPullHF() {
  if (!validatePullHF()) return
  pulling.value = true
  const id = pullForm.value.hf_url
  const job = ensureJob(id)
  try {
    await job.start(id, { hf_url: pullForm.value.hf_url, quant: pullForm.value.quant })
    toasts.success('Download started')
    showPull.value = false
    if (!models.value.some((m) => m.id === id)) {
      models.value = [
        ...models.value,
        { id, name: id, _pending: true },
      ]
    }
    pullForm.value = { hf_url: '', name: '', quant: 'Q4_K_M' }
  } catch (e) {
    toasts.error(e.message)
  } finally {
    pulling.value = false
  }
}

async function cancelPull(modelId) {
  const job = jobFor(modelId)
  if (!job) return
  try {
    await job.cancel()
    toasts.success(`Cancelled download for "${modelId}"`)
  } catch (e) {
    toasts.error(e.message)
  }
}

/**
 * On mount, ask the backend whether any of the rows we just loaded
 * have an in-flight pull job. If so, reattach so the SSE progress bar
 * picks up where the user left off when they navigated away. Soft-
 * fails per model so a 404 on one doesn't block the rest.
 */
async function reattachInFlightPulls() {
  for (const m of models.value) {
    if (!m?.id) continue
    const job = ensureJob(m.id)
    await job.reattach(m.id)
    // If the reattach didn't find an in-flight job, drop the entry so we
    // don't leak empty job state into the row template.
    if (!job.inFlight.value && !job.terminal.value) {
      delete pullJobs[m.id]
    }
  }
}

// ── Edit metadata ──────────────────────────────────────────────────────
function openEdit(model) {
  editingModel.value = model
  editForm.value = { name: model.name ?? model.id ?? '' }
}

async function submitEdit() {
  if (!editingModel.value) return
  editSubmitting.value = true
  try {
    await api(`/api/models/${encodeURIComponent(editingModel.value.id)}`, {
      method: 'PUT',
      body: JSON.stringify({ name: editForm.value.name }),
    })
    toasts.success('Model updated')
    editingModel.value = null
    await loadModels()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    editSubmitting.value = false
  }
}

// ── Delete model ───────────────────────────────────────────────────────
const deletingModelSlots = computed(() => {
  if (!deletingModel.value) return []
  return slotsForModel(deletingModel.value.id)
})

async function confirmDelete() {
  if (!deletingModel.value) return
  deleting.value = true
  try {
    await api(`/api/models/${encodeURIComponent(deletingModel.value.id)}`, { method: 'DELETE' })
    toasts.success(`Deleted model "${deletingModel.value.name ?? deletingModel.value.id}"`)
    deletingModel.value = null
    await loadModels()
    await system.fetchStatus()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    deleting.value = false
  }
}

// ── Assign to slot ─────────────────────────────────────────────────────
async function assignToSlot(model, slotName) {
  if (!slotName) return
  try {
    await api(`/api/slots/${slotName}/load`, {
      method: 'POST',
      body: JSON.stringify({ model: model.id }),
    })
    toasts.success(`Loading "${model.name ?? model.id}" into "${slotName}"`)
    await system.fetchStatus()
  } catch (e) {
    toasts.error(e.message)
  }
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────
function handleKey(e) {
  if ((e.target instanceof HTMLInputElement) || (e.target instanceof HTMLTextAreaElement)) return
  if (e.key === 'n') { e.preventDefault(); showPull.value = true }
  else if (e.key === '/') { e.preventDefault(); searchEl.value?.focus() }
  else if (e.key === 'Escape') {
    if (showPull.value) showPull.value = false
    else if (editingModel.value) editingModel.value = null
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleKey)
  await loadModels()
  // Reattach any in-flight pull jobs so the user sees live progress
  // even if they navigated away mid-download (Team I gap #3).
  await reattachInFlightPulls()
})
onUnmounted(() => {
  window.removeEventListener('keydown', handleKey)
  // Active EventSource cleanup is handled by each usePullJob's onUnmounted.
})

// ── Formatting ─────────────────────────────────────────────────────────
function fmtSize(model) {
  if (model.size_gb != null) return `${Number(model.size_gb).toFixed(1)} GB`
  if (model.size_bytes != null) return `${(model.size_bytes / 1e9).toFixed(1)} GB`
  return '—'
}

const QUANTS = ['Q4_K_M', 'Q5_K_M', 'Q8_0', 'F16', 'BF16']
</script>

<template>
  <div class="models-page">
    <PageHeader eyebrow="Registry" title="Models" subtitle="Local model registry and downloads">
      <template #actions>
        <div class="search-wrap">
          <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" class="search-icon" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M10.5 18a7.5 7.5 0 100-15 7.5 7.5 0 000 15z"/>
          </svg>
          <input
            ref="searchEl"
            v-model="search"
            class="search-input"
            type="search"
            placeholder="Search models… (/)"
            aria-label="Search models"
          />
        </div>
        <button class="btn-primary" type="button" @click="showPull = true">
          <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
          </svg>
          Pull model
        </button>
      </template>
    </PageHeader>

    <div class="page-body">
      <!-- ── Error ──────────────────────────────────────────── -->
      <div v-if="error" class="error-banner" role="alert">
        <span>{{ error }}</span>
        <button type="button" class="btn-link" @click="loadModels">Retry</button>
      </div>

      <!-- ── Loading ────────────────────────────────────────── -->
      <template v-if="loading">
        <Card v-for="i in 5" :key="i"><LoadingSkeleton :lines="2" /></Card>
      </template>

      <!-- ── Empty ──────────────────────────────────────────── -->
      <template v-else-if="models.length === 0">
        <Card :padded="false">
          <EmptyState
            icon="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
            title="No models in registry"
            description="Pull a model from Hugging Face or select from curated options to get started."
            cta-label="Pull a model"
            @cta="showPull = true"
          />
        </Card>
      </template>

      <!-- ── Models table ──────────────────────────────────── -->
      <template v-else>
        <div v-if="filteredModels.length === 0" class="no-results">
          No models match "{{ search }}"
        </div>

        <Card :padded="false" v-else>
          <div class="table-wrap" role="region" aria-label="Models table" tabindex="0">
            <table class="models-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Size</th>
                  <th scope="col">Quant</th>
                  <th scope="col">Architecture</th>
                  <th scope="col">Used by</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="model in filteredModels" :key="model.id">
                  <td>
                    <div class="model-name-cell">
                      <span class="model-name">{{ model.name ?? model.id }}</span>
                      <span v-if="model.name && model.id !== model.name" class="model-id">{{ model.id }}</span>
                      <!-- Inline pull progress: rendered when a row has an
                           active or recently-terminated pull job. SSE-driven;
                           updates instantly as bytes land. -->
                      <div
                        v-if="jobFor(model.id) && (jobFor(model.id).inFlight.value || jobFor(model.id).state.value === 'failed')"
                        class="row-pull"
                        role="status"
                        :aria-label="`Downloading ${model.name ?? model.id}`"
                      >
                        <div class="row-pull-bar" :aria-valuenow="jobFor(model.id).pct.value ?? 0" aria-valuemin="0" aria-valuemax="100" role="progressbar">
                          <div class="row-pull-fill" :style="{ width: (jobFor(model.id).pct.value ?? 0) + '%' }" />
                        </div>
                        <div class="row-pull-meta mono">
                          <span v-if="jobFor(model.id).state.value === 'failed'" class="row-pull-err">
                            <strong>{{ jobFor(model.id).error.value?.code }}</strong>:
                            {{ jobFor(model.id).error.value?.message }}
                          </span>
                          <template v-else>
                            <span>{{ jobFor(model.id).pct.value ?? 0 }}%</span>
                            <span v-if="jobFor(model.id).total.value">
                              · {{ fmtBytes(jobFor(model.id).downloaded.value) }} / {{ fmtBytes(jobFor(model.id).total.value) }}
                            </span>
                            <span v-if="jobFor(model.id).speedBps.value">· {{ fmtSpeed(jobFor(model.id).speedBps.value) }}</span>
                            <span v-if="jobFor(model.id).etaS.value">· {{ fmtEta(jobFor(model.id).etaS.value) }}</span>
                            <button
                              v-if="jobFor(model.id).inFlight.value"
                              type="button"
                              class="row-pull-cancel"
                              @click="cancelPull(model.id)"
                              :aria-label="`Cancel download for ${model.name ?? model.id}`"
                            >Cancel</button>
                          </template>
                        </div>
                      </div>
                    </div>
                  </td>
                  <td class="mono-cell">{{ fmtSize(model) }}</td>
                  <td class="mono-cell">{{ model.quant ?? '—' }}</td>
                  <td class="mono-cell">{{ model.architecture ?? '—' }}</td>
                  <td>
                    <div class="slots-cell">
                      <template v-if="slotsForModel(model.id).length > 0">
                        <span
                          v-for="s in slotsForModel(model.id)"
                          :key="s.name"
                          class="slot-badge"
                          :class="s.status === 'running' ? 'badge-running' : ''"
                        >{{ s.name }}</span>
                      </template>
                      <span v-else class="text-faint">—</span>
                    </div>
                  </td>
                  <td>
                    <div class="row-actions">
                      <!-- Assign to slot -->
                      <select
                        class="assign-select"
                        @change="(e) => { assignToSlot(model, e.target.value); e.target.value = '' }"
                        :aria-label="`Assign ${model.name ?? model.id} to slot`"
                      >
                        <option value="">Assign…</option>
                        <option v-for="s in system.slots" :key="s.name" :value="s.name">{{ s.name }}</option>
                      </select>

                      <!-- Edit name -->
                      <button
                        class="act-btn"
                        type="button"
                        @click="openEdit(model)"
                        :aria-label="`Edit ${model.name ?? model.id}`"
                        title="Edit metadata"
                      >
                        <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5" aria-hidden="true">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                        </svg>
                      </button>

                      <!-- Delete -->
                      <button
                        class="act-btn act-danger"
                        type="button"
                        @click="deletingModel = model"
                        :aria-label="`Delete ${model.name ?? model.id}`"
                        title="Delete model"
                      >
                        <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5" aria-hidden="true">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      </template>
    </div>

    <!-- ── Pull model modal ──────────────────────────────────────── -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showPull" class="modal-overlay" @click.self="showPull = false">
          <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="pull-title">
            <div class="modal-header">
              <h2 id="pull-title" class="modal-title">Pull model</h2>
              <button class="modal-close" type="button" @click="showPull = false" aria-label="Close">
                <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>

            <!-- Tab bar -->
            <div class="pull-tabs" role="tablist">
              <button role="tab" :aria-selected="pullTab === 'curated'" class="pull-tab" :class="{ active: pullTab === 'curated' }" @click="pullTab = 'curated'">Curated</button>
              <button role="tab" :aria-selected="pullTab === 'hf'" class="pull-tab" :class="{ active: pullTab === 'hf' }" @click="pullTab = 'hf'">HuggingFace</button>
            </div>

            <div class="modal-body">
              <!-- Curated tab -->
              <div v-if="pullTab === 'curated'" class="curated-list" role="tabpanel">
                <div
                  v-for="preset in CURATED"
                  :key="preset.id"
                  class="curated-row"
                >
                  <div class="curated-info">
                    <span class="curated-name">{{ preset.name }}</span>
                    <span class="curated-desc">{{ preset.desc }}</span>
                  </div>
                  <div class="curated-meta">
                    <span class="mono-chip">{{ preset.size_gb }} GB</span>
                    <span class="mono-chip">{{ preset.license }}</span>
                  </div>
                  <button
                    class="btn-sm-accent"
                    type="button"
                    :disabled="pulling"
                    @click="pullCurated(preset)"
                  >
                    <span v-if="jobFor(preset.id)?.inFlight.value" class="spinner" aria-hidden="true" />
                    {{ jobFor(preset.id)?.inFlight.value ? 'Pulling…' : 'Pull' }}
                  </button>
                </div>
              </div>

              <!-- HuggingFace tab -->
              <div v-if="pullTab === 'hf'" role="tabpanel">
                <div class="field">
                  <label class="field-label" for="hf-url">HuggingFace repo <span class="req">*</span></label>
                  <input
                    id="hf-url"
                    v-model="pullForm.hf_url"
                    class="field-input"
                    :class="{ 'field-error': pullErrors.hf_url }"
                    placeholder="org/model-name-GGUF"
                    autocomplete="off"
                  />
                  <p v-if="pullErrors.hf_url" class="field-err">{{ pullErrors.hf_url }}</p>
                  <p class="field-hint">e.g. Qwen/Qwen3-4B-GGUF or bartowski/Meta-Llama-3-8B-Instruct-GGUF</p>
                </div>
                <div class="field">
                  <label class="field-label" for="quant">Quantization</label>
                  <select id="quant" v-model="pullForm.quant" class="field-input">
                    <option v-for="q in QUANTS" :key="q" :value="q">{{ q }}</option>
                  </select>
                </div>
              </div>
            </div>

            <div class="modal-footer" v-if="pullTab === 'hf'">
              <button class="btn-ghost" type="button" @click="showPull = false" :disabled="pulling">Cancel</button>
              <button class="btn-primary" type="button" @click="submitPullHF" :disabled="pulling">
                <span v-if="pulling" class="spinner" aria-hidden="true" />
                {{ pulling ? 'Pulling…' : 'Pull model' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ── Edit model modal ──────────────────────────────────────── -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="editingModel" class="modal-overlay" @click.self="editingModel = null">
          <div class="modal-box modal-sm" role="dialog" aria-modal="true" aria-labelledby="edit-model-title">
            <div class="modal-header">
              <h2 id="edit-model-title" class="modal-title">Edit model</h2>
              <button class="modal-close" type="button" @click="editingModel = null" aria-label="Close">
                <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="modal-body">
              <div class="field">
                <label class="field-label" for="edit-model-name">Display name</label>
                <input id="edit-model-name" v-model="editForm.name" class="field-input" placeholder="Human-readable name" />
              </div>
              <p class="field-hint mono-text">ID: {{ editingModel.id }}</p>
            </div>
            <div class="modal-footer">
              <button class="btn-ghost" type="button" @click="editingModel = null" :disabled="editSubmitting">Cancel</button>
              <button class="btn-primary" type="button" @click="submitEdit" :disabled="editSubmitting">
                <span v-if="editSubmitting" class="spinner" aria-hidden="true" />
                {{ editSubmitting ? 'Saving…' : 'Save' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ── Delete confirm ────────────────────────────────────────── -->
    <ConfirmDialog
      :open="!!deletingModel"
      :title="`Delete &quot;${deletingModel?.name ?? deletingModel?.id ?? ''}&quot;?`"
      :message="deletingModelSlots.length > 0
        ? `${deletingModelSlots.length} slot(s) use this model and will be unassigned. The model files on disk will be removed.`
        : 'The model files on disk will be permanently removed.'"
      danger
      confirm-label="Delete model"
      :impact="deletingModelSlots.length > 1 ? 2 : 1"
      :confirm-text="deletingModelSlots.length > 1 ? (deletingModel?.name ?? deletingModel?.id ?? '') : ''"
      :loading="deleting"
      @update:open="(v) => { if (!v) deletingModel = null }"
      @confirm="confirmDelete"
      @cancel="deletingModel = null"
    />
  </div>
</template>

<style scoped>
.models-page { display: flex; flex-direction: column; min-height: 100%; }
.page-body   { padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; }

/* Search */
.search-wrap { position: relative; }
.search-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--color-fg-faint); pointer-events: none; }
.search-input {
  padding: 6px 10px 6px 30px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-fg);
  font-size: 12.5px;
  outline: none;
  width: 220px;
  transition: border-color 0.1s, width 0.2s;
}
.search-input:focus { border-color: var(--color-border-hi); width: 280px; }
.search-input::placeholder { color: var(--color-fg-faint); }

/* Error */
.error-banner {
  display: flex; align-items: center; gap: 12px; justify-content: space-between;
  padding: 10px 16px;
  background: color-mix(in oklch, var(--color-danger) 10%, var(--color-surface));
  border: 1px solid color-mix(in oklch, var(--color-danger) 30%, transparent);
  border-radius: var(--radius-lg);
  color: var(--color-danger);
  font-size: 13px;
}

.no-results { padding: 32px; text-align: center; color: var(--color-fg-faint); font-size: 13px; }

/* ── Table ────────────────────────────────────────────────────── */
.table-wrap { overflow-x: auto; }
.models-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.models-table thead { background: var(--hal0-bg-sunken); }
.models-table th {
  padding: 10px 16px;
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--hal0-accent);
  font-family: var(--font-mono);
  border-bottom: 1px solid var(--color-border);
  font-weight: 500;
  white-space: nowrap;
}
.models-table td {
  padding: 11px 16px;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-fg-muted);
  vertical-align: middle;
}
.models-table tbody tr:last-child td { border-bottom: none; }
.models-table tbody tr:hover td { background: var(--color-surface-2); }

.model-name-cell { display: flex; flex-direction: column; gap: 2px; }
.model-name { font-family: var(--font-mono); font-weight: 600; color: var(--color-fg); }
.model-id   { font-family: var(--font-mono); font-size: 10.5px; color: var(--color-fg-faint); }
.mono-cell  { font-family: var(--font-mono); font-size: 11.5px; font-feature-settings: 'zero' 1, 'ss02' 1, 'tnum' 1; }

/* Inline pull progress (Team I gap #3) */
.row-pull { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.row-pull-bar {
  position: relative;
  width: 100%;
  max-width: 320px;
  height: 4px;
  background: var(--color-surface-3);
  border-radius: 4px;
  overflow: hidden;
}
.row-pull-fill {
  height: 100%;
  background: var(--color-accent);
  border-radius: 4px;
  transition: width 0.3s ease;
}
.row-pull-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  color: var(--color-fg-faint);
  flex-wrap: wrap;
}
.row-pull-cancel {
  margin-left: auto;
  padding: 1px 8px;
  border-radius: 4px;
  border: 1px solid color-mix(in oklch, var(--color-danger) 30%, transparent);
  background: transparent;
  color: var(--color-danger);
  font-size: 10.5px;
  cursor: pointer;
  font-family: inherit;
}
.row-pull-cancel:hover { background: color-mix(in oklch, var(--color-danger) 10%, transparent); }
.row-pull-err { color: var(--color-danger); }
.row-pull-err strong { font-family: var(--font-mono); }

/* Slots cell */
.slots-cell { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.slot-badge {
  font-family: var(--font-mono); font-size: 10px;
  padding: 2px 6px; border-radius: 4px;
  background: var(--color-surface-2); border: 1px solid var(--color-border);
  color: var(--color-fg-faint);
}
.slot-badge.badge-running { background: color-mix(in srgb, var(--hal0-accent) 12%, transparent); border-color: color-mix(in srgb, var(--hal0-accent) 35%, transparent); color: var(--hal0-accent); }
.text-faint { color: var(--color-fg-faint); }

/* Row actions */
.row-actions { display: flex; align-items: center; gap: 6px; }
.assign-select {
  padding: 4px 7px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-fg-muted);
  font-size: 11.5px;
  cursor: pointer;
  max-width: 140px;
}
.assign-select:focus { outline: none; border-color: var(--color-border-hi); }

.act-btn {
  width: 28px; height: 28px;
  display: grid; place-items: center;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-fg-faint);
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
  flex-shrink: 0;
}
.act-btn:hover { background: var(--color-surface-2); color: var(--color-fg); }
.act-danger:hover { background: color-mix(in oklch, var(--color-danger) 12%, transparent); color: var(--color-danger); border-color: color-mix(in oklch, var(--color-danger) 30%, transparent); }

/* Pull modal tabs */
.pull-tabs { display: flex; border-bottom: 1px solid var(--color-border); padding: 0 20px; }
.pull-tab {
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-fg-faint);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  margin-bottom: -1px;
  transition: color 0.1s, border-color 0.1s;
}
.pull-tab:hover { color: var(--color-fg-muted); }
.pull-tab.active { color: var(--hal0-accent); border-bottom-color: var(--hal0-accent); }

/* Curated list */
.curated-list { display: flex; flex-direction: column; gap: 8px; }
.curated-row {
  display: flex; align-items: center; gap: 12px;
  padding: 12px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
}
.curated-info { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.curated-name { font-size: 13px; font-weight: 600; color: var(--color-fg); }
.curated-desc { font-size: 11.5px; color: var(--color-fg-faint); }
.curated-meta { display: flex; gap: 6px; flex-shrink: 0; }
.mono-chip {
  font-family: var(--font-mono); font-size: 10.5px;
  padding: 2px 7px; border-radius: 4px;
  background: var(--color-surface-3); border: 1px solid var(--color-border);
  color: var(--color-fg-faint);
}
.btn-sm-accent {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 12px; border-radius: var(--radius);
  background: var(--hal0-accent); color: #000;
  font-family: var(--font-mono);
  font-size: 11.5px; font-weight: 500; border: none; cursor: pointer;
  flex-shrink: 0; transition: background 0.15s;
}
.btn-sm-accent:hover:not(:disabled) { background: var(--hal0-accent-hover); }
.btn-sm-accent:disabled { opacity: 0.45; cursor: not-allowed; }

/* Shared */
.modal-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; padding: 16px; }
.modal-box { background: var(--color-surface); border: 1px solid var(--color-border-hi); border-radius: var(--radius-xl); width: min(540px, 100%); max-height: 90vh; display: flex; flex-direction: column; box-shadow: 0 24px 64px rgba(0,0,0,0.6); overflow: hidden; }
.modal-sm { width: min(380px, 100%); }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--color-border); }
.modal-title { font-size: 15px; font-weight: 600; color: var(--color-fg); margin: 0; }
.modal-close { width: 28px; height: 28px; border-radius: var(--radius); background: transparent; border: 1px solid transparent; color: var(--color-fg-faint); cursor: pointer; display: grid; place-items: center; }
.modal-close:hover { background: var(--color-surface-2); color: var(--color-fg); }
.modal-body { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; flex: 1; }
.modal-footer { padding: 16px 20px; border-top: 1px solid var(--color-border); display: flex; justify-content: flex-end; gap: 8px; }

.field { display: flex; flex-direction: column; gap: 5px; }
.field-label { font-size: 12.5px; font-weight: 600; color: var(--color-fg-muted); }
.req { color: var(--color-danger); }
.field-input { padding: 7px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg); font-size: 13px; outline: none; transition: border-color 0.1s; box-sizing: border-box; width: 100%; }
.field-input:focus { border-color: var(--color-border-hi); }
.field-error { border-color: var(--color-danger) !important; }
.field-err  { font-size: 11.5px; color: var(--color-danger); margin: 0; }
.field-hint { font-size: 11.5px; color: var(--color-fg-faint); margin: 0; }
.mono-text  { font-family: var(--font-mono); }

.btn-primary { display: flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: var(--radius); background: var(--hal0-accent); color: #000; font-family: var(--font-mono); font-size: 12px; font-weight: 500; border: none; cursor: pointer; transition: background 0.15s; }
.btn-primary:hover:not(:disabled) { background: var(--hal0-accent-hover); }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-ghost { padding: 7px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-family: var(--font-mono); font-size: 12px; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
.btn-ghost:hover:not(:disabled) { border-color: var(--color-border-hi); color: var(--color-fg); }
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-link { background: transparent; border: none; color: var(--hal0-accent); font-size: 13px; cursor: pointer; }
.btn-link:hover { text-decoration: underline; }

.spinner { width: 11px; height: 11px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }

.fade-enter-active, .fade-leave-active { transition: opacity 0.12s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
