<script setup>
/**
 * FirstRun — route shell.
 *
 * PROTOTYPE PHASE (2026-05): three IA variants compete on this route via
 * `?variant=A|B|C` plus the original wizard at `?variant=L`. The floating
 * PrototypeSwitcher is hidden in production builds; in production the
 * variant param is ignored and the Legacy wizard always renders, so a
 * stray merge can't ship the prototype to operators.
 *
 * After the user picks a winner: fold its render into this file, delete
 * components/firstrun-proto/, delete FirstRunLegacy.vue.
 *
 * Variants:
 *   L — Legacy (existing 5-step wizard, kept as production fallback + baseline)
 *   A — Linear wizard, more steps (8 discrete screens)
 *   B — Progressive single-page (collapsible sections + sticky install bar)
 *   C — Two-pane (live hardware + disk projection on the left, questions on the right)
 *
 * See components/firstrun-proto/NOTES.md for the question and how to evaluate.
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import FirstRunLegacy from './FirstRunLegacy.vue'
import VariantA from '../components/firstrun-proto/VariantA.vue'
import VariantB from '../components/firstrun-proto/VariantB.vue'
import VariantC from '../components/firstrun-proto/VariantC.vue'
import PrototypeSwitcher from '../components/firstrun-proto/PrototypeSwitcher.vue'

const route = useRoute()
const isProd = import.meta.env.PROD

const VARIANTS = [
  { key: 'L', name: 'Legacy (current wizard)',  component: FirstRunLegacy },
  { key: 'A', name: 'Linear, more steps',       component: VariantA },
  { key: 'B', name: 'Progressive single-page',  component: VariantB },
  { key: 'C', name: 'Two-pane, hw-grounded',    component: VariantC },
]

const currentKey = computed(() => {
  if (isProd) return 'L'
  const v = String(route.query.variant || 'A').toUpperCase()
  return VARIANTS.some((x) => x.key === v) ? v : 'A'
})
const currentComponent = computed(() => VARIANTS.find((v) => v.key === currentKey.value).component)
</script>

<template>
  <component :is="currentComponent" />
  <PrototypeSwitcher :variants="VARIANTS" :current="currentKey" />
</template>
