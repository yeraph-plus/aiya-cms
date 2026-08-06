import { beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_PRIMARY_COLOR,
  normalizeLanguage,
  normalizeLayoutPreferences,
  normalizeThemeColor,
  PRIMARY_COLORS,
  readAndMigrateLayoutPreferences,
  SUPPORTED_LANGUAGES,
} from './layout-preferences'

describe('layout preferences', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('supports only Chinese and English', () => {
    expect(SUPPORTED_LANGUAGES).toEqual(['zh', 'en'])
    expect(normalizeLanguage('zh')).toBe('zh')
    expect(normalizeLanguage('en')).toBe('en')
    expect(normalizeLanguage('fa')).toBe('zh')
    expect(normalizeLanguage('unknown')).toBe('zh')
  })

  it('keeps valid preset colors and falls back for custom colors', () => {
    expect(PRIMARY_COLORS[0]).toBe('#009b43')
    expect(DEFAULT_PRIMARY_COLOR).toBe('#009b43')
    expect(normalizeThemeColor('#0099e0')).toBe('#0099e0')
    expect(normalizeThemeColor('#123456')).toBe(DEFAULT_PRIMARY_COLOR)
    expect(normalizeThemeColor(undefined)).toBe(DEFAULT_PRIMARY_COLOR)
  })

  it('migrates stale language, custom color, and flat design state', () => {
    expect(
      normalizeLayoutPreferences({
        activeLanguage: 'fa',
        themeColor: '#123456',
        flatDesign: false,
        isRtl: true,
        isDark: true,
      }),
    ).toEqual({
      activeLanguage: 'zh',
      themeColor: DEFAULT_PRIMARY_COLOR,
      isRtl: true,
      isDark: true,
    })
  })

  it('rewrites legacy layout storage once', () => {
    window.localStorage.setItem(
      'layout',
      JSON.stringify({
        activeLanguage: 'fa',
        themeColor: '#123456',
        flatDesign: false,
      }),
    )

    const migrated = readAndMigrateLayoutPreferences(window.localStorage)

    expect(migrated).toEqual({
      activeLanguage: 'zh',
      themeColor: DEFAULT_PRIMARY_COLOR,
    })
    expect(JSON.parse(window.localStorage.getItem('layout')!)).toEqual(migrated)
  })
})
