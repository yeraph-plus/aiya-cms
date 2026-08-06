import { setupLayouts } from 'virtual:generated-layouts'
import generatedRoutes from 'virtual:generated-pages'
import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
} from 'vue-router'
import { ApiError } from '~/common/api/api-client'
import i18n from '~/modules/i18n'

const routes = setupLayouts(generatedRoutes)

export function createAppRouter(
  history: RouterHistory = createWebHistory(),
): Router {
  const router = createRouter({ history, routes })

  router.beforeEach(async (to) => {
    const needsAuth =
      to.meta.authRequired === true ||
      Boolean(
        to.meta.requiredCapability || to.meta.requiredCapabilities?.length,
      )
    const accountStore = needsAuth ? useAccountStore() : null

    if (needsAuth && accountStore && !accountStore.isAuthenticated()) {
      try {
        await accountStore.restoreSession()
      } catch (error) {
        if (
          error instanceof ApiError &&
          (error.status >= 500 || error.status === 0)
        ) {
          return { path: '/503', replace: true }
        }
      }
    }

    if (needsAuth && accountStore && !accountStore.isAuthenticated()) {
      return {
        path: '/account/login',
        query: { redirect: to.fullPath },
      }
    }

    const required = [
      ...(to.meta.requiredCapability ? [to.meta.requiredCapability] : []),
      ...(to.meta.requiredCapabilities ?? []),
    ]
    if (
      required.length &&
      accountStore &&
      !accountStore.hasAnyCapability(required)
    ) {
      return { path: '/403', replace: true }
    }

    const { t } = i18n.global
    let title = t('title')
    if (to.meta.title) {
      const key = `menu.${to.meta.title}`
      const label = i18n.global.te(key) ? t(key) : String(to.meta.title)
      title = `${label} - ${title}`
    }

    document.title = title
  })

  return router
}
