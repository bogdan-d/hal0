import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useToastsStore } from './toasts.js'

export const useSystemStore = defineStore('system', () => {
  const status = ref(null)    // raw /api/status response
  const hardware = ref(null)  // hardware section
  const slots = ref([])       // slots array
  const loading = ref(false)
  const error = ref(null)

  async function fetchStatus() {
    loading.value = true
    error.value = null
    try {
      const res = await fetch('/api/status')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      status.value = data
      hardware.value = data.hardware ?? null
      slots.value = data.slots ?? []
    } catch (err) {
      error.value = err.message
      // Don't toast on every background poll failure — only surface to store
    } finally {
      loading.value = false
    }
  }

  return { status, hardware, slots, loading, error, fetchStatus }
})
