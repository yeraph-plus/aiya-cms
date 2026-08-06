import { describe, expect, it } from 'vitest'
import { ApiService } from './api-service'

describe('ApiService', () => {
  it('removes data-table-only options from request parameters', () => {
    const service = new ApiService('/api/content')

    expect(
      service.removeDefaultOptions({
        page: 2,
        pageSize: 20,
        pageCount: 5,
        showSizePicker: true,
        query: 'release',
      }),
    ).toEqual({
      page: 2,
      pageSize: 20,
      query: 'release',
    })
  })
})
