<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSystemStore } from './stores/system.js'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import ToastContainer from './components/ToastContainer.vue'
import CommandPalette from './components/CommandPalette.vue'
import RestartBanner from './components/RestartBanner.vue'

const system = useSystemStore()
const route  = useRoute()
const router = useRouter()

// ── Responsive sidebar ────────────────────────────────────────────
// Desktop: sidebarOpen = expanded(true) / collapsed-icon-rail(false)
// Mobile (< md = 768px): off-canvas drawer
const isMobile    = ref(false)
const sidebarOpen = ref(true)
const cmdkOpen    = ref(false)

let mql = null
let pollInterval = null

function syncViewport(initial = false) {
  const mobile = mql ? mql.matches : window.matchMedia('(max-width: 768px)').matches
  if (mobile === isMobile.value && !initial) return
  isMobile.value = mobile
  sidebarOpen.value = !mobile  // default: open on desktop, closed on mobile
}

function handleKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    cmdkOpen.value = true
  } else if (e.key === 'Escape') {
    if (cmdkOpen.value) cmdkOpen.value = false
    else if (isMobile.value && sidebarOpen.value) sidebarOpen.value = false
  }
}

function onCmdkSelect(item) {
  cmdkOpen.value = false
  if (item?.to) router.push(item.to)
  else if (typeof item?.handler === 'function') item.handler()
}

// Close mobile drawer on navigation
watch(() => route.fullPath, () => {
  if (isMobile.value) sidebarOpen.value = false
})

onMounted(() => {
  mql = window.matchMedia('(max-width: 768px)')
  syncViewport(true)
  mql.addEventListener('change', syncViewport)
  window.addEventListener('keydown', handleKey)

  // Initial status fetch + 5s polling
  system.fetchStatus()
  pollInterval = setInterval(() => system.fetchStatus(), 5000)
})

onUnmounted(() => {
  clearInterval(pollInterval)
  mql?.removeEventListener('change', syncViewport)
  window.removeEventListener('keydown', handleKey)
})
</script>

<template>
  <div
    class="app-shell"
    :class="{
      'sidebar-collapsed': !sidebarOpen && !isMobile,
      'is-mobile': isMobile,
      'mobile-nav-open': isMobile && sidebarOpen,
    }"
  >
    <TopBar
      :is-mobile="isMobile"
      :sidebar-open="sidebarOpen"
      @toggle-sidebar="sidebarOpen = !sidebarOpen"
      @open-cmdk="cmdkOpen = true"
    />

    <Sidebar
      :open="sidebarOpen"
      :is-mobile="isMobile"
      @toggle="sidebarOpen = !sidebarOpen"
      @navigate="isMobile && (sidebarOpen = false)"
    />

    <!-- Mobile backdrop -->
    <div
      v-if="isMobile && sidebarOpen"
      class="mobile-backdrop"
      aria-hidden="true"
      @click="sidebarOpen = false"
    />

    <main class="app-main" id="main-content" tabindex="-1">
      <RestartBanner />
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <CommandPalette
      :open="cmdkOpen"
      @close="cmdkOpen = false"
      @select="onCmdkSelect"
    />

    <ToastContainer />
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 220px 1fr;
  grid-template-rows: 44px 1fr;
  height: 100vh;
  overflow: hidden;
  background: var(--color-bg);
}

.app-shell.sidebar-collapsed {
  grid-template-columns: 56px 1fr;
}

.app-main {
  grid-column: 2;
  grid-row: 2;
  overflow-y: auto;
  min-width: 0;
  min-height: 0;
}

/* ── Mobile (< 768px) ─────────────────────────────────────────── */
.app-shell.is-mobile {
  grid-template-columns: 1fr;
}

.app-shell.is-mobile .app-main {
  grid-column: 1;
}

.mobile-backdrop {
  position: fixed;
  inset: 44px 0 0 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(2px);
  z-index: 40;
  animation: bd-in 0.16s ease;
}

@keyframes bd-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
</style>
