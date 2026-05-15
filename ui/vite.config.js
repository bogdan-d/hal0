import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['ai.thinmint.dev', 'localhost', '127.0.0.1'],
    hmr: {
      host: 'ai.thinmint.dev',
      protocol: 'wss',
      clientPort: 443,
    },
    // Pointed at the hal0-test LXC (10.0.1.230) — real local-slot inference
    // through the Strix Halo iGPU.  The dev VM's hal0 (127.0.0.1:8080) is
    // still routable; flip these back to 127.0.0.1 to bench against the dev
    // box again.
    proxy: {
      '/api': 'http://10.0.1.230:8080',
      '/v1': 'http://10.0.1.230:8080',
    },
  },
})
