import { describe, expect, it } from 'vitest'
import i18n from '~/modules/i18n'
import { buildSidebarMenu } from './navigation'

const t: (key: string) => string = (key) => String(i18n.global.t(key))

describe('buildSidebarMenu', () => {
  const menu = buildSidebarMenu(t)

  it('contains the overview plus the seven aiya sections', () => {
    expect(menu).toHaveLength(8)
    expect(menu.map((m) => m.key)).toEqual([
      'index',
      'users',
      'content',
      'taxonomy',
      'comments',
      'audit',
      'settings',
      'tasks',
    ])
  })

  it('starts with the overview route', () => {
    expect(menu[0]?.route).toBe('/')
    expect(menu[0]?.label).toBe('概览')
  })

  it('gives every section a resolvable route', () => {
    for (const item of menu) {
      expect(item.key).toBeTruthy()
      expect(item.route).toMatch(/^\//)
    }
  })

  it('resolves every label through i18n without leaking raw keys', () => {
    for (const item of menu) {
      expect(item.label).not.toMatch(/^menu\./)
      expect(item.label?.length).toBeGreaterThan(0)
    }
  })

  it('filters protected sections by capabilities after session restore', () => {
    const visible = buildSidebarMenu(
      t,
      new Set(['user:read_any', 'task:manage']),
    )
    expect(visible.map((item) => item.key)).toEqual(['index', 'users', 'tasks'])
  })
})
