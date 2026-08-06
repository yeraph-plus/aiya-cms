import { afterEach, describe, expect, it, vi } from 'vitest'
import { adminApi } from './admin-api'

describe('admin API contract adapter', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('serializes list filters and preserves the generated terms operation', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/users?')) {
        expect(url).toContain('page=2')
        expect(url).toContain('q=alice')
        return new Response(JSON.stringify({ items: [], total: 0, page: 2, size: 20 }), { status: 200 })
      }
      expect(url).toBe('/api/v1/contents/post/content-id/terms')
      return new Response(JSON.stringify([]), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    await adminApi.users({ page: 2, q: 'alice' })
    await adminApi.assignTerms('post', 'content-id', { term_ids: [] })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
