<script setup>
/**
 * FirstRun.vue — First-run wizard.
 * 3-step: pick model → license accept → download + assign → done.
 * Designed as a centered card with a step indicator, not a full-page form.
 */
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useToastsStore } from '../stores/toasts.js'
import { useSystemStore } from '../stores/system.js'
import { api } from '../composables/useApi.js'
import { usePullJob, fmtBytes, fmtSpeed, fmtEta } from '../composables/usePullJob.js'

const router = useRouter()
const toasts = useToastsStore()
const system = useSystemStore()

const step = ref(1)  // 1 | 2 | 3 | 4 (done)

const MODELS = [
  { id: 'qwen3-4b',   name: 'Qwen3 4B',      size: '4.1 GB', vram: '4 GB',  license: 'Apache 2.0', desc: 'Fast, multilingual, vision-capable. Good all-rounder.' },
  { id: 'llama32-3b', name: 'Llama 3.2 3B',  size: '2.0 GB', vram: '2 GB',  license: 'Llama 3.2',  desc: 'Small and fast. Great for low-VRAM or quick testing.' },
  { id: 'phi3-mini',  name: 'Phi-3 Mini',    size: '2.4 GB', vram: '2.4 GB', license: 'MIT',        desc: 'Strong reasoning, efficient. MIT licensed.' },
  { id: 'custom',     name: 'Custom HF URL', size: '?',      vram: '?',     license: '?',          desc: 'Specify any GGUF model from HuggingFace.' },
]

const selectedModel = ref(null)
const customUrl     = ref('')
const customUrlErr  = ref('')
const licenseAccepted = ref(false)
const chatUrl       = ref('http://localhost:3001')

// Shared pull-job composable — same plumbing Models.vue uses, so the
// FirstRun progress bar and the Models inline progress bar drive off
// one source of truth (Team I gap #3).
const pull = usePullJob()
const downloadPct = computed(() => pull.pct.value ?? 0)
const downloading = computed(() => pull.inFlight.value)
const pullError   = computed(() => pull.error.value)

// Get chat URL from API (may differ from default if port is customized)
async function fetchChatUrl() {
  try {
    const data = await api('/api/config/urls')
    chatUrl.value = data?.openwebui_url ?? 'http://localhost:3001'
  } catch { /* use default */ }
}

function selectModel(m) {
  selectedModel.value = m
  licenseAccepted.value = false
}

function goStep2() {
  if (!selectedModel.value) { toasts.warning('Please select a model first'); return }
  if (selectedModel.value.id === 'custom' && !customUrl.value.trim()) {
    customUrlErr.value = 'Enter a HuggingFace repo URL'
    return
  }
  customUrlErr.value = ''
  step.value = 2
}

async function download() {
  if (!licenseAccepted.value) { toasts.warning('Please accept the license first'); return }
  step.value = 3

  try {
    // Custom HF URLs go through usePullJob with the hf_url body so the
    // backend resolves the repo at pull time. Curated picks pass the
    // model id directly.
    const id = selectedModel.value.id === 'custom'
      ? customUrl.value
      : selectedModel.value.id
    const body = selectedModel.value.id === 'custom'
      ? { hf_url: customUrl.value, slot: 'primary' }
      : { slot: 'primary' }
    await pull.start(id, body)
  } catch (e) {
    toasts.error(e.message)
    step.value = 2
    return
  }
}

// When the pull reaches a terminal state, advance the wizard.
watch(() => pull.state.value, async (s) => {
  if (s === 'completed') {
    await system.fetchStatus()
    await fetchChatUrl()
    step.value = 4
  } else if (s === 'failed') {
    toasts.error(pull.error.value?.message ?? 'Download failed')
    step.value = 2
  } else if (s === 'cancelled') {
    step.value = 2
  }
})

function goToDashboard() { router.push('/') }
function openChat()      { window.open(chatUrl.value, '_blank', 'noopener') }

const licenseLabel = computed(() => {
  if (!selectedModel.value || selectedModel.value.id === 'custom') return 'the model\'s license'
  return selectedModel.value.license
})
</script>

<template>
  <div class="wizard-page">
    <div class="wizard-card">
      <!-- Header -->
      <div class="wizard-head">
        <div class="wizard-logo" aria-hidden="true">h0</div>
        <h1 class="wizard-title">Welcome to hal0</h1>
        <p class="wizard-sub">Let's get your first model running.</p>
      </div>

      <!-- Step indicator -->
      <div class="steps" aria-label="Setup progress">
        <div
          v-for="(label, i) in ['Pick model', 'License', 'Install', 'Done']"
          :key="i"
          class="step"
          :class="{ 'step-done': step > i + 1, 'step-active': step === i + 1 }"
        >
          <span class="step-num" :aria-label="`Step ${i + 1}: ${label}`">{{ step > i + 1 ? '✓' : i + 1 }}</span>
          <span class="step-label">{{ label }}</span>
        </div>
      </div>

      <!-- ── Step 1: Pick model ─────────────────────────────── -->
      <div v-if="step === 1" class="wizard-body">
        <p class="step-desc">Choose a starting model. You can add more from the Models page later.</p>

        <div class="model-list" role="radiogroup" aria-label="Model selection">
          <label
            v-for="m in MODELS"
            :key="m.id"
            class="model-option"
            :class="{ selected: selectedModel?.id === m.id }"
          >
            <input
              type="radio"
              class="sr-only"
              name="model-pick"
              :value="m.id"
              :checked="selectedModel?.id === m.id"
              @change="selectModel(m)"
            />
            <div class="model-option-inner">
              <div class="model-option-header">
                <span class="model-option-name">{{ m.name }}</span>
                <span class="model-size-chip">{{ m.size }}</span>
              </div>
              <p class="model-option-desc">{{ m.desc }}</p>
              <div class="model-option-meta">
                <span class="meta-chip">{{ m.license }}</span>
                <span class="meta-chip">{{ m.vram }} VRAM</span>
              </div>
            </div>
          </label>
        </div>

        <div v-if="selectedModel?.id === 'custom'" class="custom-url-wrap">
          <label class="field-label" for="custom-hf-url">HuggingFace repo <span class="req">*</span></label>
          <input
            id="custom-hf-url"
            v-model="customUrl"
            class="field-input"
            :class="{ 'field-error': customUrlErr }"
            placeholder="org/model-name-GGUF"
            autocomplete="off"
          />
          <p v-if="customUrlErr" class="field-err">{{ customUrlErr }}</p>
        </div>

        <div class="wizard-footer">
          <button class="btn-primary btn-wide" type="button" :disabled="!selectedModel" @click="goStep2">
            Next: Review license →
          </button>
        </div>
      </div>

      <!-- ── Step 2: License ────────────────────────────────── -->
      <div v-if="step === 2" class="wizard-body">
        <p class="step-desc">
          You're about to download <strong>{{ selectedModel?.name }}</strong> under the <strong>{{ licenseLabel }}</strong> license.
          Please confirm you accept the terms.
        </p>

        <div class="license-card">
          <p class="license-text">
            By clicking "Accept &amp; download", you acknowledge that you are downloading this model under its stated license.
            hal0 does not modify or distribute model weights. You are responsible for compliance with the model's license terms in your jurisdiction.
          </p>
          <a
            v-if="selectedModel && selectedModel.id !== 'custom'"
            class="license-link"
            href="https://huggingface.co"
            target="_blank"
            rel="noopener noreferrer"
          >
            View license on HuggingFace ↗
          </a>
        </div>

        <label class="accept-label">
          <input type="checkbox" v-model="licenseAccepted" />
          I accept the {{ licenseLabel }} license
        </label>

        <div class="wizard-footer wizard-footer-2">
          <button class="btn-ghost" type="button" @click="step = 1">← Back</button>
          <button class="btn-primary" type="button" :disabled="!licenseAccepted || downloading" @click="download">
            Accept &amp; download
          </button>
        </div>
      </div>

      <!-- ── Step 3: Downloading ────────────────────────────── -->
      <div v-if="step === 3" class="wizard-body">
        <p class="step-desc">Downloading and assigning <strong>{{ selectedModel?.name }}</strong> to the <code class="inline-code">primary</code> slot.</p>

        <div class="progress-wrap" role="progressbar" :aria-valuenow="downloadPct" aria-valuemin="0" aria-valuemax="100">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: downloadPct + '%' }" />
          </div>
          <span class="progress-pct">{{ downloadPct }}%</span>
        </div>

        <p v-if="pull.total.value > 0" class="step-hint">
          {{ fmtBytes(pull.downloaded.value) }} / {{ fmtBytes(pull.total.value) }}
          <span v-if="pull.speedBps.value > 0">· {{ fmtSpeed(pull.speedBps.value) }}</span>
          <span v-if="pull.etaS.value > 0">· {{ fmtEta(pull.etaS.value) }} left</span>
        </p>
        <p v-else class="step-hint">This may take a few minutes depending on your connection speed. Slot will start automatically when download completes.</p>

        <div v-if="pullError" class="pull-error" role="alert">
          <span><strong>{{ pullError.code }}</strong>: {{ pullError.message }}</span>
        </div>

        <button v-if="downloading" class="btn-ghost" type="button" @click="pull.cancel()">
          Cancel download
        </button>
      </div>

      <!-- ── Step 4: Done ───────────────────────────────────── -->
      <div v-if="step === 4" class="wizard-body wizard-done">
        <div class="done-icon" aria-hidden="true">✓</div>
        <h2 class="done-title">You're all set!</h2>
        <p class="done-desc"><strong>{{ selectedModel?.name }}</strong> is loaded in the primary slot and ready to serve requests.</p>

        <div class="done-actions">
          <button class="btn-primary btn-wide" type="button" @click="openChat">
            Open chat →
          </button>
          <button class="btn-ghost" type="button" @click="goToDashboard">
            Go to dashboard
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wizard-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 32px 16px;
  background: var(--color-bg);
}

.wizard-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  width: min(560px, 100%);
  overflow: hidden;
}

.wizard-head {
  text-align: center;
  padding: 32px 32px 24px;
  border-bottom: 1px solid var(--color-border);
}
.wizard-logo {
  width: 48px; height: 48px; border-radius: 12px;
  background: var(--color-accent);
  color: var(--color-bg);
  font-family: var(--font-mono); font-size: 18px; font-weight: 500;
  display: grid; place-items: center; margin: 0 auto 16px;
}
.wizard-title { font-size: 22px; font-weight: 600; color: var(--color-fg); margin: 0 0 6px; }
.wizard-sub   { font-size: 14px; color: var(--color-fg-muted); margin: 0; }

/* Steps */
.steps {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 16px 32px;
  border-bottom: 1px solid var(--color-border);
}
.step {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  flex: 1;
  position: relative;
}
.step + .step::before {
  content: '';
  position: absolute; left: -50%; top: 10px;
  width: 100%; height: 1px;
  background: var(--color-border);
}
.step-done + .step::before { background: var(--color-accent); }
.step-num {
  width: 22px; height: 22px; border-radius: 50%;
  background: var(--color-surface-2); border: 1px solid var(--color-border);
  color: var(--color-fg-faint); font-size: 11px;
  display: grid; place-items: center; font-family: var(--font-mono);
  position: relative; z-index: 1;
}
.step-active .step-num { border-color: var(--color-accent); color: var(--color-accent); background: var(--color-accent-bg); }
.step-done .step-num   { background: var(--color-accent); color: var(--color-bg); border-color: var(--color-accent); }
.step-label { font-size: 10.5px; color: var(--color-fg-faint); font-family: var(--font-mono); }
.step-active .step-label { color: var(--color-accent); }

/* Body */
.wizard-body { padding: 24px 32px; display: flex; flex-direction: column; gap: 16px; }

.step-desc { font-size: 13.5px; color: var(--color-fg-muted); margin: 0; line-height: 1.6; }
.step-hint { font-size: 12px; color: var(--color-fg-faint); margin: 0; }

/* Model list */
.model-list { display: flex; flex-direction: column; gap: 8px; }
.model-option {
  border: 2px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color 0.1s;
}
.model-option:hover { border-color: var(--color-border-hi); }
.model-option.selected { border-color: var(--color-accent); }
.model-option-inner { padding: 12px 14px; }
.model-option-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.model-option-name { font-weight: 600; color: var(--color-fg); font-size: 13.5px; }
.model-size-chip { font-family: var(--font-mono); font-size: 11px; padding: 2px 6px; border-radius: 4px; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-fg-faint); }
.model-option-desc { font-size: 12px; color: var(--color-fg-muted); margin: 0 0 8px; }
.model-option-meta { display: flex; gap: 6px; }
.meta-chip { font-family: var(--font-mono); font-size: 10.5px; padding: 2px 6px; border-radius: 4px; background: var(--color-surface-3); color: var(--color-fg-faint); border: 1px solid var(--color-border); }

.custom-url-wrap { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 12.5px; font-weight: 600; color: var(--color-fg-muted); }
.req { color: var(--color-danger); }
.field-input { padding: 7px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg); font-size: 13px; outline: none; transition: border-color 0.1s; box-sizing: border-box; width: 100%; }
.field-input:focus { border-color: var(--color-border-hi); }
.field-error { border-color: var(--color-danger) !important; }
.field-err { font-size: 11.5px; color: var(--color-danger); margin: 0; }

/* License */
.license-card { background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 14px; }
.license-text { font-size: 12.5px; color: var(--color-fg-muted); margin: 0 0 8px; line-height: 1.6; }
.license-link { font-size: 12px; color: var(--color-accent); text-decoration: none; }
.license-link:hover { text-decoration: underline; }
.accept-label { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--color-fg-muted); cursor: pointer; }

/* Progress */
.progress-wrap { display: flex; align-items: center; gap: 12px; }
.progress-bar { flex: 1; height: 8px; background: var(--color-surface-3); border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--color-accent); border-radius: 4px; transition: width 0.3s ease; }
.progress-pct { font-family: var(--font-mono); font-size: 12px; color: var(--color-fg-muted); min-width: 36px; text-align: right; }

.pull-error {
  padding: 8px 12px;
  border-radius: var(--radius);
  background: color-mix(in oklch, var(--color-danger) 10%, transparent);
  border: 1px solid color-mix(in oklch, var(--color-danger) 30%, transparent);
  color: var(--color-danger);
  font-size: 12px;
}
.pull-error strong { font-family: var(--font-mono); }

/* Done */
.wizard-done { align-items: center; text-align: center; padding: 32px; }
.done-icon { width: 56px; height: 56px; border-radius: 50%; background: color-mix(in oklch, var(--color-success) 15%, var(--color-surface)); border: 2px solid var(--color-success); color: var(--color-success); font-size: 24px; display: grid; place-items: center; }
.done-title { font-size: 20px; font-weight: 600; color: var(--color-fg); margin: 0; }
.done-desc  { font-size: 13.5px; color: var(--color-fg-muted); margin: 0; line-height: 1.6; }
.done-actions { display: flex; flex-direction: column; gap: 10px; width: 100%; align-items: center; }

/* Footers */
.wizard-footer { padding-top: 4px; }
.wizard-footer-2 { display: flex; justify-content: space-between; align-items: center; }

/* Buttons */
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 20px; border-radius: var(--radius); background: var(--color-accent); color: var(--color-bg); font-size: 14px; font-weight: 600; border: none; cursor: pointer; transition: opacity 0.1s; }
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-wide { width: 100%; }
.btn-ghost { padding: 8px 16px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 13px; cursor: pointer; }
.btn-ghost:hover { background: var(--color-surface-2); color: var(--color-fg); }

.inline-code { font-family: var(--font-mono); font-size: 12px; padding: 1px 5px; border-radius: 3px; background: var(--color-surface-3); color: var(--color-fg-muted); }

.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
</style>
