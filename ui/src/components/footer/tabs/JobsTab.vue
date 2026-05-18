<script setup>
/**
 * JobsTab.vue
 *
 * Top: in-flight model pulls with progress bar + cancel button.
 *      Cancel disabled when authRequired && !authed (placeholder for now).
 * Bottom: ~20 most recent finished pulls derived from events ring.
 */
import { computed } from 'vue'
import { useFooterStore } from '../../../stores/footer.js'
import { useSystemStore } from '../../../stores/system.js'
import { api } from '../../../composables/useApi.js'
import { useToastsStore } from '../../../stores/toasts.js'

const footer = useFooterStore()
const system = useSystemStore()
const toasts = useToastsStore()

const active = computed(() => footer.activeJobs)
const recent = computed(() => footer.recentFinishedJobs)

// Auth gating — backend may expose status.auth_required + status.authed.
// Fall back to "auth not required" so the dev/single-user box stays
// usable.
const writeBlocked = computed(() => {
  const s = system.status || {}
  return !!(s.auth_required && !s.authed)
})
const tooltipForBlocked = 'Authentication required to manage jobs'

function fmtBytes(b) {
  if (!b || b < 0) return '—'
  if (b < 1024) return `${b} B`
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(0)} KB`
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
  return `${(b / 1024 ** 3).toFixed(2)} GB`
}

async function cancelJob(job) {
  if (writeBlocked.value) return
  const id = job.model || job.id
  try {
    await api(`/api/models/${encodeURIComponent(id)}/pull/cancel`, { method: 'POST' })
    toasts.success(`Cancelled ${id}`)
  } catch (e) {
    toasts.error(e.message || 'Cancel failed')
  }
}

function stateLabel(j) {
  if (j.state === 'completed') return 'done'
  if (j.state === 'failed')    return 'failed'
  if (j.state === 'cancelled') return 'cancelled'
  return j.state
}
</script>

<template>
  <div class="jobs-tab">
    <section class="jobs-section">
      <h3 class="jobs-h">In flight</h3>
      <div v-if="active.length === 0" class="empty mono">No active pulls.</div>
      <div v-else class="rows">
        <div v-for="j in active" :key="j.id" class="job">
          <div class="job-head">
            <span class="mono job-name">{{ j.model || j.id }}</span>
            <span class="mono job-pct">{{ j.pct != null ? Math.round(j.pct) + '%' : '…' }}</span>
            <button
              type="button"
              class="cancel-btn"
              :disabled="writeBlocked"
              :title="writeBlocked ? tooltipForBlocked : 'Cancel pull'"
              @click="cancelJob(j)"
            >Cancel</button>
          </div>
          <div class="track" aria-hidden="true">
            <div class="fill" :style="{ width: (j.pct || 0) + '%' }"></div>
          </div>
          <div class="job-sub mono">
            <span>{{ stateLabel(j) }}</span>
            <span v-if="j.downloaded != null && j.total != null">
              · {{ fmtBytes(j.downloaded) }} / {{ fmtBytes(j.total) }}
            </span>
            <span v-if="j.message"> · {{ j.message }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="jobs-section">
      <h3 class="jobs-h">Recent</h3>
      <div v-if="recent.length === 0" class="empty mono">No finished pulls yet.</div>
      <div v-else class="rows compact">
        <div v-for="j in recent" :key="j.id + '-r'" class="job-row" :class="`state-${j.state}`">
          <span class="dot" :class="`state-${j.state}`" aria-hidden="true"></span>
          <span class="mono job-name">{{ j.model || j.id }}</span>
          <span class="mono job-meta">{{ stateLabel(j) }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.jobs-tab {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 10px 14px;
  background: var(--hal0-bg-sunken);
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}
.jobs-section { display: flex; flex-direction: column; gap: 6px; }
.jobs-h {
  font-family: var(--font-mono);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--hal0-accent);
  margin: 0;
}
.empty { color: var(--color-fg-faint); padding: 6px 0; }

.rows { display: flex; flex-direction: column; gap: 8px; }
.rows.compact { gap: 2px; }

.job {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.job-head { display: flex; align-items: center; gap: 8px; }
.job-name { font-size: 12px; color: var(--color-fg); flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; }
.job-pct  { font-feature-settings: 'zero' 1, 'tnum' 1; color: var(--hal0-accent); font-size: 11px; }
.cancel-btn {
  background: transparent;
  border: 1px solid var(--color-border-hi);
  border-radius: var(--radius-sm);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 2px 8px;
  cursor: pointer;
}
.cancel-btn:hover:not(:disabled) { color: var(--color-danger); border-color: var(--color-danger); }
.cancel-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.track {
  height: 5px;
  border-radius: 999px;
  background: var(--color-surface-2);
  overflow: hidden;
}
.fill { height: 100%; background: var(--hal0-accent); transition: width 0.25s ease; }
@media (prefers-reduced-motion: reduce) { .fill { transition: none; } }

.job-sub { font-size: 10.5px; color: var(--color-fg-faint); }

.job-row {
  display: grid;
  grid-template-columns: 8px 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 3px 4px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-border) 60%, transparent);
  font-size: 11px;
}
.job-row:last-child { border-bottom: none; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-fg-faint); }
.dot.state-completed { background: var(--color-success); }
.dot.state-failed    { background: var(--color-danger); }
.dot.state-cancelled { background: var(--color-warning); }
.job-meta { color: var(--color-fg-faint); text-transform: lowercase; font-size: 10.5px; }
.state-failed .job-name    { color: var(--color-danger); }
.state-completed .job-name { color: var(--color-fg); }
</style>
