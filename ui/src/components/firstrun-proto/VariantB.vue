<script setup>
/**
 * Variant B — Progressive single-page.
 * Everything on one scrollable surface. Collapsible sections.
 * Sticky bottom Install bar shows live totals (download / disk / model count).
 *
 * IA: one page, sections in order — hardware, password, chat, capabilities,
 * HF (conditional inline), licenses (inline preview). Install button is sticky.
 */
import { ref, computed } from 'vue'
import { useFirstRunState } from './useFirstRunState.js'
import CapabilityToggle from '../capabilities/CapabilityToggle.vue'

const s = useFirstRunState()
const open = ref({
  hw: true,
  pw: !s.form.passwordAlreadySet,
  chat: true,
  caps: true,
  rerank: false,
})
const installing = ref(false)
const done = ref(false)

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
  <div class="vb-page">
    <header class="vb-head">
      <span class="vb-eyebrow">First run · Variant B — Single page</span>
      <h1 class="vb-title">Set up hal0</h1>
      <p class="vb-sub">All decisions on one page. Scroll, review, install.</p>
    </header>

    <main v-if="!s.loading.value" class="vb-main">
      <!-- Hardware + storage -->
      <section class="vb-section">
        <button class="vb-sec-head" type="button" @click="open.hw = !open.hw">
          <span class="vb-sec-chev">{{ open.hw ? '▾' : '▸' }}</span>
          <span class="vb-sec-title">Detected hardware &amp; storage</span>
          <span class="vb-sec-meta">{{ s.hardware.value?.npu_present ? 'NPU detected' : 'No NPU' }} · {{ fmtGb(s.diskFreeGb.value) }} free</span>
        </button>
        <div v-if="open.hw" class="vb-sec-body">
          <div class="vb-hw">
            <div><span class="vb-l">CPU</span><span>{{ s.hardware.value?.cpu_model || '—' }}</span></div>
            <div><span class="vb-l">Memory</span><span>{{ Math.round((s.hardware.value?.unified_memory_mb || 0) / 1024) }} GB unified</span></div>
            <div><span class="vb-l">GPU</span><span>{{ s.hardware.value?.gpu_name || '—' }}</span></div>
            <div><span class="vb-l">NPU</span><span>{{ s.hardware.value?.npu_present ? s.hardware.value?.npu_name : '—' }}</span></div>
          </div>
          <label class="vb-field-label" for="vb-dir">Model storage directory</label>
          <input id="vb-dir" v-model="s.form.modelDir" class="vb-input vb-mono" />
          <p class="vb-hint">Add additional roots later in Settings → Storage.</p>
        </div>
      </section>

      <!-- Password -->
      <section v-if="!s.form.passwordAlreadySet" class="vb-section">
        <button class="vb-sec-head" type="button" @click="open.pw = !open.pw">
          <span class="vb-sec-chev">{{ open.pw ? '▾' : '▸' }}</span>
          <span class="vb-sec-title">Password (optional)</span>
          <span class="vb-sec-meta">{{ s.form.password ? 'set' : 'skip — leave open' }}</span>
        </button>
        <div v-if="open.pw" class="vb-sec-body">
          <input v-model="s.form.password" class="vb-input" type="password" placeholder="at least 8 characters" autocomplete="new-password" />
          <p class="vb-hint">Empty = run open on a trusted LAN. Change later in Settings → Authentication.</p>
        </div>
      </section>

      <!-- Primary chat -->
      <section class="vb-section">
        <button class="vb-sec-head" type="button" @click="open.chat = !open.chat">
          <span class="vb-sec-chev">{{ open.chat ? '▾' : '▸' }}</span>
          <span class="vb-sec-title">Primary chat model</span>
          <span class="vb-sec-meta">{{ s.primaryModel.value ? s.primaryModel.value.display_name : 'none picked' }}</span>
        </button>
        <div v-if="open.chat" class="vb-sec-body">
          <div class="vb-models" role="radiogroup">
            <label v-for="m in s.curated.value" :key="m.id" class="vb-model" :class="{ on: s.form.primaryId === m.id }">
              <input type="radio" class="vb-sr" name="vb-primary" :value="m.id" v-model="s.form.primaryId" />
              <div class="vb-model-row">
                <span class="vb-model-name">{{ m.display_name }}</span>
                <span class="vb-model-size">{{ fmtGb(m.size_gb) }}</span>
              </div>
              <p class="vb-model-desc">{{ m.description }}</p>
            </label>
          </div>
        </div>
      </section>

      <!-- Capabilities -->
      <section class="vb-section">
        <button class="vb-sec-head" type="button" @click="open.caps = !open.caps">
          <span class="vb-sec-chev">{{ open.caps ? '▾' : '▸' }}</span>
          <span class="vb-sec-title">Capabilities</span>
          <span class="vb-sec-meta">
            {{ [s.form.caps.embed.enabled && 'embed', s.form.caps.stt.enabled && 'stt', s.form.caps.tts.enabled && 'tts', s.form.caps.img.enabled && 'img'].filter(Boolean).join(', ') || 'none on' }}
          </span>
        </button>
        <div v-if="open.caps" class="vb-sec-body vb-caps">
          <!-- embed -->
          <div class="vb-cap">
            <div class="vb-cap-head">
              <span class="vb-cap-name">embed</span>
              <CapabilityToggle v-model="s.form.caps.embed.enabled" label="enable embed" />
            </div>
            <select class="vb-select" :value="selectKey(s.form.caps.embed)"
              @change="s.setCapModel('embed', 'embed', 'embed', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('embed', 'embed')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
            <button class="vb-disclosure" type="button" @click="open.rerank = !open.rerank">
              {{ open.rerank ? '▾' : '▸' }} Advanced: rerank
            </button>
            <div v-if="open.rerank" class="vb-cap-nested">
              <div class="vb-cap-head">
                <span class="vb-cap-name vb-cap-name-sm">rerank</span>
                <CapabilityToggle v-model="s.form.caps.rerank.enabled" label="enable rerank" />
              </div>
              <select class="vb-select" :value="selectKey(s.form.caps.rerank)"
                @change="s.setCapModel('rerank', 'embed', 'rerank', $event.target.value)">
                <option value="" disabled>pick model…</option>
                <option v-for="o in s.optionsFor('embed', 'rerank')" :key="`${o.backend}::${o.id}`"
                  :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
              </select>
            </div>
          </div>

          <!-- voice (split) -->
          <div class="vb-cap">
            <div class="vb-cap-head">
              <span class="vb-cap-name">voice · stt</span>
              <CapabilityToggle v-model="s.form.caps.stt.enabled" label="enable stt" />
            </div>
            <select class="vb-select" :value="selectKey(s.form.caps.stt)"
              @change="s.setCapModel('stt', 'voice', 'stt', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('voice', 'stt')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
          </div>
          <div class="vb-cap">
            <div class="vb-cap-head">
              <span class="vb-cap-name">voice · tts</span>
              <CapabilityToggle v-model="s.form.caps.tts.enabled" label="enable tts" />
            </div>
            <select class="vb-select" :value="selectKey(s.form.caps.tts)"
              @change="s.setCapModel('tts', 'voice', 'tts', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('voice', 'tts')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
          </div>
          <div class="vb-cap">
            <div class="vb-cap-head">
              <span class="vb-cap-name">img</span>
              <CapabilityToggle v-model="s.form.caps.img.enabled" label="enable img" />
            </div>
            <select class="vb-select" :value="selectKey(s.form.caps.img)"
              @change="s.setCapModel('img', 'img', 'img', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('img', 'img')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
          </div>
        </div>
      </section>

      <!-- HF token (auto-shown) -->
      <section v-if="s.gatedModels.value.length > 0" class="vb-section vb-section-warn">
        <div class="vb-sec-head vb-sec-head-static">
          <span class="vb-sec-title">Hugging Face token required</span>
          <span class="vb-sec-meta">{{ s.gatedModels.value.length }} gated model(s)</span>
        </div>
        <div class="vb-sec-body">
          <input v-model="s.form.hfToken" class="vb-input vb-mono" placeholder="hf_…" />
          <p class="vb-hint">Read-only token. Stored in /etc/hal0/secrets.</p>
        </div>
      </section>

      <!-- License inline -->
      <section v-if="s.enabledList.value.length > 0" class="vb-section">
        <div class="vb-sec-head vb-sec-head-static">
          <span class="vb-sec-title">Licenses</span>
          <span class="vb-sec-meta">{{ s.enabledList.value.length }} model(s)</span>
        </div>
        <div class="vb-sec-body">
          <ul class="vb-license-list">
            <li v-for="x in s.enabledList.value" :key="x.label">
              <span>{{ x.label }}</span>
              <span class="vb-faint">{{ fmtGb(x.size_gb) }}</span>
            </li>
          </ul>
          <label class="vb-accept">
            <input type="checkbox" v-model="s.form.licenseAccepted" />
            I accept the licenses for each model shown above.
          </label>
        </div>
      </section>

      <!-- Install / progress / done embedded inline -->
      <section v-if="installing || done" class="vb-section vb-section-live">
        <div class="vb-sec-head vb-sec-head-static">
          <span class="vb-sec-title">{{ done ? 'Done' : 'Installing' }}</span>
        </div>
        <div class="vb-sec-body">
          <div v-for="it in s.pull.items" :key="it.label" class="vb-pull">
            <div class="vb-pull-row">
              <span>{{ it.label }}</span>
              <span class="vb-pull-pct">{{ it.pct }}%</span>
            </div>
            <div class="vb-pull-bar"><div class="vb-pull-fill" :style="{ width: it.pct + '%' }" /></div>
          </div>
          <div v-if="done" class="vb-done-row">
            <a class="vb-btn" :href="`${location.protocol}//${location.hostname}:3001`">Open chat →</a>
            <a class="vb-btn-ghost" href="/">Go to dashboard</a>
          </div>
        </div>
      </section>

      <div class="vb-spacer" aria-hidden="true" />
    </main>

    <!-- Sticky install bar -->
    <footer class="vb-bar">
      <div class="vb-bar-totals">
        <div><span class="vb-bar-l">Models</span><span>{{ s.enabledList.value.length }}</span></div>
        <div><span class="vb-bar-l">Total download</span><span :class="{ 'vb-bad': !s.fits.value }">{{ fmtGb(s.totalDownloadGb.value) }}</span></div>
        <div><span class="vb-bar-l">Free on disk</span><span>{{ fmtGb(s.diskFreeGb.value) }}</span></div>
      </div>
      <button class="vb-btn vb-btn-cta" type="button" :disabled="!ready" @click="startInstall">
        {{ installing ? 'Installing…' : done ? 'Done ✓' : 'Install' }}
      </button>
    </footer>
  </div>
</template>

<style scoped>
.vb-page { min-height: 100%; background: var(--hal0-bg); padding-bottom: 96px; }
.vb-head { padding: 28px 32px 16px; text-align: center; border-bottom: 1px solid var(--color-border); }
.vb-eyebrow { display: inline-block; padding: 3px 10px; border: 1px solid var(--hal0-border); border-radius: 999px; font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); margin-bottom: 10px; }
.vb-title { font-size: 24px; margin: 0 0 4px; color: var(--color-fg); letter-spacing: -0.02em; }
.vb-sub { font-size: 13px; color: var(--color-fg-muted); margin: 0; }

.vb-main { max-width: 720px; margin: 0 auto; padding: 18px 16px 0; display: flex; flex-direction: column; gap: 14px; }

.vb-section { border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); overflow: hidden; }
.vb-section-warn { border-color: color-mix(in srgb, var(--color-warning) 50%, var(--color-border)); }
.vb-section-live { border-color: var(--hal0-accent); }
.vb-sec-head { width: 100%; display: flex; align-items: center; gap: 10px; padding: 12px 14px; background: var(--color-surface-2); border: 0; cursor: pointer; text-align: left; }
.vb-sec-head-static { cursor: default; }
.vb-sec-chev { font-family: var(--font-mono); color: var(--color-fg-faint); width: 14px; }
.vb-sec-title { flex: 1; font-size: 13.5px; font-weight: 600; color: var(--color-fg); }
.vb-sec-meta { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-faint); }
.vb-sec-body { padding: 14px; display: flex; flex-direction: column; gap: 10px; border-top: 1px solid var(--color-border); }

.vb-hw { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; padding: 10px 12px; border-radius: var(--radius); background: var(--color-surface-2); border: 1px solid var(--color-border); font-family: var(--font-mono); font-size: 12px; }
.vb-hw > div { display: flex; justify-content: space-between; gap: 8px; }
.vb-l { color: var(--color-fg-faint); }

.vb-field-label { font-size: 12px; font-weight: 600; color: var(--color-fg-muted); margin-top: 4px; }
.vb-input { padding: 8px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg); font-size: 13px; }
.vb-mono { font-family: var(--font-mono); font-size: 12.5px; }
.vb-hint { font-size: 11px; color: var(--color-fg-faint); margin: 0; }
.vb-faint { color: var(--color-fg-faint); }

.vb-models { display: flex; flex-direction: column; gap: 6px; }
.vb-model { border: 1px solid var(--color-border); border-radius: var(--radius); padding: 10px 12px; cursor: pointer; background: var(--color-surface-2); }
.vb-model.on { border-color: var(--hal0-accent); box-shadow: inset 3px 0 0 var(--hal0-accent); }
.vb-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
.vb-model-row { display: flex; justify-content: space-between; }
.vb-model-name { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; color: var(--color-fg); }
.vb-model-size { font-family: var(--font-mono); font-size: 11px; color: var(--hal0-accent); }
.vb-model-desc { font-size: 11.5px; color: var(--color-fg-muted); margin: 4px 0 0; }

.vb-caps { gap: 12px; }
.vb-cap { border: 1px solid var(--color-border); border-radius: var(--radius); padding: 10px; background: var(--color-surface-2); display: flex; flex-direction: column; gap: 8px; }
.vb-cap-head { display: flex; align-items: center; justify-content: space-between; }
.vb-cap-name { font-family: var(--font-mono); font-weight: 600; font-size: 12.5px; color: var(--color-fg); }
.vb-cap-name-sm { font-size: 11.5px; }
.vb-select { padding: 6px 8px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-fg); font-family: var(--font-mono); font-size: 11.5px; }
.vb-disclosure { background: transparent; border: 0; color: var(--color-fg-muted); cursor: pointer; font-size: 11px; text-align: left; padding: 0; font-family: var(--font-mono); }
.vb-cap-nested { border-top: 1px dashed var(--color-border); padding-top: 6px; display: flex; flex-direction: column; gap: 6px; }

.vb-license-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.vb-license-list li { display: flex; justify-content: space-between; padding: 6px 10px; border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface-2); font-family: var(--font-mono); font-size: 12px; }
.vb-accept { display: flex; gap: 8px; font-size: 12.5px; color: var(--color-fg-muted); padding-top: 6px; }

.vb-pull { padding: 8px 10px; border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface-2); margin-bottom: 6px; }
.vb-pull-row { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 12px; }
.vb-pull-pct { color: var(--hal0-accent); }
.vb-pull-bar { height: 5px; background: var(--color-surface-3); border-radius: 3px; overflow: hidden; margin-top: 4px; }
.vb-pull-fill { height: 100%; background: var(--hal0-accent); transition: width 0.3s ease; }
.vb-done-row { display: flex; gap: 8px; padding-top: 8px; }

.vb-bar { position: fixed; left: 0; right: 0; bottom: 0; padding: 12px 18px; background: rgba(14,14,18,0.96); border-top: 1px solid var(--hal0-border); display: flex; align-items: center; gap: 18px; backdrop-filter: blur(8px); z-index: 50; }
.vb-bar-totals { display: flex; gap: 22px; flex: 1; font-family: var(--font-mono); font-size: 12px; color: var(--color-fg); }
.vb-bar-totals > div { display: flex; flex-direction: column; }
.vb-bar-l { font-size: 10px; color: var(--color-fg-faint); text-transform: uppercase; letter-spacing: 0.06em; }
.vb-bad { color: var(--color-danger); }
.vb-btn { padding: 10px 20px; border-radius: var(--radius); background: var(--hal0-accent); color: #000; border: 0; font-family: var(--font-mono); font-size: 13px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; }
.vb-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.vb-btn-cta { min-width: 130px; justify-content: center; }
.vb-btn-ghost { padding: 9px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-family: var(--font-mono); font-size: 12px; cursor: pointer; text-decoration: none; }
.vb-spacer { height: 24px; }
</style>
