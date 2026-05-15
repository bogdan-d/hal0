<script setup>
/**
 * Settings.vue
 *
 * Design decisions:
 * - Structured form fields grouped by config section, NOT raw TOML.
 *   Raw text editing is error-prone; structured fields give inline validation.
 * - Diff view before save: shows changed fields so the user sees the impact.
 * - Fields that need a restart show a "restart required" badge inline.
 * - Dangerous actions at the bottom, each requiring a confirm dialog.
 * - Config path visible at the top so the user knows where the file lives.
 * - Phase 0: mock response shape. Phase 1: wire to GET/PUT /api/settings/*.
 */
import { ref, computed, reactive, onMounted } from 'vue'
import { useToastsStore } from '../stores/toasts.js'
import { useSystemStore } from '../stores/system.js'
import { api } from '../composables/useApi.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const toasts = useToastsStore()
const system = useSystemStore()

// ── Remote config (loaded from API) ───────────────────────────────────
const loading  = ref(true)
const saving   = ref(false)
const error    = ref(null)

// Original values (for diff)
const orig = ref({})

// Current form values
const form = reactive({
  // [general]
  instance_name:  '',
  log_level:      'info',

  // [api]
  port:           8080,
  cors_origins:   '',

  // [dispatcher]
  cold_boot_grace_s:    180,
  prefetch_timeout_s:   8,
  cache_ttl_s:          300,
  parallel_prefetch_cap: 4,

  // [update]
  channel: 'stable',

  // [telemetry]
  telemetry_enabled: false,

  // [toolbox]
  toolbox_vulkan_tag: 'v1',
  toolbox_rocm_tag:   'v1',
  toolbox_flm_tag:    'v1',
})

const configPath = ref('/etc/hal0/hal0.toml')
const hal0HomeOverride = ref(null)

// ── Diff ──────────────────────────────────────────────────────────────
const changedFields = computed(() => {
  const changed = []
  for (const key of Object.keys(form)) {
    if (String(form[key]) !== String(orig.value[key] ?? '')) {
      changed.push({ key, from: orig.value[key], to: form[key] })
    }
  }
  return changed
})

const restartRequiredFields = new Set(['port', 'cors_origins', 'log_level', 'channel'])

function needsRestart(key) {
  return restartRequiredFields.has(key)
}

// ── Field metadata ────────────────────────────────────────────────────
const SECTIONS = [
  {
    title: 'General',
    fields: [
      { key: 'instance_name',  label: 'Instance name', type: 'text',   hint: 'Shown in dashboard and OpenWebUI.' },
      { key: 'log_level',      label: 'Log level',     type: 'select', options: ['debug', 'info', 'warn', 'error'], restart: true },
    ],
  },
  {
    title: 'API',
    fields: [
      { key: 'port',         label: 'Listen port',   type: 'number', hint: 'Default: 8080. Requires restart.', restart: true },
      { key: 'cors_origins', label: 'CORS origins',  type: 'text',   hint: 'Comma-separated. * for all. Requires restart.', restart: true },
    ],
  },
  {
    title: 'Dispatcher',
    fields: [
      { key: 'cold_boot_grace_s',     label: 'Cold-boot grace (s)',      type: 'number', hint: 'Max time to wait for slot to become ready. Default: 180.' },
      { key: 'prefetch_timeout_s',    label: 'Prefetch timeout (s)',      type: 'number', hint: 'Default: 8.' },
      { key: 'cache_ttl_s',           label: 'Cache TTL (s)',             type: 'number', hint: 'Default: 300.' },
      { key: 'parallel_prefetch_cap', label: 'Parallel prefetch cap',     type: 'number', hint: 'Default: 4.' },
    ],
  },
  {
    title: 'Update channel',
    fields: [
      { key: 'channel', label: 'Channel', type: 'select', options: ['stable', 'nightly'], restart: true,
        hint: 'stable = tagged releases; nightly = every main push. Change takes effect on next update check.' },
    ],
  },
  {
    title: 'Toolbox images',
    fields: [
      { key: 'toolbox_vulkan_tag', label: 'Vulkan tag', type: 'text', hint: 'Default: v1. Override pinned toolbox image tag.' },
      { key: 'toolbox_rocm_tag',   label: 'ROCm tag',   type: 'text' },
      { key: 'toolbox_flm_tag',    label: 'FLM tag',    type: 'text' },
    ],
  },
  {
    title: 'Telemetry',
    fields: [
      { key: 'telemetry_enabled', label: 'Enable telemetry', type: 'checkbox',
        hint: 'Off by default. Sends anonymous ping (hardware class, version, slot count). No model names or config content.' },
    ],
  },
]

// ── Loaders ────────────────────────────────────────────────────────────
async function loadSettings() {
  loading.value = true
  error.value = null
  try {
    const data = await api('/api/settings')
    // Flatten the nested config into form fields
    applyData(data)
    orig.value = { ...form }
    configPath.value = data._meta?.config_path ?? '/etc/hal0/hal0.toml'
    hal0HomeOverride.value = data._meta?.hal0_home ?? null
  } catch (e) {
    // Phase 0: use defaults if API isn't wired yet
    orig.value = { ...form }
    if (e.message.includes('501') || e.message.includes('404')) {
      // Expected in Phase 0 — silently use defaults
    } else {
      error.value = e.message
    }
  } finally {
    loading.value = false
  }
}

function applyData(data) {
  const g = data.general ?? {}
  const a = data.api ?? {}
  const d = data.dispatcher ?? {}
  const u = data.update ?? {}
  const t = data.telemetry ?? {}
  const tb = data.toolbox ?? {}

  if (g.instance_name  != null) form.instance_name  = g.instance_name
  if (g.log_level      != null) form.log_level      = g.log_level
  if (a.port           != null) form.port           = a.port
  if (a.cors_origins   != null) form.cors_origins   = a.cors_origins
  if (d.cold_boot_grace_s     != null) form.cold_boot_grace_s     = d.cold_boot_grace_s
  if (d.prefetch_timeout_s    != null) form.prefetch_timeout_s    = d.prefetch_timeout_s
  if (d.cache_ttl_s           != null) form.cache_ttl_s           = d.cache_ttl_s
  if (d.parallel_prefetch_cap != null) form.parallel_prefetch_cap = d.parallel_prefetch_cap
  if (u.channel        != null) form.channel        = u.channel
  if (t.enabled        != null) form.telemetry_enabled = t.enabled
  if (tb.vulkan_tag    != null) form.toolbox_vulkan_tag = tb.vulkan_tag
  if (tb.rocm_tag      != null) form.toolbox_rocm_tag   = tb.rocm_tag
  if (tb.flm_tag       != null) form.toolbox_flm_tag    = tb.flm_tag
}

// ── Validation ────────────────────────────────────────────────────────
const fieldErrors = ref({})

function validate() {
  const errs = {}
  if (form.port < 1024 || form.port > 65535) errs.port = 'Must be 1024–65535'
  if (form.cold_boot_grace_s < 10)           errs.cold_boot_grace_s = 'Must be ≥ 10'
  if (form.prefetch_timeout_s < 1)           errs.prefetch_timeout_s = 'Must be ≥ 1'
  if (form.cache_ttl_s < 0)                  errs.cache_ttl_s = 'Must be ≥ 0'
  if (form.parallel_prefetch_cap < 1)        errs.parallel_prefetch_cap = 'Must be ≥ 1'
  fieldErrors.value = errs
  return Object.keys(errs).length === 0
}

// ── Save ──────────────────────────────────────────────────────────────
const showDiff = ref(false)

async function save() {
  if (!validate()) return
  showDiff.value = false
  saving.value = true
  try {
    await api('/api/settings', {
      method: 'PUT',
      body: JSON.stringify({
        general:    { instance_name: form.instance_name, log_level: form.log_level },
        api:        { port: form.port, cors_origins: form.cors_origins },
        dispatcher: {
          cold_boot_grace_s:     form.cold_boot_grace_s,
          prefetch_timeout_s:    form.prefetch_timeout_s,
          cache_ttl_s:           form.cache_ttl_s,
          parallel_prefetch_cap: form.parallel_prefetch_cap,
        },
        update:    { channel: form.channel },
        telemetry: { enabled: form.telemetry_enabled },
        toolbox:   { vulkan_tag: form.toolbox_vulkan_tag, rocm_tag: form.toolbox_rocm_tag, flm_tag: form.toolbox_flm_tag },
      }),
    })
    orig.value = { ...form }
    toasts.success('Settings saved')
    if (changedFields.value.some((f) => restartRequiredFields.has(f.key))) {
      toasts.info('Some changes require an API restart to take effect.')
    }
    await system.fetchStatus()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    saving.value = false
  }
}

function revert() {
  Object.assign(form, orig.value)
  fieldErrors.value = {}
  showDiff.value = false
}

// ── Dangerous actions ─────────────────────────────────────────────────
const confirmAction  = ref(null)  // 'reset-defaults' | 're-probe' | 'clear-cache'
const actionLoading  = ref(false)

const DANGER_ACTIONS = [
  { id: 'reset-defaults', label: 'Reset to defaults', desc: 'Overwrites /etc/hal0/hal0.toml with default values. Current config is lost.', danger: true },
  { id: 're-probe',       label: 'Re-run hardware probe', desc: 'Runs hal0 probe and updates hardware.json. Safe to re-run.', danger: false },
  { id: 'clear-cache',    label: 'Clear dispatcher cache', desc: 'Clears cold-start model cache and SSE state. In-flight requests complete.', danger: false },
]

async function runDangerAction() {
  const id = confirmAction.value
  confirmAction.value = null
  actionLoading.value = true
  try {
    const endpoints = {
      'reset-defaults': ['/api/settings/reset', 'POST'],
      're-probe':        ['/api/hardware/probe', 'POST'],
      'clear-cache':     ['/api/dispatcher/cache', 'DELETE'],
    }
    const [path, method] = endpoints[id]
    await api(path, { method })
    toasts.success(`${DANGER_ACTIONS.find((a) => a.id === id)?.label} done`)
    if (id === 'reset-defaults') await loadSettings()
    if (id === 're-probe') await system.fetchStatus()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <div class="settings-page">
    <PageHeader title="Settings" subtitle="Configure hal0 runtime behaviour">
      <template #actions>
        <span v-if="changedFields.length > 0" class="change-count">{{ changedFields.length }} unsaved change{{ changedFields.length !== 1 ? 's' : '' }}</span>
        <button class="btn-ghost" type="button" @click="revert" :disabled="saving || changedFields.length === 0">Revert</button>
        <button class="btn-primary" type="button" @click="showDiff = true" :disabled="saving || changedFields.length === 0">
          <span v-if="saving" class="spinner" aria-hidden="true" />
          {{ saving ? 'Saving…' : 'Save changes' }}
        </button>
      </template>
    </PageHeader>

    <div class="page-body">
      <!-- Config path -->
      <div class="config-path-row">
        <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
        <code class="config-path">{{ configPath }}</code>
        <span v-if="hal0HomeOverride" class="hal0-home-note">HAL0_HOME={{ hal0HomeOverride }}</span>
      </div>

      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>

      <!-- Form sections -->
      <template v-if="loading">
        <Card v-for="i in 3" :key="i"><LoadingSkeleton :lines="3" /></Card>
      </template>
      <template v-else>
        <Card v-for="section in SECTIONS" :key="section.title">
          <h3 class="section-title">{{ section.title }}</h3>
          <div class="fields">
            <div
              v-for="field in section.fields"
              :key="field.key"
              class="field-row"
            >
              <div class="field-meta">
                <label :for="'f-' + field.key" class="field-label">
                  {{ field.label }}
                  <span v-if="field.restart" class="restart-badge" title="Requires API restart">restart</span>
                </label>
                <p v-if="field.hint" class="field-hint">{{ field.hint }}</p>
                <p v-if="fieldErrors[field.key]" class="field-err" role="alert">{{ fieldErrors[field.key] }}</p>
              </div>
              <div class="field-input-wrap">
                <template v-if="field.type === 'checkbox'">
                  <label class="toggle-label">
                    <input
                      type="checkbox"
                      class="toggle-checkbox"
                      v-model="form[field.key]"
                    />
                    <span class="toggle-track">
                      <span class="toggle-thumb" />
                    </span>
                    <span class="toggle-text">{{ form[field.key] ? 'Enabled' : 'Disabled' }}</span>
                  </label>
                </template>
                <template v-else-if="field.type === 'select'">
                  <select
                    :id="'f-' + field.key"
                    v-model="form[field.key]"
                    class="field-input"
                    :class="{ 'field-changed': String(form[field.key]) !== String(orig[field.key] ?? '') }"
                  >
                    <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
                  </select>
                </template>
                <template v-else>
                  <input
                    :id="'f-' + field.key"
                    v-model="form[field.key]"
                    :type="field.type"
                    class="field-input"
                    :class="{
                      'field-changed': String(form[field.key]) !== String(orig[field.key] ?? ''),
                      'field-error':   !!fieldErrors[field.key],
                    }"
                  />
                </template>
              </div>
            </div>
          </div>
        </Card>

        <!-- Dangerous actions -->
        <Card>
          <h3 class="section-title section-title-danger">Dangerous actions</h3>
          <div class="danger-list">
            <div v-for="action in DANGER_ACTIONS" :key="action.id" class="danger-row">
              <div class="danger-info">
                <span class="danger-label">{{ action.label }}</span>
                <span class="danger-desc">{{ action.desc }}</span>
              </div>
              <button
                class="btn-action"
                :class="action.danger ? 'btn-danger' : 'btn-secondary'"
                type="button"
                :disabled="actionLoading"
                @click="confirmAction = action.id"
              >
                {{ action.label }}
              </button>
            </div>
          </div>
        </Card>
      </template>
    </div>

    <!-- Diff modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showDiff" class="modal-overlay" @click.self="showDiff = false">
          <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="diff-title">
            <div class="modal-header">
              <h2 id="diff-title" class="modal-title">Review changes ({{ changedFields.length }})</h2>
              <button class="modal-close" type="button" @click="showDiff = false" aria-label="Close">
                <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="modal-body">
              <table class="diff-table">
                <thead>
                  <tr><th>Field</th><th>From</th><th>To</th><th></th></tr>
                </thead>
                <tbody>
                  <tr v-for="ch in changedFields" :key="ch.key">
                    <td class="mono">{{ ch.key }}</td>
                    <td class="mono text-muted">{{ String(ch.from ?? '') || '(empty)' }}</td>
                    <td class="mono text-accent">{{ String(ch.to) }}</td>
                    <td>
                      <span v-if="needsRestart(ch.key)" class="restart-badge">restart</span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <p v-if="changedFields.some((f) => needsRestart(f.key))" class="restart-notice" role="alert">
                Some changes require an API restart. Slots will keep running.
              </p>
            </div>
            <div class="modal-footer">
              <button class="btn-ghost" type="button" @click="showDiff = false" :disabled="saving">Cancel</button>
              <button class="btn-primary" type="button" @click="save" :disabled="saving">
                <span v-if="saving" class="spinner" aria-hidden="true" />
                {{ saving ? 'Saving…' : 'Apply changes' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Danger confirm -->
    <ConfirmDialog
      :open="!!confirmAction"
      :title="DANGER_ACTIONS.find((a) => a.id === confirmAction)?.label ?? ''"
      :message="DANGER_ACTIONS.find((a) => a.id === confirmAction)?.desc ?? ''"
      :danger="DANGER_ACTIONS.find((a) => a.id === confirmAction)?.danger ?? false"
      :confirm-label="DANGER_ACTIONS.find((a) => a.id === confirmAction)?.label ?? 'Confirm'"
      :loading="actionLoading"
      @update:open="(v) => { if (!v) confirmAction = null }"
      @confirm="runDangerAction"
      @cancel="confirmAction = null"
    />
  </div>
</template>

<style scoped>
.settings-page { display: flex; flex-direction: column; min-height: 100%; }
.page-body     { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }

.config-path-row { display: flex; align-items: center; gap: 8px; padding: 8px 0; }
.config-path { font-family: var(--font-mono); font-size: 12px; color: var(--color-fg-muted); }
.hal0-home-note { font-family: var(--font-mono); font-size: 11px; color: var(--color-warning); background: color-mix(in oklch, var(--color-warning) 12%, transparent); padding: 2px 6px; border-radius: 4px; }

.error-banner { padding: 10px 16px; border-radius: var(--radius-lg); background: color-mix(in oklch, var(--color-danger) 10%, var(--color-surface)); border: 1px solid color-mix(in oklch, var(--color-danger) 30%, transparent); color: var(--color-danger); font-size: 13px; }

.section-title { font-size: 13px; font-weight: 600; color: var(--color-fg-muted); margin: 0 0 14px; letter-spacing: 0.02em; }
.section-title-danger { color: var(--color-danger); }

.fields { display: flex; flex-direction: column; gap: 14px; }
.field-row { display: grid; grid-template-columns: 1fr 240px; align-items: start; gap: 16px; }
@media (max-width: 640px) { .field-row { grid-template-columns: 1fr; } }

.field-meta { display: flex; flex-direction: column; gap: 3px; }
.field-label { font-size: 13px; font-weight: 500; color: var(--color-fg); display: flex; align-items: center; gap: 8px; }
.field-hint { font-size: 11.5px; color: var(--color-fg-faint); margin: 0; font-family: var(--font-mono); }
.field-err  { font-size: 11.5px; color: var(--color-danger); margin: 0; }
.restart-badge { font-family: var(--font-mono); font-size: 9.5px; padding: 1px 5px; border-radius: 3px; background: color-mix(in oklch, var(--color-warning) 15%, transparent); color: var(--color-warning); border: 1px solid color-mix(in oklch, var(--color-warning) 30%, transparent); white-space: nowrap; }

.field-input-wrap { display: flex; flex-direction: column; }
.field-input {
  padding: 7px 10px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-fg);
  font-size: 13px;
  outline: none;
  transition: border-color 0.1s;
  width: 100%;
  box-sizing: border-box;
}
.field-input:focus { border-color: var(--color-border-hi); }
.field-changed { border-color: color-mix(in oklch, var(--color-accent) 50%, var(--color-border)) !important; }
.field-error   { border-color: var(--color-danger) !important; }

/* Toggle */
.toggle-label { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.toggle-checkbox { display: none; }
.toggle-track {
  width: 36px; height: 20px; border-radius: 10px;
  background: var(--color-surface-3); border: 1px solid var(--color-border);
  position: relative; flex-shrink: 0; transition: background 0.15s;
}
.toggle-checkbox:checked + .toggle-track { background: var(--color-accent); border-color: var(--color-accent); }
.toggle-thumb {
  position: absolute; left: 2px; top: 2px;
  width: 14px; height: 14px; border-radius: 50%;
  background: white; transition: transform 0.15s;
}
.toggle-checkbox:checked + .toggle-track .toggle-thumb { transform: translateX(16px); }
.toggle-text { font-size: 13px; color: var(--color-fg-muted); }

/* Dangerous actions */
.danger-list { display: flex; flex-direction: column; gap: 10px; }
.danger-row { display: flex; align-items: center; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--color-border); }
.danger-row:last-child { border-bottom: none; padding-bottom: 0; }
.danger-info { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.danger-label { font-size: 13px; font-weight: 500; color: var(--color-fg); }
.danger-desc  { font-size: 12px; color: var(--color-fg-faint); }

.change-count { font-family: var(--font-mono); font-size: 11.5px; color: var(--color-warning); }

/* Diff modal */
.diff-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.diff-table th { padding: 8px 10px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); font-family: var(--font-mono); border-bottom: 1px solid var(--color-border); }
.diff-table td { padding: 8px 10px; border-bottom: 1px solid var(--color-border); }
.diff-table tbody tr:last-child td { border-bottom: none; }
.mono { font-family: var(--font-mono); }
.text-muted  { color: var(--color-fg-faint); }
.text-accent { color: var(--color-accent); }
.restart-notice { margin-top: 12px; padding: 8px 12px; border-radius: var(--radius); background: color-mix(in oklch, var(--color-warning) 12%, transparent); color: var(--color-warning); font-size: 12.5px; }

/* Shared */
.modal-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; padding: 16px; }
.modal-box { background: var(--color-surface); border: 1px solid var(--color-border-hi); border-radius: var(--radius-xl); width: min(540px, 100%); max-height: 90vh; display: flex; flex-direction: column; box-shadow: 0 24px 64px rgba(0,0,0,0.6); overflow: hidden; }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--color-border); }
.modal-title { font-size: 15px; font-weight: 600; color: var(--color-fg); margin: 0; }
.modal-close { width: 28px; height: 28px; border-radius: var(--radius); background: transparent; border: 1px solid transparent; color: var(--color-fg-faint); cursor: pointer; display: grid; place-items: center; }
.modal-close:hover { background: var(--color-surface-2); color: var(--color-fg); }
.modal-body { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; flex: 1; }
.modal-footer { padding: 16px 20px; border-top: 1px solid var(--color-border); display: flex; justify-content: flex-end; gap: 8px; }

.btn-primary { display: flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: var(--radius); background: var(--color-accent); color: var(--color-bg); font-size: 13px; font-weight: 600; border: none; cursor: pointer; }
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-ghost { padding: 7px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 13px; cursor: pointer; }
.btn-ghost:hover:not(:disabled) { background: var(--color-surface-2); color: var(--color-fg); }
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-action { padding: 6px 14px; border-radius: var(--radius); font-size: 12.5px; cursor: pointer; border: 1px solid var(--color-border); white-space: nowrap; flex-shrink: 0; }
.btn-secondary { background: transparent; color: var(--color-fg-muted); }
.btn-secondary:hover:not(:disabled) { background: var(--color-surface-2); }
.btn-danger  { background: color-mix(in oklch, var(--color-danger) 12%, transparent); border-color: color-mix(in oklch, var(--color-danger) 30%, transparent); color: var(--color-danger); }
.btn-danger:hover:not(:disabled)  { background: color-mix(in oklch, var(--color-danger) 20%, transparent); }
.btn-action:disabled { opacity: 0.5; cursor: not-allowed; }

.spinner { width: 11px; height: 11px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }

.fade-enter-active, .fade-leave-active { transition: opacity 0.12s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
