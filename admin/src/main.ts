import { createAppRouter } from '~/router'
import App from './App.vue'
import type { AppModule } from './types'

import '@unocss/reset/tailwind-compat.css'
import 'uno.css'
import './styles/main.scss'

async function initializeMocking() {
  if (import.meta.env.VITE_API_MOCKING_ENABLED?.trim() !== 'true') {
    return
  }
  const { worker } = await import('~/mocks/browser')
  try {
    await worker.start({
      onUnhandledRequest: 'bypass',
      serviceWorker: {
        url: '/mockServiceWorker.js',
        options: {
          scope: '/',
        },
      },
      quiet: true,
    })
    if ('serviceWorker' in navigator) await navigator.serviceWorker.ready
  } catch (error) {
    console.warn('MSW initialization failed:', error)
  }
  return worker
}

const router = createAppRouter()

const app = createApp(App)
app.use(router)
Object.values(
  import.meta.glob<{ install: AppModule }>('./modules/*.ts', { eager: true }),
).forEach((i: any) => {
  i.install?.(app, router)
})

// register filters
app.config.globalProperties.$filters = {}
Object.values(
  import.meta.glob<any>('./common/filters/*.filter.ts', {
    eager: true,
    import: 'default',
  }),
).forEach((filters: any) => {
  Object.keys(filters).forEach((func) => {
    app.config.globalProperties.$filters[func] = filters[func]
  })
})

async function startApp() {
  try {
    await initializeMocking()
  } catch (error) {
    console.warn('Mock service initialization failed:', error)
  }

  try {
    app.mount('#app')
  } catch (error) {
    console.error('App mounting failed:', error)
  }
}

startApp()
