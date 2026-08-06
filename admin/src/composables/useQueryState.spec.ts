import { describe, expect, it } from 'vitest'
import { useQueryState } from './useQueryState'

describe('useQueryState', () => {
  it('is exported as the shared list filter contract', () => {
    expect(typeof useQueryState).toBe('function')
  })
})
