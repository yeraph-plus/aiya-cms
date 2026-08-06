import { beforeAll, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from './index'

let router: ReturnType<typeof createAppRouter>

beforeAll(async () => {
  router = createAppRouter(createMemoryHistory())
  await router.push('/')
  await router.isReady()
})

describe('app router startup', () => {
  it('sets the section title on the overview route at startup', () => {
    expect(document.title).toBe('概览 - aiya-cms 管理后台')
  })

  it('sets a section-specific title on navigation', async () => {
    await router.push('/users')
    expect(document.title).toBe('用户与权限 - aiya-cms 管理后台')
  })

  it('falls back to the base title when no meta title is set', async () => {
    await router.push('/account/login')
    expect(document.title).toBe('aiya-cms 管理后台')
  })

  it('resolves unknown paths to the 404 catch-all without crashing', async () => {
    await router.push('/definitely-not-a-route')
    const resolved = router.currentRoute.value
    expect(resolved.path).toBe('/definitely-not-a-route')
    expect(resolved.matched.length).toBeGreaterThan(0)
  })
})
