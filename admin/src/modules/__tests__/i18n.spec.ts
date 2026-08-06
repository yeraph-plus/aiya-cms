import { describe, expect, it } from 'vitest'
import i18n from '../i18n'

describe('i18n module', () => {
  it('defaults to zh-CN when nothing is stored', () => {
    expect(i18n.global.locale.value).toBe('zh-CN')
    expect(i18n.global.fallbackLocale.value).toBe('zh')
  })

  it('translates the product title', () => {
    expect(i18n.global.t('title')).toBe('aiya-cms 管理后台')
  })

  it('resolves the aiya navigation menu labels', () => {
    expect(i18n.global.t('menu.dashboard')).toBe('概览')
    expect(i18n.global.t('menu.users')).toBe('用户与权限')
    expect(i18n.global.t('menu.taxonomy')).toBe('分类')
  })

  it('loads only Chinese and English locale resources', () => {
    expect(new Set(i18n.global.availableLocales)).toEqual(new Set(['en', 'zh']))
    expect(i18n.global.te('languages.fa')).toBe(false)
  })
})
