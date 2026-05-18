<script setup>
/**
 * LogsTab.vue — log spelunker inside the footer pane.
 *
 * Sub-tabs: api / primary / embed / stt / tts / All. Custom slots from
 * /api/slots are appended after the built-ins.
 *
 * One /api/logs/stream open at a time. Swapped on sub-tab change. Closed
 * when this tab loses focus (Footer un-selects 'logs').
 *
 * Autoscroll w/ pause-on-up + "Jump to live" button. Copy-on-click.
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useFooterStore } from '../../../stores/footer.js'
import { useSystemStore } from '../../../stores/system.js'
import { useAutoscroll } from '../../../composables/useAutoscroll.js'
import { useToastsStore } from '../../../stores/toasts.js'

const footer = useFooterStore()
const system = useSystemStore()
const toasts = useToastsStore()
const { scrollEl, atBottom, jumpToLive, onContentAppended } = useAutoscroll()

const BUILTIN = ['api', 'primary', 'embed', 'stt', 'tts']

const subtabs = computed(() => {
  const slotNames = (system.slots || []).map((s) => s.name).filter(Boolean)
  const extras = slotNames.filter((n) => !BUILTIN.includes(n))
  return [...BUILTIN, ...extras, 'all']
})

const lines = ref([])
const connected = ref(false)
let es = null

function unitFor(subtab) {
  if (subtab === 'api') return 'hal0-api'
  if (subtab === 'all') return ''  // backend's 'all' is empty / '*'
  return `hal0-slot@${subtab}`
}

function openStream() {
  closeStream()
  lines.value = []
  const sub = footer.logsSubtab
  const unit = unitFor(sub)
  const level = footer.logsLevel
  const params = new URLSearchParams()
  if (unit) params.set('unit', unit)
  if (level) params.set('level', level)
  let url = `/api/logs/stream`
  const qs = params.toString()
  if (qs) url += `?${qs}`
  try {
    es = new EventSource(url)
  } catch {
    return
  }
  es.onopen = () => { connected.value = true }
  es.onmessage = (evt) => {
    let line = evt.data
    try {
      // Backend may JSON-encode the line string per the Logs.vue contract.
      const decoded = JSON.parse(line)
      if (typeof decoded === 'string') line = decoded
    } catch { /* raw text */ }
    lines.value.push(line)
    if (lines.value.length > 2000) lines.value = lines.value.slice(-2000)
    nextTick(onContentAppended)
  }
  es.onerror = () => { connected.value = false }
}

function closeStream() {
  if (es) { try { es.close() } catch {} es = null }
  connected.value = false
}

// Mount when this tab becomes visible.
onMounted(openStream)
onBeforeUnmount(closeStream)

watch(() => footer.logsSubtab, openStream)
watch(() => footer.logsLevel, openStream)

function lineClass(line) {
  if (/\bERROR\b|\bERR\b|\[ERROR\]/.test(line)) return 'line-error'
  if (/\bWARN(ING)?\b|\[WARN\]/.test(line))     return 'line-warn'
  if (/\bDEBUG\b|\[DEBUG\]/.test(line))         return 'line-debug'
  return ''
}

async function copyLine(text) {
  try {
    await navigator.clipboard.writeText(text)
    toasts.success('Line copied')
  } catch {
    toasts.error('Copy failed')
  }
}
</script>

<template>
  <div class="logs-tab">
    <div class="bar">
      <div class="sub-tabs" role="tablist" aria-label="Log sources">
        <button
          v-for="s in subtabs"
          :key="s"
          type="button"
          role="tab"
          :aria-selected="footer.logsSubtab === s"
          class="sub-tab"
          :class="{ active: footer.logsSubtab === s }"
          @click="footer.setLogsSubtab(s)"
        >{{ s }}</button>
      </div>
      <div class="bar-right">
        <select
          class="level-select mono"
          :value="footer.logsLevel"
          @change="footer.setLogsLevel($event.target.value)"
          aria-label="Filter by log level"
        >
          <option value="">all</option>
          <option value="info">info+</option>
          <option value="warn">warn+</option>
          <option value="error">error</option>
        </select>
        <span class="conn-dot" :class="{ ok: connected }" :title="connected ? 'streaming' : 'offline'"></span>
      </div>
    </div>
    <div ref="scrollEl" class="lines" role="log" aria-live="polite">
      <div v-if="lines.length === 0" class="empty mono">Waiting for log lines…</div>
      <div
        v-for="(line, i) in lines"
        :key="i"
        class="line"
        :class="lineClass(line)"
        :title="'Click to copy'"
        @click="copyLine(line)"
      >{{ line }}</div>
    </div>
    <button v-if="!atBottom" type="button" class="jump-btn" @click="jumpToLive">
      Jump to live ↓
    </button>
  </div>
</template>

<style scoped>
.logs-tab {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}
.bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  flex-shrink: 0;
  overflow-x: auto;
}
.sub-tabs { display: inline-flex; gap: 2px; flex: 1 1 auto; min-width: 0; }
.sub-tab {
  padding: 3px 9px;
  height: 22px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-fg-faint);
  cursor: pointer;
  white-space: nowrap;
}
.sub-tab:hover { color: var(--color-fg); background: var(--color-surface-2); }
.sub-tab.active {
  color: var(--hal0-accent);
  background: color-mix(in srgb, var(--hal0-accent) 12%, transparent);
  border-color: color-mix(in srgb, var(--hal0-accent) 30%, transparent);
}
.bar-right { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; }
.level-select {
  padding: 2px 6px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-fg);
  font-size: 10.5px;
}
.conn-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--color-fg-faint);
}
.conn-dot.ok { background: var(--color-success); box-shadow: 0 0 5px var(--color-success); }

.lines {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 6px 12px;
  background: var(--hal0-bg-sunken);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.55;
  min-height: 0;
}
.empty { color: var(--color-fg-faint); padding: 12px 0; text-align: center; }
.line {
  padding: 1px 0;
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-all;
  cursor: copy;
  border-bottom: 1px solid color-mix(in srgb, var(--color-border) 50%, transparent);
}
.line:hover { color: var(--color-fg); background: color-mix(in srgb, var(--color-surface-2) 60%, transparent); }
.line.line-warn  { color: var(--color-warning); }
.line.line-error { color: var(--color-danger); }
.line.line-debug { color: var(--color-fg-faint); opacity: 0.7; }

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
