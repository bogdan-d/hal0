<script setup>
/**
 * Wordmark — "hal0" rendered in JetBrains Mono with the slashed-zero
 * accent on the "0". Direct Vue port of hal0-web/src/components/
 * Wordmark.astro so the dashboard and marketing site render the brand
 * identically.
 *
 * Props:
 *   size   – tailwind text size class (default "text-base")
 *   tone   – "default" keeps fg + accent zero; "mono" forces a single
 *            colour (used inside coloured chips where the amber would
 *            clash with the surface).
 *   as     – tag override; defaults to <span>. <a> is supported for
 *            header/footer usage and accepts an `href`.
 *   href   – when `as="a"`, the link target.
 */
defineProps({
  size: { type: String, default: 'text-base' },
  tone: { type: String, default: 'default' },  // 'default' | 'mono'
  as:   { type: String, default: 'span' },     // 'span' | 'div' | 'h1' | 'a'
  href: { type: String, default: undefined },
})
</script>

<template>
  <component
    :is="as"
    :href="as === 'a' ? href : undefined"
    class="wordmark inline-flex items-baseline tracking-tight"
    :class="size"
  >
    <span class="text-hal0-fg">hal</span>
    <span :class="tone === 'mono' ? 'text-hal0-fg' : 'text-hal0-accent'">0</span>
  </component>
</template>
