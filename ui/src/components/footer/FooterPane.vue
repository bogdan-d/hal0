<script setup>
/**
 * FooterPane.vue — the expanded pane.
 *
 * Four top-level tabs: activity | slots | logs | jobs. Mounted only when
 * footer.expanded === true. LogsTab is keyed so its SSE tears down when
 * the user navigates away from the Logs tab (per the connection budget).
 */
import { computed } from 'vue'
import { useFooterStore } from '../../stores/footer.js'
import ActivityTab from './tabs/ActivityTab.vue'
import SlotsTab from './tabs/SlotsTab.vue'
import LogsTab from './tabs/LogsTab.vue'
import JobsTab from './tabs/JobsTab.vue'

const footer = useFooterStore()

const TABS = [
  { id: 'activity', label: 'Activity' },
  { id: 'slots',    label: 'Slots' },
  { id: 'logs',     label: 'Logs' },
  { id: 'jobs',     label: 'Jobs' },
]

const active = computed(() => footer.tab)
</script>

<template>
  <div
    id="hal0-footer-pane"
    class="pane"
    role="region"
    aria-label="Status panel"
  >
    <div class="tabs" role="tablist" aria-label="Footer tabs">
      <button
        v-for="t in TABS"
        :key="t.id"
        type="button"
        role="tab"
        :id="`footer-tab-${t.id}`"
        :aria-selected="active === t.id"
        :aria-controls="`footer-panel-${t.id}`"
        :tabindex="active === t.id ? 0 : -1"
        class="tab"
        :class="{ active: active === t.id }"
        @click="footer.setTab(t.id)"
      >{{ t.label }}</button>
    </div>

    <div class="panels">
      <div
        v-show="active === 'activity'"
        role="tabpanel"
        :aria-labelledby="'footer-tab-activity'"
        id="footer-panel-activity"
        class="panel"
      >
        <ActivityTab v-if="active === 'activity'" />
      </div>

      <div
        v-show="active === 'slots'"
        role="tabpanel"
        aria-labelledby="footer-tab-slots"
        id="footer-panel-slots"
        class="panel"
      >
        <SlotsTab v-if="active === 'slots'" />
      </div>

      <div
        v-show="active === 'logs'"
        role="tabpanel"
        aria-labelledby="footer-tab-logs"
        id="footer-panel-logs"
        class="panel"
      >
        <!-- key forces remount on every visit so the SSE wiring is fresh
             and old one is fully torn down (per connection budget). -->
        <LogsTab v-if="active === 'logs'" :key="`logs-${footer.logsSubtab}`" />
      </div>

      <div
        v-show="active === 'jobs'"
        role="tabpanel"
        aria-labelledby="footer-tab-jobs"
        id="footer-panel-jobs"
        class="panel"
      >
        <JobsTab v-if="active === 'jobs'" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.pane {
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  border-top: 1px solid var(--color-border);
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.tabs {
  display: flex;
  gap: 0;
  padding: 4px 8px 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  flex-shrink: 0;
}
.tab {
  padding: 6px 14px;
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--color-fg-faint);
  font-family: var(--font-mono);
  font-size: 11.5px;
  cursor: pointer;
  margin-bottom: -1px;
}
.tab:hover { color: var(--color-fg); }
.tab.active {
  color: var(--hal0-accent);
  border-bottom-color: var(--hal0-accent);
}
.panels {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.panel[hidden], .panel[v-show="false"] { display: none; }
</style>
