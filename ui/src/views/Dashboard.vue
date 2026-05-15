<script setup>
/**
 * Dashboard.vue
 *
 * Design intent: operator at-a-glance view. The metric grid is primary;
 * slot cards secondary. Goal: answer "is my system healthy right now?"
 * in under 2 seconds without clicking anything.
 *
 * Layout: 4-column stat rail (status, slots, GPU mem, disk) →
 * horizontal slot summary cards → quick links to actions.
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '../stores/system.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const system = useSystemStore()

const hw = computed(() => system.hardware ?? {})

const slotSummary = computed(() => {
  const running = system.slots.filter((s) => s.status === 'running').length
  const total   = system.slots.length
  return { running, total }
})

// GPU/memory heuristic: prefer GTT (unified) when available, fallback to VRAM
const memUsedGb  = computed(() => {
  if (hw.value.gtt_used_mb)   return (hw.value.gtt_used_mb / 1024).toFixed(1)
  if (hw.value.vram_used_mb)  return (hw.value.vram_used_mb / 1024).toFixed(1)
  return null
})
const memTotalGb = computed(() => {
  if (hw.value.gtt_total_mb)  return (hw.value.gtt_total_mb / 1024).toFixed(0)
  if (hw.value.vram_total_mb) return (hw.value.vram_total_mb / 1024).toFixed(0)
  return null
})
const memLabel = computed(() => hw.value.gtt_total_mb ? 'GTT' : 'VRAM')

const diskUsedGb  = computed(() => hw.value.disk_used_gb?.toFixed(0) ?? null)
const diskTotalGb = computed(() => hw.value.disk_total_gb?.toFixed(0) ?? null)

// API health
const apiOk = computed(() => !system.error && system.status !== null)

// Recent logs: Phase 1 — from system store
const recentLogs = computed(() => system.status?.recent_logs ?? [])

const stateClass = (status) => ({
  running:  'state-running',
  ready:    'state-running',
  idle:     'state-idle',
  error:    'state-error',
  offline:  'state-offline',
  starting: 'state-idle',
  pulling:  'state-idle',
}[status] ?? 'state-offline')
</script>

<template>
  <div class="dashboard-page">
    <PageHeader
      title="Dashboard"
      subtitle="System overview"
    >
      <template #actions>
        <button class="btn-secondary" type="button" @click="system.fetchStatus()">
          <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          Refresh
        </button>
      </template>
    </PageHeader>

    <div class="page-body">
      <!-- ── Stat rail ──────────────────────────────────────────── -->
      <div class="stat-grid">
        <!-- API status -->
        <Card class="stat-card">
          <div class="stat-label">API status</div>
          <div class="stat-value" :class="apiOk ? 'text-success' : 'text-danger'">
            {{ apiOk ? 'Online' : 'Unreachable' }}
          </div>
          <div class="stat-sub">
            {{ system.loading ? 'Checking…' : (system.status?.version ? `v${system.status.version}` : 'unknown') }}
          </div>
        </Card>

        <!-- Slots -->
        <Card class="stat-card">
          <div class="stat-label">Slots running</div>
          <div class="stat-value">
            <template v-if="system.loading && system.slots.length === 0">
              <LoadingSkeleton :lines="1" height="28px" />
            </template>
            <template v-else>
              {{ slotSummary.running }}<span class="stat-denom">/{{ slotSummary.total }}</span>
            </template>
          </div>
          <div class="stat-sub">
            <button class="stat-link" type="button" @click="router.push('/slots')">
              Manage slots →
            </button>
          </div>
        </Card>

        <!-- GPU/GTT memory -->
        <Card class="stat-card">
          <div class="stat-label">{{ memLabel }} memory</div>
          <div class="stat-value">
            <template v-if="memUsedGb && memTotalGb">
              {{ memUsedGb }}<span class="stat-denom">/{{ memTotalGb }} GB</span>
            </template>
            <template v-else-if="system.loading">
              <LoadingSkeleton :lines="1" height="28px" />
            </template>
            <template v-else>
              <span class="text-muted">—</span>
            </template>
          </div>
          <div class="stat-sub">
            <button class="stat-link" type="button" @click="router.push('/hardware')">
              Hardware details →
            </button>
          </div>
        </Card>

        <!-- Disk -->
        <Card class="stat-card">
          <div class="stat-label">Model storage</div>
          <div class="stat-value">
            <template v-if="diskUsedGb && diskTotalGb">
              {{ diskUsedGb }}<span class="stat-denom">/{{ diskTotalGb }} GB</span>
            </template>
            <template v-else-if="system.loading">
              <LoadingSkeleton :lines="1" height="28px" />
            </template>
            <template v-else>
              <span class="text-muted">—</span>
            </template>
          </div>
          <div class="stat-sub">
            <button class="stat-link" type="button" @click="router.push('/models')">
              Browse models →
            </button>
          </div>
        </Card>
      </div>

      <!-- ── Slot summary ───────────────────────────────────────── -->
      <section aria-labelledby="slots-heading">
        <h2 id="slots-heading" class="section-title">Active slots</h2>

        <template v-if="system.loading && system.slots.length === 0">
          <div class="slot-list">
            <Card v-for="i in 3" :key="i"><LoadingSkeleton :lines="3" /></Card>
          </div>
        </template>

        <template v-else-if="system.slots.length === 0">
          <Card :padded="false">
            <EmptyState
              title="No slots configured"
              description="Create a slot to start serving inference requests."
              cta-label="Go to Slots"
              @cta="router.push('/slots')"
            />
          </Card>
        </template>

        <template v-else>
          <div class="slot-list">
            <Card
              v-for="slot in system.slots"
              :key="slot.name"
              class="slot-row"
              :padded="false"
            >
              <div class="slot-info">
                <span class="state-dot" :class="stateClass(slot.status)" aria-hidden="true" />
                <div class="slot-name-wrap">
                  <span class="slot-name">{{ slot.name }}</span>
                  <span v-if="slot.model" class="slot-model">{{ slot.model }}</span>
                </div>
              </div>
              <div class="slot-meta">
                <span class="mono-chip" v-if="slot.port">:{{ slot.port }}</span>
                <span class="state-label" :class="stateClass(slot.status)">{{ slot.status ?? 'offline' }}</span>
                <button
                  class="slot-action-btn"
                  type="button"
                  @click="router.push('/slots')"
                  aria-label="`Manage slot ${slot.name}`"
                >
                  Manage →
                </button>
              </div>
            </Card>
          </div>
        </template>
      </section>

      <!-- ── Recent logs (Phase 1) ─────────────────────────────── -->
      <section aria-labelledby="logs-heading">
        <h2 id="logs-heading" class="section-title">
          Recent log events
          <button class="stat-link section-link" type="button" @click="router.push('/logs')">
            View all →
          </button>
        </h2>
        <Card :padded="false">
          <div v-if="recentLogs.length === 0" class="logs-empty">
            <span class="text-muted mono-text">No recent log events — start a slot to see activity.</span>
          </div>
          <div v-else class="logs-list">
            <div v-for="(line, i) in recentLogs.slice(-10)" :key="i" class="log-line">
              {{ line }}
            </div>
          </div>
        </Card>
      </section>

      <!-- ── First-run nudge ────────────────────────────────────── -->
      <template v-if="!system.loading && system.slots.length === 0 && !system.error">
        <Card class="welcome-card" :padded="false">
          <div class="welcome-inner">
            <div class="welcome-icon" aria-hidden="true">🚀</div>
            <div class="welcome-text">
              <strong>Welcome to hal0</strong>
              <p>You haven't set up any inference slots yet. Run the first-time wizard to pick a model and get started.</p>
            </div>
            <button class="btn-primary" type="button" @click="router.push('/welcome')">
              Start setup wizard
            </button>
          </div>
        </Card>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page { display: flex; flex-direction: column; min-height: 100%; }
.page-body      { padding: 20px 24px; display: flex; flex-direction: column; gap: 24px; }

/* ── Stat rail ────────────────────────────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 480px) { .stat-grid { grid-template-columns: 1fr; } }

.stat-card { padding: 16px; }
.stat-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-fg-faint);
  font-family: var(--font-mono);
  margin-bottom: 6px;
}
.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--color-fg);
  line-height: 1;
  margin-bottom: 6px;
}
.stat-denom {
  font-size: 15px;
  color: var(--color-fg-muted);
  font-weight: 400;
}
.stat-sub {
  font-size: 11.5px;
  color: var(--color-fg-faint);
  font-family: var(--font-mono);
}
.stat-link {
  background: transparent;
  border: none;
  color: var(--color-accent);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.stat-link:hover { text-decoration: underline; }

/* ── Sections ─────────────────────────────────────────────────── */
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-fg-muted);
  letter-spacing: 0.03em;
  margin: 0 0 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.section-link { margin-left: auto; }

/* ── Slot summary list ────────────────────────────────────────── */
.slot-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.slot-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  gap: 12px;
}

.slot-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.state-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.state-running { background: var(--color-success); box-shadow: 0 0 6px -1px var(--color-success); }
.state-idle    { background: var(--color-warning); }
.state-error   { background: var(--color-danger); }
.state-offline { background: var(--color-fg-faint); }

.slot-name-wrap {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.slot-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-fg);
}
.slot-model {
  font-size: 11px;
  color: var(--color-fg-faint);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.slot-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.mono-chip {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  color: var(--color-fg-faint);
}

.state-label {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}
.state-label.state-running { background: color-mix(in oklch, var(--color-success) 15%, transparent); color: var(--color-success); }
.state-label.state-idle    { background: color-mix(in oklch, var(--color-warning) 15%, transparent); color: var(--color-warning); }
.state-label.state-error   { background: color-mix(in oklch, var(--color-danger) 15%, transparent); color: var(--color-danger); }
.state-label.state-offline { background: var(--color-surface-2); color: var(--color-fg-faint); }

.slot-action-btn {
  padding: 4px 10px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: 11.5px;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.slot-action-btn:hover { background: var(--color-surface-2); color: var(--color-fg); }

/* ── Logs ─────────────────────────────────────────────────────── */
.logs-empty {
  padding: 20px 16px;
  display: flex;
  align-items: center;
}
.logs-list {
  padding: 8px 0;
  max-height: 200px;
  overflow-y: auto;
}
.log-line {
  padding: 3px 16px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-all;
  border-bottom: 1px solid var(--color-border);
}
.log-line:last-child { border-bottom: none; }

/* ── Welcome card ─────────────────────────────────────────────── */
.welcome-card { border-color: var(--color-accent-bg); }
.welcome-inner {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  flex-wrap: wrap;
}
.welcome-icon { font-size: 28px; }
.welcome-text { flex: 1; min-width: 0; }
.welcome-text strong { color: var(--color-fg); font-size: 14px; }
.welcome-text p { font-size: 13px; color: var(--color-fg-muted); margin: 4px 0 0; }

/* ── Utility ──────────────────────────────────────────────────── */
.text-success { color: var(--color-success); }
.text-danger  { color: var(--color-danger); }
.text-muted   { color: var(--color-fg-faint); }
.mono-text    { font-family: var(--font-mono); font-size: 12px; }

.btn-primary {
  padding: 8px 18px;
  border-radius: var(--radius);
  background: var(--color-accent);
  color: var(--color-bg);
  font-size: 13px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  flex-shrink: 0;
}
.btn-primary:hover { opacity: 0.88; }

.btn-secondary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.btn-secondary:hover { background: var(--color-surface-2); color: var(--color-fg); }
</style>
