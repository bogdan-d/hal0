<script setup>
/**
 * Settings.vue — typed config editor backed by /api/settings.
 *
 * Backend contract (Team C):
 *   GET  /api/settings          → { meta, slots, dispatcher, telemetry }
 *   PUT  /api/settings (partial, deep-merged) → updated config
 *   POST /api/settings/reload   → re-read hal0.toml into the running process
 *   GET  /api/settings/schema   → pydantic JSON schema (used to populate
 *                                 type / description / constraints below)
 *
 * The schema lives in src/hal0/config/schema.py — sections:
 *   - meta.schema_version          int >= 1  (restart on bump)
 *   - slots.max_slots              int >= 0 (0 = unlimited)
 *   - slots.port_range_start/end   1024–65535
 *   - dispatcher.prefetch_timeout_s float > 0
 *   - dispatcher.prefetch_parallel_cap int >= 1
 *   - telemetry.enabled            bool
 *   - telemetry.channel            'stable' | 'nightly'  (restart-required)
 *
 * Validation failures from PUT come back as { error: { code:
 * "config.invalid", details: { "field.path": "msg" }}}. useApi.js's
 * fetch wrapper surfaces those on the Error.details map so we can render
 * inline per-field reasons.
 */
import { ref, computed, reactive, onMounted } from 'vue'
import { useToastsStore } from '../stores/toasts.js'
import { api } from '../composables/useApi.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const toasts = useToastsStore()

const loading = ref(true)
const saving  = ref(false)
const error   = ref(null)

// Original snapshot (for diff + revert) and live form values.
const orig = ref({})
const form = reactive({
  meta:       { schema_version: 1 },
  slots:      { max_slots: 0, port_range_start: 8081, port_range_end: 8099 },
  dispatcher: { prefetch_timeout_s: 8.0, prefetch_parallel_cap: 4 },
  telemetry:  { enabled: false, channel: 'stable' },
})

// Per-field error map keyed by pydantic field path (e.g.
// "dispatcher.prefetch_timeout_s"). Populated when PUT returns
// code: "config.invalid".
const fieldErrors = ref({})

// Keys (as dot-paths) whose change requires an API restart to take effect.
const RESTART_REQUIRED = new Set([
  'telemetry.channel',
  'meta.schema_version',
])

// Show a local "restart required" banner after a successful save when
// any restart-required key actually changed. Resets on next save.
const pendingRestart = ref(false)
const restartedKeys  = ref([])

// ── load + apply ─────────────────────────────────────────────────────
async function load() {
  loading.value = true
  error.value = null
  try {
    const data = await api('/api/settings')
    applyServerData(data)
    snapshotOrig()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function applyServerData(data) {
  // Deep-copy the four known sections; preserve unknown keys via
  // `extra="allow"` round-trip by stashing them on the section objects.
  const sections = ['meta', 'slots', 'dispatcher', 'telemetry']
  for (const key of sections) {
    const src = data?.[key] ?? {}
    form[key] = { ...form[key], ...src }
  }
}

function snapshotOrig() {
  orig.value = JSON.parse(JSON.stringify({
    meta: form.meta,
    slots: form.slots,
    dispatcher: form.dispatcher,
    telemetry: form.telemetry,
  }))
}

// ── diff helpers ─────────────────────────────────────────────────────
function valueChanged(section, key) {
  return String(form[section][key]) !== String(orig.value?.[section]?.[key] ?? '')
}

const changedFields = computed(() => {
  const out = []
  for (const section of ['meta', 'slots', 'dispatcher', 'telemetry']) {
    const before = orig.value?.[section] ?? {}
    const after  = form[section] ?? {}
    for (const key of Object.keys(after)) {
      const a = before[key]
      const b = after[key]
      if (String(a ?? '') !== String(b ?? '')) {
        out.push({ path: `${section}.${key}`, from: a, to: b })
      }
    }
  }
  return out
})

// ── save ─────────────────────────────────────────────────────────────
function buildPatch() {
  // Send only the dotted paths that actually changed, deep-merge-safe.
  const patch = {}
  for (const ch of changedFields.value) {
    const [section, key] = ch.path.split('.')
    if (!patch[section]) patch[section] = {}
    patch[section][key] = ch.to
  }
  return patch
}

async function save() {
  if (changedFields.value.length === 0) return
  fieldErrors.value = {}
  saving.value = true
  try {
    const body = JSON.stringify(buildPatch())
    const updated = await api('/api/settings', { method: 'PUT', body })
    const changedRestartKeys = changedFields.value
      .map((c) => c.path)
      .filter((p) => RESTART_REQUIRED.has(p))
    applyServerData(updated)
    snapshotOrig()
    toasts.success('Settings saved')
    if (changedRestartKeys.length > 0) {
      pendingRestart.value = true
      restartedKeys.value  = changedRestartKeys
    }
  } catch (e) {
    if (e.code === 'config.invalid' && e.details && typeof e.details === 'object') {
      // Render per-field inline error messages exactly where the form
      // says "field-err" today. Pydantic returns paths like
      // "dispatcher.prefetch_timeout_s" — match those verbatim.
      fieldErrors.value = e.details
      toasts.error('Settings did not validate — see inline errors')
    } else {
      toasts.error(e.message)
    }
  } finally {
    saving.value = false
  }
}

async function reload() {
  // POST /api/settings/reload re-reads hal0.toml from disk into the
  // running process — useful after an out-of-band editor change.
  try {
    const data = await api('/api/settings/reload', { method: 'POST' })
    applyServerData(data)
    snapshotOrig()
    fieldErrors.value = {}
    toasts.success('Settings reloaded from disk')
  } catch (e) {
    toasts.error(e.message)
  }
}

function revert() {
  applyServerData(orig.value)
  fieldErrors.value = {}
}

function dismissRestart() {
  pendingRestart.value = false
  restartedKeys.value  = []
}

// ── field declarations (used by the template) ───────────────────────
// Built off the pydantic schema in src/hal0/config/schema.py. The
// schema endpoint /api/settings/schema is available if we want to be
// fully data-driven later; keeping these explicit keeps the form
// human-readable and lets us write per-field hints. extra keys
// preserved server-side via `extra="allow"` will still round-trip even
// though they don't render here.
const SECTIONS = [
  {
    id: 'meta',
    title: 'Meta',
    fields: [
      {
        key: 'schema_version',
        label: 'Schema version',
        type: 'number',
        hint: 'Bumped by config migrations. Restart required when manually edited.',
      },
    ],
  },
  {
    id: 'slots',
    title: 'Slots',
    fields: [
      { key: 'max_slots', label: 'Max concurrent slots', type: 'number',
        hint: '0 means unlimited.' },
      { key: 'port_range_start', label: 'Port range start', type: 'number',
        hint: 'First port available to slots (default 8081).' },
      { key: 'port_range_end', label: 'Port range end', type: 'number',
        hint: 'Last port (inclusive, default 8099).' },
    ],
  },
  {
    id: 'dispatcher',
    title: 'Dispatcher',
    fields: [
      { key: 'prefetch_timeout_s', label: 'Prefetch timeout (s)', type: 'number', step: '0.5',
        hint: 'Cold-cache prefetch deadline. Default 8s (PLAN §5 Tier 2).' },
      { key: 'prefetch_parallel_cap', label: 'Prefetch parallel cap', type: 'number',
        hint: 'Max concurrent upstream prefetches. Default 4.' },
    ],
  },
  {
    id: 'telemetry',
    title: 'Telemetry',
    fields: [
      { key: 'enabled', label: 'Telemetry enabled', type: 'checkbox',
        hint: 'Off by default — anonymous opt-in ping (PLAN §14).' },
      { key: 'channel', label: 'Update channel', type: 'select',
        options: ['stable', 'nightly'],
        hint: 'Stable = tagged releases; nightly = every main push. Restart-required.' },
    ],
  },
]

// ── Authentication panel (v0.2 auth POC, Team J) ─────────────────────
//
// The panel reads /api/auth/status to render the on/off badge and the
// caller's identity, and /api/auth/tokens to list mintable bearer
// tokens. Token CRUD goes through the admin-protected /api/auth/tokens
// subrouter (require_admin) — the dashboard caller is always admin via
// Caddy basic_auth in the deployed config, so the call succeeds.
//
// Important UX note: a freshly-minted token's raw value is shown ONCE
// in `newTokenRaw` and never again. The modal warns the user verbatim,
// then on close clears the raw value from memory.

const authStatus    = ref({ enabled: false, modes: [], managed_via_installer: true })
const authIdentity  = ref({ identity: 'anonymous', scope: 'all', source: 'anonymous' })
const tokens        = ref([])
const tokensLoading = ref(false)
const tokensError   = ref(null)

const showCreateTokenModal = ref(false)
const newTokenLabel        = ref('')
const newTokenScope        = ref('all')
const newTokenRaw          = ref('')          // shown once, cleared on close
const newTokenCopied       = ref(false)
const creatingToken        = ref(false)
const showRevokeModal      = ref(false)
const revokeTarget         = ref(null)        // {id, label}
const showAuthInfoModal    = ref(false)

async function loadAuthState() {
  try {
    authStatus.value = await api('/api/auth/status')
  } catch (e) {
    // Auth status is public; a failure here means the API itself is
    // unhealthy — surface as an error banner via the existing route.
    error.value = e.message
    return
  }
  // /api/auth/me requires a Bearer or X-Forwarded-Email — when the
  // dashboard is loaded directly (no auth) the call 401s and we
  // gracefully fall back to "anonymous". When loaded behind Caddy, the
  // forwarded email gives us the admin identity.
  try {
    authIdentity.value = await api('/api/auth/me')
  } catch {
    authIdentity.value = { identity: 'anonymous', scope: 'all', source: 'anonymous' }
  }
  await loadTokens()
}

async function loadTokens() {
  tokensLoading.value = true
  tokensError.value = null
  try {
    const data = await api('/api/auth/tokens')
    tokens.value = data.tokens || []
  } catch (e) {
    // 401 / 403 here is "you're not admin" or "auth disabled" — render
    // a clear hint rather than a noisy toast. We still want the panel
    // to render so the operator can see the auth state.
    if (e.code === 'auth.required' || e.code === 'auth.forbidden') {
      tokens.value = []
      tokensError.value = 'Token management is admin-only. Sign in via the Caddy basic_auth prompt or use an admin Bearer token.'
    } else if (e.code === 'system.http_404') {
      // Auth router not mounted — older API, ignore.
      tokens.value = []
    } else {
      tokensError.value = e.message
    }
  } finally {
    tokensLoading.value = false
  }
}

function openCreateTokenModal() {
  newTokenLabel.value = ''
  newTokenScope.value = 'all'
  newTokenRaw.value   = ''
  newTokenCopied.value = false
  showCreateTokenModal.value = true
}

function closeCreateTokenModal() {
  // Clear the raw token from memory before the modal unmounts. Vue's
  // reactivity won't expose it any more once the v-if flips false, but
  // we want the local ref empty too in case dev tools snapshot state.
  newTokenRaw.value = ''
  newTokenLabel.value = ''
  newTokenCopied.value = false
  showCreateTokenModal.value = false
}

async function submitCreateToken() {
  if (!newTokenLabel.value.trim()) {
    toasts.error('Token label is required')
    return
  }
  creatingToken.value = true
  try {
    const body = JSON.stringify({
      label: newTokenLabel.value.trim(),
      scope: newTokenScope.value,
    })
    const result = await api('/api/auth/tokens', { method: 'POST', body })
    newTokenRaw.value = result.token
    toasts.success(`Token "${result.label}" created — copy it now`)
    await loadTokens()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    creatingToken.value = false
  }
}

async function copyTokenToClipboard() {
  if (!newTokenRaw.value) return
  try {
    await navigator.clipboard.writeText(newTokenRaw.value)
    newTokenCopied.value = true
    toasts.success('Token copied to clipboard')
  } catch {
    toasts.error('Could not copy — select the value manually')
  }
}

function openRevokeModal(token) {
  revokeTarget.value = token
  showRevokeModal.value = true
}

async function confirmRevokeToken() {
  if (!revokeTarget.value) return
  try {
    await api(`/api/auth/tokens/${revokeTarget.value.id}`, { method: 'DELETE' })
    toasts.success(`Token "${revokeTarget.value.label}" revoked`)
    showRevokeModal.value = false
    revokeTarget.value = null
    await loadTokens()
  } catch (e) {
    toasts.error(e.message)
  }
}

function formatTimestamp(iso) {
  if (!iso) return 'never'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString()
  } catch {
    return iso
  }
}

onMounted(async () => {
  await load()
  await loadAuthState()
})
</script>

<template>
  <div class="settings-page">
    <PageHeader title="Settings" subtitle="hal0.toml runtime configuration">
      <template #actions>
        <span v-if="changedFields.length > 0" class="change-count">
          {{ changedFields.length }} unsaved change{{ changedFields.length !== 1 ? 's' : '' }}
        </span>
        <button class="btn-ghost" type="button" @click="reload" :disabled="saving" title="Re-read /etc/hal0/hal0.toml from disk">
          Reload from disk
        </button>
        <button class="btn-ghost" type="button" @click="revert" :disabled="saving || changedFields.length === 0">
          Revert
        </button>
        <button class="btn-primary" type="button" @click="save" :disabled="saving || changedFields.length === 0">
          <span v-if="saving" class="spinner" aria-hidden="true" />
          {{ saving ? 'Saving…' : 'Save changes' }}
        </button>
      </template>
    </PageHeader>

    <!-- Restart-required banner (rendered after a successful save when
         a restart-required key actually changed). Matches the styling
         of components/RestartBanner.vue so the visual language is
         consistent — that component is wired to system store updates
         and stays our home for update-available banners. -->
    <Transition name="slide-up">
      <div v-if="pendingRestart" class="restart-banner" role="alert">
        <svg width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        <span>
          Restart required for: <strong class="mono">{{ restartedKeys.join(', ') }}</strong>. Slots will keep running across an API restart.
        </span>
        <button type="button" class="banner-btn" @click="dismissRestart">Dismiss</button>
      </div>
    </Transition>

    <div class="page-body">
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>

      <!-- ── Authentication panel (Team J / v0.2 auth POC) ────────── -->
      <Card>
        <div class="auth-header">
          <h3 class="section-title">Authentication</h3>
          <div class="auth-status-row">
            <span class="auth-badge" :class="authStatus.enabled ? 'auth-on' : 'auth-off'">
              {{ authStatus.enabled ? 'Enabled' : 'Disabled' }}
            </span>
            <span class="auth-identity mono" v-if="authStatus.enabled">
              {{ authIdentity.identity }} · scope=<strong>{{ authIdentity.scope }}</strong>
            </span>
            <button class="btn-ghost btn-small" type="button" @click="showAuthInfoModal = true">
              How does this work?
            </button>
          </div>
        </div>

        <div v-if="!authStatus.enabled" class="auth-disabled-hint">
          Auth is currently <strong>off</strong> — the API and chat bind public ports
          with no credentials required. Re-run the installer with
          <code class="mono">--auth=basic</code> to bring up Caddy, basic_auth at the
          edge, and bearer tokens for the OpenAI-compatible API. Toggling auth here
          alone would lock you out without a Caddy front; the installer wires both
          sides atomically.
        </div>

        <div v-else>
          <div class="tokens-row">
            <div>
              <h4 class="subsection-title">Bearer tokens</h4>
              <p class="field-hint">
                Programmatic clients (OpenWebUI bridge, third-party OpenAI SDKs)
                authenticate by sending <code class="mono">Authorization: Bearer hal0_…</code>.
                Browser sessions go through Caddy basic_auth — no token needed.
              </p>
            </div>
            <button class="btn-primary btn-small" type="button" @click="openCreateTokenModal">
              + Create token
            </button>
          </div>

          <div v-if="tokensError" class="error-banner" role="alert">{{ tokensError }}</div>
          <div v-else-if="tokensLoading" class="loading-row">Loading tokens…</div>
          <div v-else-if="tokens.length === 0" class="empty-row">
            No tokens yet. Create one to authenticate the OpenWebUI bridge or any
            external OpenAI client.
          </div>
          <table v-else class="token-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Scope</th>
                <th>Created</th>
                <th>Last used</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tokens" :key="t.id">
                <td class="mono">{{ t.label }}</td>
                <td><span class="scope-badge">{{ t.scope }}</span></td>
                <td class="mono dim">{{ formatTimestamp(t.created_at) }}</td>
                <td class="mono dim">{{ formatTimestamp(t.last_used_at) }}</td>
                <td class="row-actions">
                  <button class="btn-danger btn-small" type="button"
                          @click="openRevokeModal(t)" title="Revoke token">
                    Revoke
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <template v-if="loading">
        <Card v-for="i in 3" :key="i"><LoadingSkeleton :lines="3" /></Card>
      </template>

      <template v-else>
        <Card v-for="section in SECTIONS" :key="section.id">
          <h3 class="section-title">{{ section.title }}</h3>
          <div class="fields">
            <div v-for="field in section.fields" :key="field.key" class="field-row">
              <div class="field-meta">
                <label :for="`f-${section.id}-${field.key}`" class="field-label">
                  {{ field.label }}
                  <span v-if="RESTART_REQUIRED.has(`${section.id}.${field.key}`)"
                        class="restart-badge"
                        title="Requires API restart">restart</span>
                </label>
                <p v-if="field.hint" class="field-hint">{{ field.hint }}</p>
                <p v-if="fieldErrors[`${section.id}.${field.key}`]" class="field-err" role="alert">
                  {{ fieldErrors[`${section.id}.${field.key}`] }}
                </p>
              </div>
              <div class="field-input-wrap">
                <template v-if="field.type === 'checkbox'">
                  <label class="toggle-label">
                    <input
                      :id="`f-${section.id}-${field.key}`"
                      type="checkbox"
                      class="toggle-checkbox"
                      v-model="form[section.id][field.key]"
                    />
                    <span class="toggle-track">
                      <span class="toggle-thumb" />
                    </span>
                    <span class="toggle-text">{{ form[section.id][field.key] ? 'Enabled' : 'Disabled' }}</span>
                  </label>
                </template>
                <template v-else-if="field.type === 'select'">
                  <select
                    :id="`f-${section.id}-${field.key}`"
                    v-model="form[section.id][field.key]"
                    class="field-input"
                    :class="{
                      'field-changed': valueChanged(section.id, field.key),
                      'field-error':   !!fieldErrors[`${section.id}.${field.key}`],
                    }"
                  >
                    <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
                  </select>
                </template>
                <template v-else>
                  <input
                    :id="`f-${section.id}-${field.key}`"
                    v-model="form[section.id][field.key]"
                    :type="field.type"
                    :step="field.step"
                    class="field-input"
                    :class="{
                      'field-changed': valueChanged(section.id, field.key),
                      'field-error':   !!fieldErrors[`${section.id}.${field.key}`],
                    }"
                  />
                </template>
              </div>
            </div>
          </div>
        </Card>
      </template>
    </div>

    <!-- ── Create-token modal (Team J) ─────────────────────────── -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showCreateTokenModal"
          class="dialog-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-token-title"
          @click.self="closeCreateTokenModal"
        >
          <div class="dialog-box">
            <h3 id="create-token-title" class="dialog-title">Create bearer token</h3>

            <div v-if="!newTokenRaw" class="dialog-body">
              <p class="field-hint">
                The token's raw value is shown <strong>once</strong> and never
                retrievable afterwards. Copy it into a secret manager
                immediately after creation.
              </p>
              <div class="field-row dialog-field">
                <label for="new-token-label" class="field-label">Label</label>
                <input
                  id="new-token-label"
                  v-model="newTokenLabel"
                  type="text"
                  class="field-input"
                  placeholder="e.g. openwebui-bridge"
                  :disabled="creatingToken"
                />
              </div>
              <div class="field-row dialog-field">
                <label for="new-token-scope" class="field-label">Scope</label>
                <select
                  id="new-token-scope"
                  v-model="newTokenScope"
                  class="field-input"
                  :disabled="creatingToken"
                >
                  <option value="all">all (chat + admin)</option>
                  <option value="admin">admin (token CRUD only)</option>
                  <option value="v1-only">v1-only (chat / embed / etc.)</option>
                  <option value="read-only">read-only (probes + listings)</option>
                </select>
              </div>
            </div>

            <div v-else class="dialog-body">
              <p class="field-hint warning">
                Copy this token now — it will not be shown again.
              </p>
              <div class="raw-token-box mono" role="textbox" aria-readonly="true">
                {{ newTokenRaw }}
              </div>
              <button class="btn-ghost btn-small" type="button"
                      @click="copyTokenToClipboard">
                {{ newTokenCopied ? 'Copied' : 'Copy to clipboard' }}
              </button>
            </div>

            <div class="dialog-actions">
              <template v-if="!newTokenRaw">
                <button class="btn-ghost" type="button"
                        @click="closeCreateTokenModal" :disabled="creatingToken">
                  Cancel
                </button>
                <button class="btn-primary" type="button"
                        @click="submitCreateToken" :disabled="creatingToken">
                  {{ creatingToken ? 'Creating…' : 'Create token' }}
                </button>
              </template>
              <template v-else>
                <button class="btn-primary" type="button"
                        @click="closeCreateTokenModal">
                  I've saved this token; close
                </button>
              </template>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ── Revoke-token confirm modal ──────────────────────────── -->
    <ConfirmDialog
      v-model:open="showRevokeModal"
      title="Revoke token?"
      :message="`Revoke '${revokeTarget?.label ?? ''}'? Any client using this token will fail to authenticate immediately.`"
      :danger="true"
      confirm-label="Revoke"
      @confirm="confirmRevokeToken"
    />

    <!-- ── Auth info modal (How does this work?) ───────────────── -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showAuthInfoModal"
          class="dialog-overlay"
          role="dialog"
          aria-modal="true"
          @click.self="showAuthInfoModal = false"
        >
          <div class="dialog-box">
            <h3 class="dialog-title">How hal0 auth works</h3>
            <div class="dialog-body">
              <p class="field-hint">
                Two surfaces share the same identity model:
              </p>
              <ul class="field-hint">
                <li>
                  <strong>Browser sessions</strong> — Caddy basic_auth at the edge.
                  Caddy forwards <code class="mono">X-Forwarded-Email</code> to hal0
                  and OpenWebUI; both treat the header as the authenticated
                  identity. No second login.
                </li>
                <li>
                  <strong>Programmatic clients</strong> — send
                  <code class="mono">Authorization: Bearer hal0_…</code>. Tokens
                  are minted here, hashed with argon2id at
                  <code class="mono">/etc/hal0/tokens.toml</code>, and revocable
                  any time.
                </li>
              </ul>
              <p class="field-hint">
                The Caddy front + the <code class="mono">HAL0_AUTH_ENABLED=1</code>
                flag are wired together by <code class="mono">install.sh --auth=basic</code>.
                Toggling <code class="mono">HAL0_AUTH_ENABLED</code> alone (without
                Caddy in front) is intentionally NOT exposed in this UI — it would
                lock you out of the dashboard with no recovery path other than
                editing <code class="mono">/etc/hal0/api.env</code> by hand.
              </p>
            </div>
            <div class="dialog-actions">
              <button class="btn-primary" type="button"
                      @click="showAuthInfoModal = false">Got it</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.settings-page { display: flex; flex-direction: column; min-height: 100%; }
.page-body     { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }

.restart-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 24px;
  background: color-mix(in oklch, var(--color-warning) 14%, var(--color-surface));
  border-bottom: 1px solid color-mix(in oklch, var(--color-warning) 30%, transparent);
  color: var(--color-warning);
  font-size: 13px;
}
.banner-btn {
  margin-left: auto;
  padding: 4px 12px;
  border-radius: var(--radius);
  background: var(--color-warning);
  color: var(--color-bg);
  font-size: 12px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  flex-shrink: 0;
}
.banner-btn:hover { opacity: 0.9; }
.slide-up-enter-active { transition: all 0.2s ease; }
.slide-up-leave-active { transition: all 0.15s ease; }
.slide-up-enter-from   { opacity: 0; transform: translateY(-100%); }
.slide-up-leave-to     { opacity: 0; transform: translateY(-100%); }

.error-banner { padding: 10px 16px; border-radius: var(--radius-lg); background: color-mix(in oklch, var(--color-danger) 10%, var(--color-surface)); border: 1px solid color-mix(in oklch, var(--color-danger) 30%, transparent); color: var(--color-danger); font-size: 13px; }

.section-title { font-size: 13px; font-weight: 600; color: var(--color-fg-muted); margin: 0 0 14px; letter-spacing: 0.02em; }

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

.change-count { font-family: var(--font-mono); font-size: 11.5px; color: var(--color-warning); }
.mono { font-family: var(--font-mono); }

.btn-primary { display: flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: var(--radius); background: var(--color-accent); color: var(--color-bg); font-size: 13px; font-weight: 600; border: none; cursor: pointer; }
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-ghost { padding: 7px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 13px; cursor: pointer; }
.btn-ghost:hover:not(:disabled) { background: var(--color-surface-2); color: var(--color-fg); }
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }

.spinner { width: 11px; height: 11px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Authentication panel ────────────────────────────────────────────── */

.auth-header { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.auth-status-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.auth-badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.auth-on  { background: color-mix(in oklch, var(--color-success) 18%, transparent); color: var(--color-success); border: 1px solid color-mix(in oklch, var(--color-success) 30%, transparent); }
.auth-off { background: color-mix(in oklch, var(--color-warning) 16%, transparent); color: var(--color-warning); border: 1px solid color-mix(in oklch, var(--color-warning) 30%, transparent); }
.auth-identity { font-size: 11.5px; color: var(--color-fg-muted); }

.auth-disabled-hint {
  padding: 10px 12px;
  border-radius: var(--radius);
  background: color-mix(in oklch, var(--color-warning) 8%, var(--color-surface-2));
  border: 1px solid color-mix(in oklch, var(--color-warning) 22%, transparent);
  color: var(--color-fg-muted);
  font-size: 12.5px;
  line-height: 1.55;
}
.auth-disabled-hint code { padding: 1px 5px; border-radius: 3px; background: var(--color-surface-3); color: var(--color-fg); }

.tokens-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.subsection-title { font-size: 12.5px; font-weight: 600; color: var(--color-fg); margin: 0 0 4px; }

.loading-row, .empty-row {
  padding: 12px;
  text-align: center;
  font-size: 12px;
  color: var(--color-fg-faint);
  background: var(--color-surface-2);
  border-radius: var(--radius);
}

.token-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.token-table th {
  text-align: left;
  font-weight: 500;
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-fg-faint);
  padding: 6px 8px;
  border-bottom: 1px solid var(--color-border);
}
.token-table td {
  padding: 8px;
  border-bottom: 1px solid color-mix(in oklch, var(--color-border) 60%, transparent);
}
.token-table tr:last-child td { border-bottom: none; }
.token-table .dim { color: var(--color-fg-faint); font-size: 11.5px; }
.scope-badge {
  display: inline-block;
  padding: 1px 7px;
  font-size: 10.5px;
  font-family: var(--font-mono);
  border-radius: 3px;
  background: var(--color-surface-3);
  color: var(--color-fg-muted);
  border: 1px solid var(--color-border);
}
.row-actions { text-align: right; }

.btn-small { padding: 4px 10px; font-size: 11.5px; }
.btn-danger {
  border: 1px solid color-mix(in oklch, var(--color-danger) 40%, var(--color-border));
  background: transparent;
  color: var(--color-danger);
  border-radius: var(--radius);
  cursor: pointer;
}
.btn-danger:hover:not(:disabled) {
  background: color-mix(in oklch, var(--color-danger) 12%, transparent);
}

/* ── Modal styling (mirrors ConfirmDialog.vue) ──────────────────────── */
.dialog-overlay {
  position: fixed; inset: 0;
  background: color-mix(in oklch, var(--color-bg) 70%, transparent);
  backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center;
  z-index: 50;
}
.dialog-box {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  width: 100%;
  max-width: 460px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
}
.dialog-title { font-size: 14px; font-weight: 600; margin: 0 0 12px; color: var(--color-fg); }
.dialog-body { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; font-size: 13px; }
.dialog-body code { padding: 1px 5px; border-radius: 3px; background: var(--color-surface-3); }
.dialog-body ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; }
.dialog-field { display: flex; flex-direction: column; gap: 4px; align-items: stretch; grid-template-columns: none; }
.dialog-actions { display: flex; gap: 8px; justify-content: flex-end; }

.field-hint.warning { color: var(--color-warning); }
.raw-token-box {
  padding: 10px 12px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border-hi);
  border-radius: var(--radius);
  font-size: 12px;
  word-break: break-all;
  user-select: all;
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.12s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
