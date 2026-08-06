import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    authRequired?: boolean
    requiredCapability?: string
    requiredCapabilities?: string[]
  }
}
