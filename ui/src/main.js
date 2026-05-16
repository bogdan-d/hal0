import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router.js'

// Self-hosted brand fonts — matches hal0-web. Importing here (instead
// of via <link href="…fonts.googleapis.com/…">) keeps the dashboard
// usable on hosts with no outbound internet and avoids the FOUC the
// CDN setup used to produce.
import '@fontsource-variable/geist/index.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/700.css'

import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
