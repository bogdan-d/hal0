<script setup>
/**
 * ActivityTab.vue — chronological feed of events from the shared ring.
 * Severity-colored rows. Auto-scroll w/ pause + jump-to-live.
 */
import { computed, watch, nextTick } from 'vue'
import { useFooterStore } from '../../../stores/footer.js'
import { useAutoscroll } from '../../../composables/useAutoscroll.js'

const footer = useFooterStore()
const { scrollEl, atBottom, jumpToLive, onContentAppended } = useAutoscroll()

const rows = computed(() => footer.events)

watch(rows, async () => {
  await nextTick()
  onContentAppended()
}, { deep: false, flush: 'post' })

function sevClass(s) {
  if (s === 'error') return 'sev-error'
  if (s === 'warn' || s === 'warning') return 'sev-warn'
  return 'sev-info'
}
function tsText(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString(undefined, { hour12: false })
}
</script>

<template>
  <div class="activity">
    <div ref="scrollEl" class="rows" role="log" aria-live="polite" aria-relevant="additions">
      <div v-if="rows.length === 0" class="empty mono">
        Waiting for events…
      </div>
      <div
        v-for="e in rows"
        :key="e.id"
        class="row"
        :class="sevClass(e.severity)"
      >
        <span class="ts mono">{{ tsText(e.ts) }}</span>
        <span class="type mono" :title="e.type">{{ e.type }}</span>
        <span class="msg">{{ e.message }}</span>
      </div>
    </div>
    <button
      v-if="!atBottom"
      type="button"
      class="jump-btn"
      @click="jumpToLive"
    >
      Jump to live ↓
    </button>
  </div>
</template>

<style scoped>
.activity {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}
.rows {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 6px 12px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.6;
  background: var(--hal0-bg-sunken);
}
.empty {
  color: var(--color-fg-faint);
  padding: 12px 0;
  text-align: center;
}
.row {
  display: grid;
  grid-template-columns: 64px 140px 1fr;
  gap: 10px;
  padding: 2px 0;
  border-bottom: 1px solid color-mix(in srgb, var(--color-border) 60%, transparent);
}
.row:last-child { border-bottom: none; }
.ts   { color: var(--color-fg-faint); font-feature-settings: 'zero' 1, 'tnum' 1; }
.type { color: var(--color-fg-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.msg  { color: var(--color-fg); word-break: break-word; }
.sev-warn  .msg { color: var(--color-warning); }
.sev-error .msg { color: var(--color-danger); }
.sev-warn  .type { color: var(--color-warning); }
.sev-error .type { color: var(--color-danger); }

.jump-btn {
  position: absolute;
  bottom: 12px;
  right: 14px;
  padding: 4px 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  border: 1px solid var(--color-border-hi);
  border-radius: 999px;
  background: var(--color-surface-2);
  color: var(--color-fg);
  cursor: pointer;
}
.jump-btn:hover { background: var(--color-surface-3); }
</style>
