<script setup>
/**
 * Variant C — Two-pane, hardware-grounded.
 * Left rail: live hardware probe + live disk projection bar + per-backend
 *   "what would run here" rollup. Updates as right-rail picks change.
 * Right rail: question stack flowing top to bottom. No step indicator —
 *   the user just answers in order, the left rail reacts.
 *
 * The premise: every decision is grounded in the actual machine, so the
 * operator never has to mentally map "12 GB embedding model" onto their
 * disk + RAM. The bar moves.
 */
import { ref, computed } from 'vue'
import { useFirstRunState } from './useFirstRunState.js'
import CapabilityToggle from '../capabilities/CapabilityToggle.vue'

const s = useFirstRunState()
const showRerank = ref(false)
const installing = ref(false)
const done = ref(false)

const memUsedGb = computed(() => s.totalDownloadGb.value)
const memTotalGb = computed(() => Math.round((s.hardware.value?.unified_memory_mb || 1) / 1024))
const memPct = computed(() => Math.min(100, (memUsedGb.value / Math.max(1, memTotalGb.value)) * 100))

const diskPct = computed(() => {
  const free = s.diskFreeGb.value || 1
  return Math.min(100, (s.totalDownloadGb.value / free) * 100)
})

const onBackend = computed(() => {
  const groups = {}
  const add = (b, label) => { if (!b) return; (groups[b] ||= []).push(label) }
  if (s.form.caps.embed.enabled)  add(s.form.caps.embed.backend,  `embed → ${s.form.caps.embed.model}`)
  if (s.form.caps.rerank.enabled) add(s.form.caps.rerank.backend, `rerank → ${s.form.caps.rerank.model}`)
  if (s.form.caps.stt.enabled)    add(s.form.caps.stt.backend,    `stt → ${s.form.caps.stt.model}`)
  if (s.form.caps.tts.enabled)    add(s.form.caps.tts.backend,    `tts → ${s.form.caps.tts.model}`)
  if (s.form.caps.img.enabled)    add(s.form.caps.img.backend,    `img → ${s.form.caps.img.model}`)
  return groups
})

const ready = computed(() =>
  !!s.primaryModel.value && s.form.licenseAccepted && s.fits.value && !installing.value,
)

async function startInstall() {
  installing.value = true
  await s.applyAll()
  done.value = true
  installing.value = false
}

function fmtGb(n) { return `${(n || 0).toFixed(1)} GB` }
function selectKey(cap) { return cap.backend && cap.model ? `${cap.backend}::${cap.model}` : '' }
</script>

<template>
  <div class="vc-page">
    <div v-if="s.loading.value" class="vc-loading">Probing your machine…</div>

    <div v-else class="vc-grid">
      <!-- Left rail: live machine + projection -->
      <aside class="vc-rail">
        <div class="vc-rail-section">
          <div class="vc-rail-eyebrow">Detected</div>
          <h3 class="vc-rail-title">{{ s.hardware.value?.cpu_model || 'Unknown CPU' }}</h3>
          <div class="vc-rail-rows">
            <div><span class="vc-l">Memory</span><span>{{ memTotalGb }} GB unified</span></div>
            <div><span class="vc-l">GPU</span><span>{{ s.hardware.value?.gpu_name || '—' }}</span></div>
            <div><span class="vc-l">NPU</span><span :class="{ 'vc-good': s.hardware.value?.npu_present }">{{ s.hardware.value?.npu_present ? s.hardware.value?.npu_name : 'none' }}</span></div>
          </div>
        </div>

        <div class="vc-rail-section">
          <div class="vc-rail-eyebrow">Disk · {{ s.form.modelDir }}</div>
          <div class="vc-meter">
            <div class="vc-meter-bar"><div class="vc-meter-fill" :class="{ 'vc-meter-over': !s.fits.value }" :style="{ width: diskPct + '%' }" /></div>
            <div class="vc-meter-labels">
              <span>{{ fmtGb(s.totalDownloadGb.value) }} download</span>
              <span>{{ fmtGb(s.diskFreeGb.value) }} free</span>
            </div>
          </div>
          <p v-if="!s.fits.value" class="vc-warn">Will not fit. Reduce capabilities or free space.</p>
        </div>

        <div class="vc-rail-section">
          <div class="vc-rail-eyebrow">Memory budget (projected)</div>
          <div class="vc-meter">
            <div class="vc-meter-bar"><div class="vc-meter-fill" :style="{ width: memPct + '%' }" /></div>
            <div class="vc-meter-labels">
              <span>{{ fmtGb(memUsedGb) }} models</span>
              <span>{{ memTotalGb }} GB total</span>
            </div>
          </div>
        </div>

        <div class="vc-rail-section">
          <div class="vc-rail-eyebrow">What lands where</div>
          <div v-if="Object.keys(onBackend).length === 0" class="vc-empty">nothing enabled yet</div>
          <div v-for="(items, backend) in onBackend" :key="backend" class="vc-backend">
            <div class="vc-backend-head">{{ backend }}</div>
            <ul>
              <li v-for="x in items" :key="x">{{ x }}</li>
            </ul>
          </div>
        </div>
      </aside>

      <!-- Right rail: question stack -->
      <main class="vc-main">
        <header class="vc-head">
          <span class="vc-eyebrow">First run · Variant C — Two-pane</span>
          <h1 class="vc-title">Tell hal0 what to run</h1>
          <p class="vc-sub">The left panel shows your machine; right panel asks the questions. Decisions stay grounded in real numbers.</p>
        </header>

        <!-- Password -->
        <section v-if="!s.form.passwordAlreadySet" class="vc-q">
          <h2 class="vc-q-title">1 · Dashboard password</h2>
          <p class="vc-q-desc">Optional. Empty = run open on a trusted LAN.</p>
          <input v-model="s.form.password" class="vc-input" type="password" placeholder="at least 8 characters" autocomplete="new-password" />
        </section>

        <!-- Storage -->
        <section class="vc-q">
          <h2 class="vc-q-title">{{ s.form.passwordAlreadySet ? '1' : '2' }} · Where models live</h2>
          <p class="vc-q-desc">The disk meter on the left updates as you change this.</p>
          <input v-model="s.form.modelDir" class="vc-input vc-mono" />
          <p class="vc-hint">Add additional roots later in Settings → Storage.</p>
        </section>

        <!-- Chat model -->
        <section class="vc-q">
          <h2 class="vc-q-title">{{ s.form.passwordAlreadySet ? '2' : '3' }} · Primary chat model</h2>
          <p class="vc-q-desc">Powers /v1/chat/completions. You can swap or add later.</p>
          <div class="vc-models" role="radiogroup">
            <label v-for="m in s.curated.value" :key="m.id" class="vc-model" :class="{ on: s.form.primaryId === m.id }">
              <input type="radio" class="vc-sr" name="vc-primary" :value="m.id" v-model="s.form.primaryId" />
              <div class="vc-model-row">
                <span class="vc-model-name">{{ m.display_name }}</span>
                <span class="vc-model-size">{{ fmtGb(m.size_gb) }}</span>
              </div>
              <p class="vc-model-desc">{{ m.description }}</p>
            </label>
          </div>
        </section>

        <!-- Capabilities -->
        <section class="vc-q">
          <h2 class="vc-q-title">{{ s.form.passwordAlreadySet ? '3' : '4' }} · Capabilities</h2>
          <p class="vc-q-desc">Toggle = run at startup. Model picker stays editable either way — flip on later from /slots.</p>

          <div class="vc-cap">
            <div class="vc-cap-head">
              <div>
                <div class="vc-cap-name">embed</div>
                <div class="vc-cap-sub">text → vector · /v1/embeddings</div>
              </div>
              <CapabilityToggle v-model="s.form.caps.embed.enabled" label="enable embed" />
            </div>
            <select class="vc-select" :value="selectKey(s.form.caps.embed)"
              @change="s.setCapModel('embed', 'embed', 'embed', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('embed', 'embed')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
            <button class="vc-disclosure" type="button" @click="showRerank = !showRerank">
              {{ showRerank ? '▾' : '▸' }} Advanced: rerank
            </button>
            <div v-if="showRerank" class="vc-cap-nested">
              <div class="vc-cap-head">
                <div>
                  <div class="vc-cap-name vc-cap-name-sm">rerank</div>
                  <div class="vc-cap-sub">query+doc → score · /v1/rerankings</div>
                </div>
                <CapabilityToggle v-model="s.form.caps.rerank.enabled" label="enable rerank" />
              </div>
              <select class="vc-select" :value="selectKey(s.form.caps.rerank)"
                @change="s.setCapModel('rerank', 'embed', 'rerank', $event.target.value)">
                <option value="" disabled>pick model…</option>
                <option v-for="o in s.optionsFor('embed', 'rerank')" :key="`${o.backend}::${o.id}`"
                  :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
              </select>
            </div>
          </div>

          <div class="vc-cap">
            <div class="vc-cap-head">
              <div>
                <div class="vc-cap-name">voice · stt</div>
                <div class="vc-cap-sub">speech → text · /v1/audio/transcriptions</div>
              </div>
              <CapabilityToggle v-model="s.form.caps.stt.enabled" label="enable stt" />
            </div>
            <select class="vc-select" :value="selectKey(s.form.caps.stt)"
              @change="s.setCapModel('stt', 'voice', 'stt', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('voice', 'stt')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
          </div>

          <div class="vc-cap">
            <div class="vc-cap-head">
              <div>
                <div class="vc-cap-name">voice · tts</div>
                <div class="vc-cap-sub">text → speech · /v1/audio/speech</div>
              </div>
              <CapabilityToggle v-model="s.form.caps.tts.enabled" label="enable tts" />
            </div>
            <select class="vc-select" :value="selectKey(s.form.caps.tts)"
              @change="s.setCapModel('tts', 'voice', 'tts', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('voice', 'tts')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
          </div>

          <div class="vc-cap">
            <div class="vc-cap-head">
              <div>
                <div class="vc-cap-name">img</div>
                <div class="vc-cap-sub">text → image · /v1/images/generations</div>
              </div>
              <CapabilityToggle v-model="s.form.caps.img.enabled" label="enable img" />
            </div>
            <select class="vc-select" :value="selectKey(s.form.caps.img)"
              @change="s.setCapModel('img', 'img', 'img', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('img', 'img')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
          </div>
        </section>

        <!-- HF token (auto) -->
        <section v-if="s.gatedModels.value.length > 0" class="vc-q vc-q-warn">
          <h2 class="vc-q-title">⚠ Hugging Face token required</h2>
          <p class="vc-q-desc">{{ s.gatedModels.value.length }} selected model(s) are gated.</p>
          <input v-model="s.form.hfToken" class="vc-input vc-mono" placeholder="hf_…" />
        </section>

        <!-- Licenses + install -->
        <section v-if="s.enabledList.value.length > 0" class="vc-q">
          <h2 class="vc-q-title">License + install</h2>
          <ul class="vc-license-list">
            <li v-for="x in s.enabledList.value" :key="x.label">
              <span>{{ x.label }}</span>
              <span class="vc-faint">{{ fmtGb(x.size_gb) }}</span>
            </li>
          </ul>
          <label class="vc-accept">
            <input type="checkbox" v-model="s.form.licenseAccepted" />
            I accept the licenses for each model shown above.
          </label>
          <button class="vc-btn vc-btn-cta" type="button" :disabled="!ready" @click="startInstall">
            {{ installing ? 'Installing…' : done ? 'Done ✓' : `Install · ${fmtGb(s.totalDownloadGb.value)}` }}
          </button>
          <div v-if="installing || done" class="vc-pull-list">
            <div v-for="it in s.pull.items" :key="it.label" class="vc-pull">
              <div class="vc-pull-row"><span>{{ it.label }}</span><span class="vc-pull-pct">{{ it.pct }}%</span></div>
              <div class="vc-pull-bar"><div class="vc-pull-fill" :style="{ width: it.pct + '%' }" /></div>
            </div>
          </div>
          <div v-if="done" class="vc-done-row">
            <a class="vc-btn" :href="`${location.protocol}//${location.hostname}:3001`">Open chat →</a>
            <a class="vc-btn-ghost" href="/">Go to dashboard</a>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.vc-page { min-height: 100%; background: var(--hal0-bg); }
.vc-loading { padding: 60px; text-align: center; color: var(--color-fg-faint); }
.vc-grid { display: grid; grid-template-columns: 320px 1fr; min-height: 100vh; }
@media (max-width: 880px) {
  .vc-grid { grid-template-columns: 1fr; }
}

/* Left rail */
.vc-rail { background: var(--color-surface); border-right: 1px solid var(--color-border); padding: 24px 18px; display: flex; flex-direction: column; gap: 22px; position: sticky; top: 0; align-self: start; max-height: 100vh; overflow-y: auto; }
.vc-rail-section { display: flex; flex-direction: column; gap: 10px; }
.vc-rail-eyebrow { font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); }
.vc-rail-title { font-size: 13px; color: var(--color-fg); margin: 0; font-family: var(--font-mono); }
.vc-rail-rows { display: flex; flex-direction: column; gap: 4px; font-family: var(--font-mono); font-size: 11.5px; }
.vc-rail-rows > div { display: flex; justify-content: space-between; }
.vc-l { color: var(--color-fg-faint); }
.vc-good { color: var(--color-success); }

.vc-meter { display: flex; flex-direction: column; gap: 4px; }
.vc-meter-bar { height: 6px; background: var(--color-surface-3); border-radius: 3px; overflow: hidden; border: 1px solid var(--color-border); }
.vc-meter-fill { height: 100%; background: var(--hal0-accent); transition: width 0.25s ease; }
.vc-meter-over { background: var(--color-danger); }
.vc-meter-labels { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 10.5px; color: var(--color-fg-faint); }

.vc-empty { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-faint); font-style: italic; }
.vc-backend { font-family: var(--font-mono); font-size: 11px; }
.vc-backend-head { color: var(--hal0-accent); padding: 4px 6px; background: color-mix(in srgb, var(--hal0-accent) 10%, transparent); border-radius: 4px; display: inline-block; margin-bottom: 4px; }
.vc-backend ul { list-style: none; padding: 0; margin: 0; color: var(--color-fg-muted); }
.vc-backend li { padding-left: 8px; border-left: 1px solid var(--color-border); margin: 2px 0; }

.vc-warn { font-size: 11px; color: var(--color-danger); margin: 0; }

/* Right pane */
.vc-main { padding: 32px 36px 80px; max-width: 720px; }
.vc-head { margin-bottom: 32px; }
.vc-eyebrow { display: inline-block; padding: 3px 10px; border: 1px solid var(--hal0-border); border-radius: 999px; font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); margin-bottom: 12px; }
.vc-title { font-size: 26px; margin: 0 0 6px; color: var(--color-fg); letter-spacing: -0.02em; }
.vc-sub { font-size: 13px; color: var(--color-fg-muted); margin: 0; line-height: 1.6; }

.vc-q { padding: 22px 0; border-top: 1px solid var(--color-border); display: flex; flex-direction: column; gap: 10px; }
.vc-q:first-of-type { border-top: 0; }
.vc-q-warn { background: color-mix(in srgb, var(--color-warning) 6%, transparent); border-radius: var(--radius-lg); padding: 16px; border-top: 0; border: 1px solid color-mix(in srgb, var(--color-warning) 30%, var(--color-border)); }
.vc-q-title { font-size: 16px; margin: 0; color: var(--color-fg); font-weight: 600; letter-spacing: -0.01em; }
.vc-q-desc { font-size: 12.5px; color: var(--color-fg-muted); margin: 0; }
.vc-hint { font-size: 11px; color: var(--color-fg-faint); margin: 0; }
.vc-faint { color: var(--color-fg-faint); }

.vc-input { padding: 9px 11px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg); font-size: 13px; }
.vc-mono { font-family: var(--font-mono); font-size: 12.5px; }

.vc-models { display: flex; flex-direction: column; gap: 6px; }
.vc-model { border: 1px solid var(--color-border); border-radius: var(--radius); padding: 10px 12px; cursor: pointer; background: var(--color-surface); }
.vc-model.on { border-color: var(--hal0-accent); box-shadow: inset 3px 0 0 var(--hal0-accent); }
.vc-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
.vc-model-row { display: flex; justify-content: space-between; }
.vc-model-name { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; color: var(--color-fg); }
.vc-model-size { font-family: var(--font-mono); font-size: 11px; color: var(--hal0-accent); }
.vc-model-desc { font-size: 11.5px; color: var(--color-fg-muted); margin: 4px 0 0; }

.vc-cap { border: 1px solid var(--color-border); border-radius: var(--radius); padding: 12px; background: var(--color-surface); display: flex; flex-direction: column; gap: 8px; }
.vc-cap-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.vc-cap-name { font-family: var(--font-mono); font-weight: 600; font-size: 13px; color: var(--color-fg); }
.vc-cap-name-sm { font-size: 12px; }
.vc-cap-sub { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-faint); }
.vc-select { padding: 7px 9px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg); font-family: var(--font-mono); font-size: 12px; }
.vc-disclosure { background: transparent; border: 0; color: var(--color-fg-muted); cursor: pointer; font-size: 11.5px; text-align: left; padding: 0; font-family: var(--font-mono); }
.vc-cap-nested { border-top: 1px dashed var(--color-border); padding-top: 8px; display: flex; flex-direction: column; gap: 6px; }

.vc-license-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.vc-license-list li { display: flex; justify-content: space-between; padding: 6px 10px; border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface-2); font-family: var(--font-mono); font-size: 12px; }
.vc-accept { display: flex; gap: 8px; font-size: 12.5px; color: var(--color-fg-muted); padding: 8px 0; }
.vc-pull-list { display: flex; flex-direction: column; gap: 6px; }
.vc-pull { padding: 8px 10px; border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface); }
.vc-pull-row { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 12px; }
.vc-pull-pct { color: var(--hal0-accent); }
.vc-pull-bar { height: 5px; background: var(--color-surface-3); border-radius: 3px; overflow: hidden; margin-top: 4px; }
.vc-pull-fill { height: 100%; background: var(--hal0-accent); transition: width 0.3s ease; }
.vc-done-row { display: flex; gap: 8px; padding-top: 8px; }

.vc-btn { padding: 10px 18px; border-radius: var(--radius); background: var(--hal0-accent); color: #000; border: 0; font-family: var(--font-mono); font-size: 13px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; }
.vc-btn-cta { margin-top: 6px; }
.vc-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.vc-btn-ghost { padding: 9px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-family: var(--font-mono); font-size: 12px; cursor: pointer; text-decoration: none; }
</style>
