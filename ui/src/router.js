import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('./views/Dashboard.vue'),
    meta: { title: 'Dashboard' },
  },
  {
    path: '/slots',
    name: 'slots',
    component: () => import('./views/Slots.vue'),
    meta: { title: 'Slots' },
  },
  {
    path: '/slots/:name',
    name: 'slot-detail',
    component: () => import('./views/Slots.vue'),
    meta: { title: 'Slots' },
  },
  {
    path: '/models',
    name: 'models',
    component: () => import('./views/Models.vue'),
    meta: { title: 'Models' },
  },
  {
    path: '/hardware',
    name: 'hardware',
    component: () => import('./views/Hardware.vue'),
    meta: { title: 'Hardware' },
  },
  {
    path: '/logs',
    name: 'logs',
    component: () => import('./views/Logs.vue'),
    meta: { title: 'Logs' },
  },
  {
    path: '/providers',
    name: 'providers',
    component: () => import('./views/Providers.vue'),
    meta: { title: 'Providers' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('./views/Settings.vue'),
    meta: { title: 'Settings' },
  },
  {
    path: '/welcome',
    name: 'welcome',
    component: () => import('./views/FirstRun.vue'),
    meta: { title: 'Setup' },
  },
  {
    path: '/:catchAll(.*)',
    name: 'not-found',
    component: () => import('./views/NotFound.vue'),
    meta: { title: 'Not Found' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const base = 'hal0'
  document.title = to.meta?.title ? `${to.meta.title} — ${base}` : base
})

export default router
