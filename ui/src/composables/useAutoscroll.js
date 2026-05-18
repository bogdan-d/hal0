import { ref, onMounted, onUnmounted, nextTick } from 'vue'

/**
 * useAutoscroll — keep a scroll container pinned to the bottom while the
 * user is at the bottom; pause auto-pinning when the user scrolls up.
 *
 * Usage:
 *   const { scrollEl, atBottom, jumpToLive, onContentAppended } = useAutoscroll()
 *   <div ref="scrollEl" @scroll="...">...</div>
 *   // after pushing a line:
 *   onContentAppended()
 *
 * `atBottom` is the source of truth — when true, content updates trigger
 * an immediate scroll-to-bottom; when false, content piles up off-screen
 * until the user clicks "Jump to live".
 */
export function useAutoscroll(thresholdPx = 16) {
  const scrollEl = ref(null)
  const atBottom = ref(true)

  function recompute() {
    const el = scrollEl.value
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    atBottom.value = distFromBottom <= thresholdPx
  }

  async function pinToBottom() {
    await nextTick()
    const el = scrollEl.value
    if (!el) return
    el.scrollTop = el.scrollHeight
    atBottom.value = true
  }

  function jumpToLive() { pinToBottom() }

  function onContentAppended() {
    if (atBottom.value) pinToBottom()
  }

  function onScroll() { recompute() }

  onMounted(() => {
    const el = scrollEl.value
    if (el) {
      el.addEventListener('scroll', onScroll, { passive: true })
      pinToBottom()
    }
  })

  onUnmounted(() => {
    const el = scrollEl.value
    if (el) el.removeEventListener('scroll', onScroll)
  })

  return { scrollEl, atBottom, jumpToLive, onContentAppended, pinToBottom }
}
