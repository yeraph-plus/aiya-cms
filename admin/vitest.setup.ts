import { vi } from 'vitest'

/**
 * Test-only mocks for the virtual modules the app plugins emit at build time.
 * Under vitest's vite-node these are re-generated per importing file, which
 * breaks `@intlify/unplugin-vue-i18n/messages` (duplicate locale keys) and the
 * layout pages module (unresolvable file URL). The fixtures below mirror the
 * real zh/en locale files and page route records for the keys under test.
 */

vi.mock('@intlify/unplugin-vue-i18n/messages', () => ({
  default: {
    zh: {
      title: 'aiya-cms 管理后台',
      menu: {
        dashboard: '概览',
        users: '用户与权限',
        content: '内容',
        taxonomy: '分类',
        comments: '评论',
        audit: '审计',
        settings: '设置',
        tasks: '任务',
      },
    },
    en: {
      title: 'aiya-cms Admin',
      menu: {
        dashboard: 'Overview',
        users: 'Users & Permissions',
        content: 'Content',
        taxonomy: 'Taxonomy',
        comments: 'Comments',
        audit: 'Audit',
        settings: 'Settings',
        tasks: 'Tasks',
      },
    },
  },
}))

vi.mock('virtual:generated-pages', () => {
  const Stub = { template: '<div />' }
  return {
    default: [
      { path: '/', component: Stub, meta: { title: 'dashboard' } },
      { path: '/users', component: Stub, meta: { title: 'users' } },
      { path: '/account/login', component: Stub },
      { path: '/:all(.*)', component: Stub },
    ],
  }
})

vi.mock('virtual:generated-layouts', () => ({
  default: (routes: unknown[]) => routes,
  setupLayouts: (routes: unknown[]) => routes,
}))
