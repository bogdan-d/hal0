<script setup>
/**
 * SlotsTab.vue — dense grid of SlotCard components.
 *
 * Driven by:
 *   - system store's polled /api/slots data (5s)
 *   - slot.state events from the shared events ring (live transitions)
 *   - useSlotMetrics for the spark + tps numbers each card needs.
 *
 * Click "Manage" on a card → router-push to /slots.
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '../../../stores/system.js'
import { useSlotMetrics } from '../../../composables/useStats.js'
import SlotCard from '../../SlotCard.vue'

const router = useRouter()
const system = useSystemStore()
const { metrics, history } = useSlotMetrics(2500)

const slots = computed(() => system.slots || [])

function goManage() {
  router.push('/slots')
}
</script>

<template>
  <div class="slots-tab">
    <div v-if="slots.length === 0" class="empty">
      <p class="mono">No slots configured.</p>
      <button class="link-btn" type="button" @click="goManage">Configure slots →</button>
    </div>
    <div v-else class="grid">
      <SlotCard
        v-for="s in slots"
        :key="s.name"
        :slot="s"
        :metrics="metrics[s.name]"
        :spark-data="history[s.name] || { tps: [], pps: [] }"
        :models="[]"
        :selected-model="''"
        :action-loading="null"
        @logs="goManage"
        @edit="goManage"
        @action="goManage"
        @delete="goManage"
        @select-model="goManage"
      />
    </div>
  </div>
</template>

<style scoped>
.slots-tab {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 12px;
  background: var(--hal0-bg-sunken);
  min-height: 0;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 100%;
  color: var(--color-fg-faint);
}
.link-btn {
  background: transparent;
  border: 0;
  color: var(--hal0-accent);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 12px;
}
.link-btn:hover { text-decoration: underline; }
</style>
