<script setup>
/**
 * Variant A — Linear wizard, more steps.
 * 8 discrete steps. One decision per screen. Next/Back navigation.
 *
 * IA: password → hw+storage → primary → capabilities → hf? → license → pull → done
 */
import { ref, computed, watch } from 'vue'
import { useFirstRunState } from './useFirstRunState.js'
import CapabilityToggle from '../capabilities/CapabilityToggle.vue'

const s = useFirstRunState()
const step = ref(s.form.passwordAlreadySet ? 2 : 1)
const showRerank = ref(false)

const STEPS = [
  { n: 1, label: 'Password' },
  { n: 2, label: 'Hardware' },
  { n: 3, label: 'Chat' },
  { n: 4, label: 'Capabilities' },
  { n: 5, label: 'HF token' },
  { n: 6, label: 'License' },
  { n: 7, label: 'Install' },
  { n: 8, label: 'Done' },
]

const needsHfToken = computed(() => s.gatedModels.value.length > 0)
const canNextFromPrimary = computed(() => !!s.primaryModel.value)
const canStartPull = computed(() => s.form.licenseAccepted && s.fits.value)

function next() {
  // Skip HF step when no gated models selected
  if (step.value === 4 && !needsHfToken.value) { step.value = 6; return }
  step.value = Math.min(8, step.value + 1)
}
function back() {
  if (step.value === 6 && !needsHfToken.value) { step.value = 4; return }
  step.value = Math.max(1, step.value - 1)
}

watch(() => s.pull.done, (d) => { if (d) step.value = 8 })

function fmtGb(n) { return `${(n || 0).toFixed(1)} GB` }
function selectKey(cap) { return cap.backend && cap.model ? `${cap.backend}::${cap.model}` : '' }
</script>

<template>
  <div class="va-page">
    <div class="va-card">
      <header class="va-head">
        <span class="va-eyebrow">First run · Variant A — Linear wizard</span>
        <h1 class="va-title">Welcome to hal0</h1>
        <p class="va-sub">Local AI for your home. Eight quick steps.</p>
      </header>

      <ol class="va-steps" aria-label="Setup progress">
        <li v-for="st in STEPS" :key="st.n" class="va-step"
          :class="{ 'is-done': step > st.n, 'is-active': step === st.n }">
          <span class="va-step-num">{{ step > st.n ? '✓' : st.n }}</span>
          <span class="va-step-label">{{ st.label }}</span>
        </li>
      </ol>

      <div v-if="s.loading.value" class="va-body va-loading">Loading…</div>

      <!-- 1. Password -->
      <div v-else-if="step === 1" class="va-body">
        <p class="va-desc">Protect the dashboard + OpenAI-compatible API. Skip to run open on a trusted LAN.</p>
        <label class="va-field-label" for="va-pw">Password</label>
        <input id="va-pw" v-model="s.form.password" class="va-input" type="password" placeholder="at least 8 characters" autocomplete="new-password" />
        <p class="va-hint">You can set or change this later in Settings → Authentication.</p>
        <div class="va-foot va-foot-2">
          <button class="va-btn-ghost" type="button" @click="next">Skip — leave open</button>
          <button class="va-btn" type="button" :disabled="s.form.password.length > 0 && s.form.password.length < 8" @click="next">
            {{ s.form.password ? 'Set password →' : 'Next →' }}
          </button>
        </div>
      </div>

      <!-- 2. Hardware + storage -->
      <div v-else-if="step === 2" class="va-body">
        <p class="va-desc">We probed your hardware. Confirm where models go.</p>
        <div class="va-hw">
          <div class="va-hw-row"><span class="va-hw-l">CPU</span><span>{{ s.hardware.value?.cpu_model || '—' }}</span></div>
          <div class="va-hw-row"><span class="va-hw-l">Memory</span><span>{{ Math.round((s.hardware.value?.unified_memory_mb || 0) / 1024) }} GB unified</span></div>
          <div class="va-hw-row"><span class="va-hw-l">GPU</span><span>{{ s.hardware.value?.gpu_name || '—' }}</span></div>
          <div class="va-hw-row"><span class="va-hw-l">NPU</span><span>{{ s.hardware.value?.npu_present ? s.hardware.value?.npu_name : 'none detected' }}</span></div>
        </div>
        <label class="va-field-label" for="va-dir">Model storage directory</label>
        <input id="va-dir" v-model="s.form.modelDir" class="va-input va-input-mono" />
        <div class="va-disk">
          <span class="va-disk-l">Free here</span>
          <span class="va-disk-v">{{ fmtGb(s.diskFreeGb.value) }}</span>
        </div>
        <p class="va-hint">Add additional roots later in <strong>Settings → Storage</strong>.</p>
        <div class="va-foot va-foot-2">
          <button class="va-btn-ghost" type="button" @click="back">← Back</button>
          <button class="va-btn" type="button" @click="next">Next →</button>
        </div>
      </div>

      <!-- 3. Primary chat -->
      <div v-else-if="step === 3" class="va-body">
        <p class="va-desc">Pick the model that powers chat. You can swap or add more later.</p>
        <div class="va-models" role="radiogroup">
          <label v-for="m in s.curated.value" :key="m.id" class="va-model" :class="{ on: s.form.primaryId === m.id }">
            <input type="radio" class="va-sr" name="va-primary" :value="m.id" v-model="s.form.primaryId" />
            <div class="va-model-row">
              <span class="va-model-name">{{ m.display_name }}</span>
              <span class="va-model-size">{{ fmtGb(m.size_gb) }}</span>
            </div>
            <p class="va-model-desc">{{ m.description }}</p>
            <div class="va-model-meta">
              <span class="va-chip">{{ m.license }}</span>
              <span class="va-chip">{{ fmtGb(m.vram_gb_min) }} VRAM</span>
              <span v-for="t in m.tags" :key="t" class="va-chip va-chip-tag">{{ t }}</span>
            </div>
          </label>
        </div>
        <div class="va-foot va-foot-2">
          <button class="va-btn-ghost" type="button" @click="back">← Back</button>
          <button class="va-btn" type="button" :disabled="!canNextFromPrimary" @click="next">Next →</button>
        </div>
      </div>

      <!-- 4. Capabilities -->
      <div v-else-if="step === 4" class="va-body">
        <p class="va-desc">Pick which capabilities run at startup. Off = configured but not running — flip on later in /slots.</p>

        <!-- embed -->
        <section class="va-cap">
          <header class="va-cap-head">
            <div class="va-cap-l">
              <span class="va-cap-name">embed</span>
              <span class="va-cap-sub">text → vector · /v1/embeddings</span>
            </div>
            <CapabilityToggle v-model="s.form.caps.embed.enabled" label="enable embed" />
          </header>
          <select class="va-select" :value="selectKey(s.form.caps.embed)"
            @change="s.setCapModel('embed', 'embed', 'embed', $event.target.value)">
            <option value="" disabled>pick model…</option>
            <option v-for="o in s.optionsFor('embed', 'embed')" :key="`${o.backend}::${o.id}`"
              :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
          </select>
          <button class="va-disclosure" type="button" @click="showRerank = !showRerank">
            {{ showRerank ? '▾' : '▸' }} Advanced: rerank
          </button>
          <div v-if="showRerank" class="va-cap-nested">
            <header class="va-cap-head">
              <div class="va-cap-l">
                <span class="va-cap-name va-cap-name-sm">rerank</span>
                <span class="va-cap-sub">query+doc → score · /v1/rerankings</span>
              </div>
              <CapabilityToggle v-model="s.form.caps.rerank.enabled" label="enable rerank" />
            </header>
            <select class="va-select" :value="selectKey(s.form.caps.rerank)"
              @change="s.setCapModel('rerank', 'embed', 'rerank', $event.target.value)">
              <option value="" disabled>pick model…</option>
              <option v-for="o in s.optionsFor('embed', 'rerank')" :key="`${o.backend}::${o.id}`"
                :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
            </select>
          </div>
        </section>

        <!-- voice -->
        <section class="va-cap">
          <header class="va-cap-head">
            <div class="va-cap-l">
              <span class="va-cap-name">voice</span>
              <span class="va-cap-sub">speech in + out · stt + tts</span>
            </div>
          </header>
          <div class="va-sub-row">
            <span class="va-sub-name">stt · /v1/audio/transcriptions</span>
            <CapabilityToggle v-model="s.form.caps.stt.enabled" label="enable stt" />
          </div>
          <select class="va-select" :value="selectKey(s.form.caps.stt)"
            @change="s.setCapModel('stt', 'voice', 'stt', $event.target.value)">
            <option value="" disabled>pick model…</option>
            <option v-for="o in s.optionsFor('voice', 'stt')" :key="`${o.backend}::${o.id}`"
              :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
          </select>
          <div class="va-sub-row">
            <span class="va-sub-name">tts · /v1/audio/speech</span>
            <CapabilityToggle v-model="s.form.caps.tts.enabled" label="enable tts" />
          </div>
          <select class="va-select" :value="selectKey(s.form.caps.tts)"
            @change="s.setCapModel('tts', 'voice', 'tts', $event.target.value)">
            <option value="" disabled>pick model…</option>
            <option v-for="o in s.optionsFor('voice', 'tts')" :key="`${o.backend}::${o.id}`"
              :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
          </select>
        </section>

        <!-- img -->
        <section class="va-cap">
          <header class="va-cap-head">
            <div class="va-cap-l">
              <span class="va-cap-name">img</span>
              <span class="va-cap-sub">text → image · /v1/images/generations</span>
            </div>
            <CapabilityToggle v-model="s.form.caps.img.enabled" label="enable img" />
          </header>
          <select class="va-select" :value="selectKey(s.form.caps.img)"
            @change="s.setCapModel('img', 'img', 'img', $event.target.value)">
            <option value="" disabled>pick model…</option>
            <option v-for="o in s.optionsFor('img', 'img')" :key="`${o.backend}::${o.id}`"
              :value="`${o.backend}::${o.id}`">{{ o.backend }} / {{ o.id }} — {{ fmtGb(o.size_gb) }}</option>
          </select>
          <p v-if="s.form.caps.img.enabled" class="va-warn">Heavy: 7–12 GB pull + significant memory at runtime.</p>
        </section>

        <div class="va-foot va-foot-2">
          <button class="va-btn-ghost" type="button" @click="back">← Back</button>
          <button class="va-btn" type="button" @click="next">Next →</button>
        </div>
      </div>

      <!-- 5. HF token (conditional) -->
      <div v-else-if="step === 5" class="va-body">
        <p class="va-desc">One or more selected models are gated on Hugging Face. Provide a token or remove them.</p>
        <ul class="va-gated">
          <li v-for="m in s.gatedModels.value" :key="m.id">{{ m.display_name }}</li>
        </ul>
        <label class="va-field-label" for="va-hf">Hugging Face access token</label>
        <input id="va-hf" v-model="s.form.hfToken" class="va-input va-input-mono" placeholder="hf_…" />
        <p class="va-hint">Read-only token is enough. Stored in /etc/hal0/secrets.</p>
        <div class="va-foot va-foot-2">
          <button class="va-btn-ghost" type="button" @click="back">← Back</button>
          <button class="va-btn" type="button" @click="next">Next →</button>
        </div>
      </div>

      <!-- 6. License -->
      <div v-else-if="step === 6" class="va-body">
        <p class="va-desc">You're about to download these models. Confirm their licenses.</p>
        <ul class="va-license-list">
          <li v-for="x in s.enabledList.value" :key="x.label">
            <span class="va-license-name">{{ x.label }}</span>
            <span class="va-license-size">{{ fmtGb(x.size_gb) }}</span>
          </li>
        </ul>
        <div class="va-totals">
          <div><span class="va-tot-l">Total download</span><span class="va-tot-v">{{ fmtGb(s.totalDownloadGb.value) }}</span></div>
          <div><span class="va-tot-l">Free on {{ s.form.modelDir }}</span><span class="va-tot-v" :class="{ 'va-bad': !s.fits.value }">{{ fmtGb(s.diskFreeGb.value) }}</span></div>
        </div>
        <p v-if="!s.fits.value" class="va-err">Not enough disk. Free up space or remove capabilities.</p>
        <label class="va-accept">
          <input type="checkbox" v-model="s.form.licenseAccepted" />
          I accept the licenses for each model shown above.
        </label>
        <div class="va-foot va-foot-2">
          <button class="va-btn-ghost" type="button" @click="back">← Back</button>
          <button class="va-btn" type="button" :disabled="!canStartPull" @click="() => { next(); s.applyAll() }">Accept &amp; install →</button>
        </div>
      </div>

      <!-- 7. Install -->
      <div v-else-if="step === 7" class="va-body">
        <p class="va-desc">Pulling models. You can leave this tab open.</p>
        <div v-for="it in s.pull.items" :key="it.label" class="va-pull">
          <div class="va-pull-row">
            <span class="va-pull-name">{{ it.label }}</span>
            <span class="va-pull-pct">{{ it.pct }}%</span>
          </div>
          <div class="va-pull-bar"><div class="va-pull-fill" :style="{ width: it.pct + '%' }" /></div>
        </div>
      </div>

      <!-- 8. Done -->
      <div v-else-if="step === 8" class="va-body va-done">
        <div class="va-done-icon">✓</div>
        <h2 class="va-done-title">You're set</h2>
        <p class="va-done-desc">{{ s.enabledList.value.length }} models ready. Capabilities are warming up in the background.</p>
        <div class="va-done-actions">
          <a class="va-btn va-btn-wide" :href="`${location.protocol}//${location.hostname}:3001`">Open chat →</a>
          <a class="va-btn-ghost" href="/">Go to dashboard</a>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.va-page { min-height: 100%; padding: 32px 16px; background: var(--hal0-bg); display: flex; justify-content: center; }
.va-card { width: min(620px, 100%); background: var(--hal0-bg-elevated); border: 1px solid var(--hal0-border); border-radius: var(--radius-xl); overflow: hidden; }
.va-head { padding: 28px 28px 18px; text-align: center; border-bottom: 1px solid var(--color-border); }
.va-eyebrow { display: inline-block; padding: 3px 10px; border: 1px solid var(--hal0-border); border-radius: 999px; font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); margin-bottom: 14px; }
.va-title { font-size: 24px; margin: 0 0 4px; color: var(--color-fg); letter-spacing: -0.02em; }
.va-sub { font-size: 13px; color: var(--color-fg-muted); margin: 0; }

.va-steps { display: grid; grid-template-columns: repeat(8, 1fr); gap: 0; padding: 12px 24px; border-bottom: 1px solid var(--color-border); margin: 0; list-style: none; }
.va-step { display: flex; flex-direction: column; align-items: center; gap: 3px; position: relative; }
.va-step + .va-step::before { content: ''; position: absolute; left: -50%; top: 9px; width: 100%; height: 1px; background: var(--color-border); }
.va-step.is-done + .va-step::before { background: var(--hal0-accent); }
.va-step-num { width: 18px; height: 18px; border-radius: 50%; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-fg-faint); font-size: 10px; display: grid; place-items: center; font-family: var(--font-mono); position: relative; z-index: 1; }
.va-step.is-active .va-step-num { border-color: var(--hal0-accent); color: var(--hal0-accent); background: var(--color-accent-bg); }
.va-step.is-done   .va-step-num { background: var(--hal0-accent); color: #000; border-color: var(--hal0-accent); }
.va-step-label { font-size: 9px; color: var(--color-fg-faint); font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 0.05em; }
.va-step.is-active .va-step-label { color: var(--hal0-accent); }

.va-body { padding: 22px 28px 26px; display: flex; flex-direction: column; gap: 14px; }
.va-loading { color: var(--color-fg-faint); text-align: center; padding: 36px 0; }
.va-desc { font-size: 13px; color: var(--color-fg-muted); margin: 0; line-height: 1.55; }
.va-hint { font-size: 11px; color: var(--color-fg-faint); margin: 0; }
.va-err { font-size: 12px; color: var(--color-danger); margin: 4px 0 0; }
.va-warn { font-size: 11.5px; color: var(--color-warning); margin: 2px 0 0; }
.va-field-label { font-size: 12px; font-weight: 600; color: var(--color-fg-muted); }
.va-input { padding: 8px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg); font-size: 13px; }
.va-input-mono { font-family: var(--font-mono); font-size: 12.5px; }

.va-hw { display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: var(--radius); background: var(--color-surface-2); border: 1px solid var(--color-border); font-family: var(--font-mono); font-size: 12px; }
.va-hw-row { display: flex; justify-content: space-between; gap: 12px; }
.va-hw-l { color: var(--color-fg-faint); }
.va-disk { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 12px; color: var(--color-fg-muted); }

.va-models { display: flex; flex-direction: column; gap: 8px; }
.va-model { border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 12px 14px; cursor: pointer; background: var(--color-surface); }
.va-model.on { border-color: var(--hal0-accent); box-shadow: inset 3px 0 0 var(--hal0-accent); }
.va-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
.va-model-row { display: flex; justify-content: space-between; }
.va-model-name { font-family: var(--font-mono); font-weight: 600; color: var(--color-fg); font-size: 13px; }
.va-model-size { font-family: var(--font-mono); font-size: 11px; padding: 2px 7px; border-radius: 999px; background: color-mix(in srgb, var(--hal0-accent) 14%, transparent); color: var(--hal0-accent); }
.va-model-desc { font-size: 12px; color: var(--color-fg-muted); margin: 4px 0 6px; }
.va-model-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.va-chip { font-family: var(--font-mono); font-size: 10px; padding: 2px 6px; border-radius: 4px; background: var(--color-surface-3); color: var(--color-fg-faint); border: 1px solid var(--color-border); }

.va-cap { border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 12px; display: flex; flex-direction: column; gap: 8px; background: var(--color-surface); }
.va-cap-head { display: flex; align-items: center; justify-content: space-between; }
.va-cap-l { display: flex; flex-direction: column; }
.va-cap-name { font-family: var(--font-mono); font-weight: 600; color: var(--color-fg); font-size: 13px; }
.va-cap-name-sm { font-size: 12px; }
.va-cap-sub { font-size: 11px; color: var(--color-fg-faint); font-family: var(--font-mono); }
.va-select { padding: 7px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg); font-family: var(--font-mono); font-size: 12px; }
.va-disclosure { background: transparent; border: 0; color: var(--color-fg-muted); cursor: pointer; font-size: 11.5px; text-align: left; padding: 2px 0; font-family: var(--font-mono); }
.va-cap-nested { border-top: 1px dashed var(--color-border); padding-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.va-sub-row { display: flex; align-items: center; justify-content: space-between; padding-top: 6px; border-top: 1px dashed var(--color-border); }
.va-sub-name { font-family: var(--font-mono); font-size: 11.5px; color: var(--color-fg-muted); }

.va-gated { list-style: none; padding: 8px 12px; margin: 0; background: var(--color-surface-2); border-radius: var(--radius); border: 1px solid var(--color-border); font-family: var(--font-mono); font-size: 12px; }

.va-license-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.va-license-list li { display: flex; justify-content: space-between; padding: 6px 10px; border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface-2); font-family: var(--font-mono); font-size: 12px; }
.va-license-size { color: var(--color-fg-faint); }
.va-totals { display: flex; flex-direction: column; gap: 4px; font-family: var(--font-mono); font-size: 12px; padding: 8px 0; }
.va-totals > div { display: flex; justify-content: space-between; }
.va-tot-l { color: var(--color-fg-muted); }
.va-tot-v { color: var(--color-fg); }
.va-bad { color: var(--color-danger); }
.va-accept { display: flex; gap: 8px; font-size: 13px; color: var(--color-fg-muted); padding-top: 4px; }

.va-pull { padding: 8px 10px; border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface-2); margin-bottom: 6px; }
.va-pull-row { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 12px; }
.va-pull-name { color: var(--color-fg); }
.va-pull-pct { color: var(--hal0-accent); }
.va-pull-bar { height: 6px; background: var(--color-surface-3); border-radius: 3px; overflow: hidden; margin-top: 4px; }
.va-pull-fill { height: 100%; background: var(--hal0-accent); transition: width 0.3s ease; }

.va-done { align-items: center; text-align: center; }
.va-done-icon { width: 48px; height: 48px; border-radius: 50%; background: color-mix(in srgb, var(--hal0-accent) 14%, transparent); border: 2px solid var(--hal0-accent); color: var(--hal0-accent); font-size: 22px; display: grid; place-items: center; }
.va-done-title { font-size: 22px; margin: 8px 0 0; color: var(--color-fg); }
.va-done-desc { font-size: 13px; color: var(--color-fg-muted); margin: 0; }
.va-done-actions { display: flex; flex-direction: column; gap: 8px; width: 100%; align-items: center; padding-top: 8px; }

.va-foot { padding-top: 4px; }
.va-foot-2 { display: flex; justify-content: space-between; }
.va-btn { padding: 10px 18px; border-radius: var(--radius); background: var(--hal0-accent); color: #000; border: 0; font-family: var(--font-mono); font-size: 12.5px; font-weight: 500; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
.va-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.va-btn-wide { width: 100%; justify-content: center; }
.va-btn-ghost { padding: 9px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-family: var(--font-mono); font-size: 12px; cursor: pointer; text-decoration: none; }
.va-btn-ghost:hover { color: var(--color-fg); border-color: var(--color-border-hi); }
</style>
