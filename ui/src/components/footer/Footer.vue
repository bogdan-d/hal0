<script setup>
/**
 * Footer.vue — bottom dock shell.
 *
 *   ┌─ resize handle (3px, drag) ─┐
 *   ├─ expanded pane ─────────────┤   (when expanded)
 *   ├─ collapsed bar (28px) ──────┤
 *
 * Bar always rendered. Pane mounts only when expanded. Mobile (<768px):
 *   - bar only when collapsed
 *   - full-screen sheet when expanded (no drag handle)
 *
 * Footer is mounted at the App root and owns the shared SSE stream via
 * useEventsLifecycle() — every other consumer (tabs, etc) reads the same
 * ring.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useFooterStore } from '../../stores/footer.js'
import { useEventsLifecycle } from '../../composables/useEvents.js'
import FooterBar from './FooterBar.vue'
import FooterPane from './FooterPane.vue'

const footer = useFooterStore()

// Single owner of the events SSE — auto-stops on unmount.
const eventsApi = useEventsLifecycle()

// ── Mobile detection ───────────────────────────────────────────────
const isMobile = ref(false)
let mql = null
function syncViewport() {
  isMobile.value = mql ? mql.matches : window.matchMedia('(max-width: 768px)').matches
}

// ── Resize drag (desktop only) ─────────────────────────────────────
const dragging = ref(false)
let dragStartY = 0
let dragStartH = 0

function onHandleDown(e) {
  if (isMobile.value) return
  e.preventDefault()
  dragging.value = true
  dragStartY = e.clientY ?? (e.touches?.[0]?.clientY ?? 0)
  dragStartH = footer.height
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
  window.addEventListener('touchmove', onDragMove, { passive: false })
  window.addEventListener('touchend', onDragEnd)
}
function onDragMove(e) {
  if (!dragging.value) return
  if (e.preventDefault) e.preventDefault()
  const y = e.clientY ?? (e.touches?.[0]?.clientY ?? 0)
  const delta = dragStartY - y  // dragging up = positive delta = grow
  footer.setHeight(dragStartH + delta)
}
function onDragEnd() {
  dragging.value = false
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
  window.removeEventListener('touchmove', onDragMove)
  window.removeEventListener('touchend', onDragEnd)
}

// ── Total reserved height (for grid-template-rows feedback) ───────
// Bar (28px) + (pane height when expanded).
const totalHeight = computed(() => {
  if (isMobile.value) return 28  // mobile uses overlay sheet, not grid row
  return 28 + (footer.expanded ? footer.height : 0)
})

// Emit so App can adjust grid row.
const emit = defineEmits(['reserve-height'])
watch(totalHeight, (h) => emit('reserve-height', h), { immediate: true })

onMounted(async () => {
  mql = window.matchMedia('(max-width: 768px)')
  syncViewport()
  mql.addEventListener('change', syncViewport)
  await eventsApi.start()
})
onBeforeUnmount(() => {
  mql?.removeEventListener('change', syncViewport)
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
})
</script>

<template>
  <div
    class="footer"
    :class="{
      expanded: footer.expanded,
      mobile: isMobile,
      dragging,
    }"
    :style="!isMobile && footer.expanded ? { '--pane-h': footer.height + 'px' } : null"
  >
    <!-- Mobile backdrop when sheet open -->
    <div
      v-if="isMobile && footer.expanded"
      class="m-backdrop"
      aria-hidden="true"
      @click="footer.collapse()"
    />

    <div class="footer-stack" :class="{ 'm-sheet': isMobile && footer.expanded }">
      <!-- Resize handle (desktop only, when expanded) -->
      <div
        v-if="footer.expanded && !isMobile"
        class="handle"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize footer"
        @mousedown="onHandleDown"
        @touchstart="onHandleDown"
      ></div>

      <!-- Expanded pane -->
      <div
        v-if="footer.expanded"
        class="pane-host"
        :style="!isMobile ? { height: footer.height + 'px' } : null"
      >
        <FooterPane />
      </div>

      <!-- Always-visible collapsed bar -->
      <FooterBar @toggle="footer.toggleExpanded()" />
    </div>
  </div>
</template>

<style scoped>
.footer {
  grid-column: 1 / -1;
  grid-row: 3;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
  z-index: 30;
}
.footer-stack {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--color-bg);
}

.handle {
  height: 4px;
  cursor: ns-resize;
  background: transparent;
  border-top: 1px solid var(--color-border);
  position: relative;
  flex-shrink: 0;
}
.handle:hover, .footer.dragging .handle {
  background: color-mix(in srgb, var(--hal0-accent) 35%, transparent);
  border-top-color: var(--hal0-accent);
}
.handle::after {
  content: '';
  position: absolute;
  inset: -4px 0;  /* hit zone bigger than visible */
}

.pane-host {
  flex-shrink: 0;
  min-height: 0;
  display: flex;
}
.pane-host > * { width: 100%; }

/* ── Mobile sheet ───────────────────────────────────────────────── */
.footer.mobile.expanded .footer-stack.m-sheet {
  position: fixed;
  left: 0;
  right: 0;
  top: 44px;     /* below the topbar */
  bottom: 0;
  background: var(--color-surface);
  z-index: 50;
  flex-direction: column;
}
.footer.mobile.expanded .pane-host {
  flex: 1 1 auto;
  min-height: 0;
}
.m-backdrop {
  position: fixed;
  inset: 44px 0 0 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(2px);
  z-index: 45;
}
</style>
