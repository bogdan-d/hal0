<script setup>
/**
 * Providers.vue — External upstream LLM providers.
 * Shows configured upstreams (OpenRouter, Anthropic, OpenAI, custom)
 * with status dot (online/offline from /api/providers/test), API key
 * entry, enable/disable toggle, and delete. Add provider modal opens
 * from the header.
 */
import { ref, onMounted } from 'vue'
import { useToastsStore } from '../stores/toasts.js'
import { api } from '../composables/useApi.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import EmptyState from '../components/EmptyState.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const toasts = useToastsStore()

const providers = ref([])
const loading   = ref(true)
const error     = ref(null)

const showAdd    = ref(false)
const addForm    = ref({ type: 'openrouter', name: '', api_key: '', base_url: '' })
const addErrors  = ref({})
const adding     = ref(false)

const testResults = ref({})  // { [id]: 'ok' | 'error' | 'testing' }
const deletingId  = ref(null)
const deleting    = ref(false)

const PROVIDER_TYPES = [
  { id: 'openrouter', label: 'OpenRouter',     url: 'https://openrouter.ai/api/v1' },
  { id: 'openai',     label: 'OpenAI',          url: 'https://api.openai.com/v1' },
  { id: 'anthropic',  label: 'Anthropic',       url: 'https://api.anthropic.com' },
  { id: 'custom',     label: 'Custom OpenAI-compatible', url: '' },
]

async function loadProviders() {
  loading.value = true
  error.value = null
  try {
    const data = await api('/api/providers')
    providers.value = Array.isArray(data) ? data : (data?.providers ?? [])
  } catch (e) {
    error.value = e.message
    providers.value = []
  } finally {
    loading.value = false
  }
}

function validateAdd() {
  const errs = {}
  if (!addForm.value.name.trim()) errs.name = 'Required'
  if (!addForm.value.api_key.trim()) errs.api_key = 'Required'
  if (addForm.value.type === 'custom' && !addForm.value.base_url.trim()) {
    errs.base_url = 'Required for custom providers'
  }
  addErrors.value = errs
  return Object.keys(errs).length === 0
}

function onTypeChange() {
  const preset = PROVIDER_TYPES.find((t) => t.id === addForm.value.type)
  if (preset?.url) addForm.value.base_url = preset.url
}

async function submitAdd() {
  if (!validateAdd()) return
  adding.value = true
  try {
    const body = {
      type:    addForm.value.type,
      name:    addForm.value.name,
      api_key: addForm.value.api_key,
    }
    if (addForm.value.base_url) body.base_url = addForm.value.base_url
    await api('/api/providers', { method: 'POST', body: JSON.stringify(body) })
    toasts.success(`Provider "${addForm.value.name}" added`)
    showAdd.value = false
    addForm.value = { type: 'openrouter', name: '', api_key: '', base_url: '' }
    addErrors.value = {}
    await loadProviders()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    adding.value = false
  }
}

async function testProvider(provider) {
  testResults.value[provider.id] = 'testing'
  try {
    const data = await api(`/api/providers/${provider.id}/test`, { method: 'POST' })
    testResults.value[provider.id] = data?.ok ? 'ok' : 'error'
    if (data?.ok) toasts.success(`"${provider.name}" is reachable`)
    else toasts.error(`"${provider.name}" test failed: ${data?.error ?? 'unknown'}`)
  } catch (e) {
    testResults.value[provider.id] = 'error'
    toasts.error(e.message)
  }
}

async function toggleEnabled(provider) {
  try {
    await api(`/api/providers/${provider.id}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled: !provider.enabled }),
    })
    provider.enabled = !provider.enabled
    toasts.success(`"${provider.name}" ${provider.enabled ? 'enabled' : 'disabled'}`)
  } catch (e) {
    toasts.error(e.message)
  }
}

async function confirmDelete() {
  if (!deletingId.value) return
  deleting.value = true
  try {
    await api(`/api/providers/${deletingId.value}`, { method: 'DELETE' })
    toasts.success('Provider removed')
    deletingId.value = null
    await loadProviders()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    deleting.value = false
  }
}

const testStatusColor = { ok: 'var(--color-success)', error: 'var(--color-danger)', testing: 'var(--color-warning)' }

onMounted(loadProviders)
</script>

<template>
  <div class="providers-page">
    <PageHeader title="Providers" subtitle="External LLM upstreams (OpenRouter, Anthropic, OpenAI, custom)">
      <template #actions>
        <button class="btn-primary" type="button" @click="showAdd = true">
          <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
          Add provider
        </button>
      </template>
    </PageHeader>

    <div class="page-body">
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>

      <template v-if="loading">
        <Card v-for="i in 3" :key="i"><LoadingSkeleton :lines="2" /></Card>
      </template>

      <template v-else-if="providers.length === 0">
        <Card :padded="false">
          <EmptyState
            icon="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"
            title="No external providers"
            description="Add OpenRouter, Anthropic, OpenAI, or a custom OpenAI-compatible upstream to enable external model routing."
            cta-label="Add provider"
            @cta="showAdd = true"
          />
        </Card>
      </template>

      <template v-else>
        <div class="providers-list">
          <div v-for="p in providers" :key="p.id" class="provider-row">
            <div class="provider-left">
              <span
                class="status-dot"
                :style="{ background: testResults[p.id] ? testStatusColor[testResults[p.id]] : (p.enabled ? 'var(--color-success)' : 'var(--color-fg-faint)') }"
                :title="testResults[p.id] ?? (p.enabled ? 'enabled' : 'disabled')"
                aria-hidden="true"
              />
              <div class="provider-info">
                <span class="provider-name">{{ p.name }}</span>
                <span class="provider-type">{{ p.type }} · {{ p.base_url ?? '' }}</span>
              </div>
            </div>
            <div class="provider-actions">
              <button
                class="act-btn"
                type="button"
                :disabled="testResults[p.id] === 'testing'"
                @click="testProvider(p)"
                title="Test connectivity"
              >
                <span v-if="testResults[p.id] === 'testing'" class="spinner" aria-hidden="true" />
                <template v-else>Test</template>
              </button>
              <label class="toggle-wrap" :title="p.enabled ? 'Disable' : 'Enable'">
                <input type="checkbox" class="toggle-hidden" :checked="p.enabled" @change="toggleEnabled(p)" :aria-label="`${p.enabled ? 'Disable' : 'Enable'} ${p.name}`" />
                <span class="toggle-track" :class="p.enabled ? 'track-on' : ''">
                  <span class="toggle-thumb" />
                </span>
              </label>
              <button
                class="act-btn act-danger"
                type="button"
                @click="deletingId = p.id"
                :aria-label="`Delete provider ${p.name}`"
              >
                <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- Add provider modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showAdd" class="modal-overlay" @click.self="showAdd = false">
          <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="add-provider-title">
            <div class="modal-header">
              <h2 id="add-provider-title" class="modal-title">Add provider</h2>
              <button class="modal-close" type="button" @click="showAdd = false" aria-label="Close">
                <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="modal-body">
              <div class="field">
                <label class="field-label" for="p-type">Provider type</label>
                <select id="p-type" v-model="addForm.type" class="field-input" @change="onTypeChange">
                  <option v-for="t in PROVIDER_TYPES" :key="t.id" :value="t.id">{{ t.label }}</option>
                </select>
              </div>
              <div class="field">
                <label class="field-label" for="p-name">Name <span class="req">*</span></label>
                <input id="p-name" v-model="addForm.name" class="field-input" :class="{ 'field-error': addErrors.name }" placeholder="e.g. OpenRouter (my account)" />
                <p v-if="addErrors.name" class="field-err">{{ addErrors.name }}</p>
              </div>
              <div class="field">
                <label class="field-label" for="p-key">API key <span class="req">*</span></label>
                <input id="p-key" v-model="addForm.api_key" class="field-input" :class="{ 'field-error': addErrors.api_key }" type="password" placeholder="sk-…" autocomplete="off" />
                <p v-if="addErrors.api_key" class="field-err">{{ addErrors.api_key }}</p>
              </div>
              <div class="field" v-if="addForm.type === 'custom'">
                <label class="field-label" for="p-url">Base URL <span class="req">*</span></label>
                <input id="p-url" v-model="addForm.base_url" class="field-input" :class="{ 'field-error': addErrors.base_url }" placeholder="https://api.example.com/v1" />
                <p v-if="addErrors.base_url" class="field-err">{{ addErrors.base_url }}</p>
              </div>
            </div>
            <div class="modal-footer">
              <button class="btn-ghost" type="button" @click="showAdd = false" :disabled="adding">Cancel</button>
              <button class="btn-primary" type="button" @click="submitAdd" :disabled="adding">
                <span v-if="adding" class="spinner" aria-hidden="true" />
                {{ adding ? 'Adding…' : 'Add provider' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <ConfirmDialog
      :open="!!deletingId"
      title="Delete provider?"
      message="This will remove the provider and its API key from hal0's config."
      danger
      confirm-label="Delete provider"
      :loading="deleting"
      @update:open="(v) => { if (!v) deletingId = null }"
      @confirm="confirmDelete"
      @cancel="deletingId = null"
    />
  </div>
</template>

<style scoped>
.providers-page { display: flex; flex-direction: column; min-height: 100%; }
.page-body      { padding: 20px 24px; display: flex; flex-direction: column; gap: 8px; }

.error-banner { padding: 10px 16px; border-radius: var(--radius-lg); background: color-mix(in oklch, var(--color-danger) 10%, var(--color-surface)); border: 1px solid color-mix(in oklch, var(--color-danger) 30%, transparent); color: var(--color-danger); font-size: 13px; }

.providers-list { display: flex; flex-direction: column; gap: 4px; }
.provider-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 13px 16px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); }
.provider-row:hover { border-color: var(--color-border-hi); }
.provider-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; transition: background 0.3s; }
.provider-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.provider-name { font-size: 13px; font-weight: 600; color: var(--color-fg); }
.provider-type { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-faint); }
.provider-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.act-btn { display: flex; align-items: center; gap: 5px; padding: 5px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 12px; cursor: pointer; transition: background 0.1s, color 0.1s; }
.act-btn:hover { background: var(--color-surface-2); color: var(--color-fg); }
.act-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.act-danger { width: 28px; height: 28px; padding: 0; justify-content: center; }
.act-danger:hover { background: color-mix(in oklch, var(--color-danger) 12%, transparent); color: var(--color-danger); border-color: color-mix(in oklch, var(--color-danger) 30%, transparent); }

/* Toggle */
.toggle-wrap { cursor: pointer; }
.toggle-hidden { display: none; }
.toggle-track { display: block; width: 34px; height: 18px; border-radius: 9px; background: var(--color-surface-3); border: 1px solid var(--color-border); position: relative; transition: background 0.15s; }
.toggle-track.track-on { background: var(--color-accent); border-color: var(--color-accent); }
.toggle-thumb { position: absolute; left: 2px; top: 2px; width: 12px; height: 12px; border-radius: 50%; background: white; transition: transform 0.15s; }
.toggle-track.track-on .toggle-thumb { transform: translateX(16px); }

/* Modals */
.modal-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; padding: 16px; }
.modal-box { background: var(--color-surface); border: 1px solid var(--color-border-hi); border-radius: var(--radius-xl); width: min(440px, 100%); max-height: 90vh; display: flex; flex-direction: column; box-shadow: 0 24px 64px rgba(0,0,0,0.6); overflow: hidden; }
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
.btn-primary { display: flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: var(--radius); background: var(--color-accent); color: var(--color-bg); font-size: 13px; font-weight: 600; border: none; cursor: pointer; }
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-ghost { padding: 7px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 13px; cursor: pointer; }
.btn-ghost:hover:not(:disabled) { background: var(--color-surface-2); color: var(--color-fg); }
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.spinner { width: 11px; height: 11px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
.fade-enter-active, .fade-leave-active { transition: opacity 0.12s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
