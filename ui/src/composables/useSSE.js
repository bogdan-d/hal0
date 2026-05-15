import { ref, onUnmounted } from 'vue'

/**
 * Server-Sent Events composable.
 *
 * Usage:
 *   const { lines, connected, error, connect, disconnect } = useSSE()
 *   connect('/api/logs/stream?slot=primary')
 *
 * Each SSE `data` payload is appended to `lines` as a string.
 * Call `disconnect()` or let the component unmount to close the stream.
 */
export function useSSE(maxLines = 2000) {
  const lines = ref([])
  const connected = ref(false)
  const error = ref(null)
  let es = null

  function connect(url) {
    disconnect()
    error.value = null
    es = new EventSource(url)

    es.onopen = () => {
      connected.value = true
    }

    es.onmessage = (evt) => {
      lines.value.push(evt.data)
      // Trim to maxLines to avoid unbounded memory growth
      if (lines.value.length > maxLines) {
        lines.value = lines.value.slice(-maxLines)
      }
    }

    es.onerror = (evt) => {
      connected.value = false
      error.value = 'SSE connection lost'
      // EventSource auto-reconnects; reset after brief delay
      setTimeout(() => {
        if (es?.readyState !== EventSource.CLOSED) {
          connected.value = true
          error.value = null
        }
      }, 3000)
    }
  }

  function disconnect() {
    if (es) {
      es.close()
      es = null
    }
    connected.value = false
  }

  function clear() {
    lines.value = []
  }

  onUnmounted(disconnect)

  return { lines, connected, error, connect, disconnect, clear }
}
