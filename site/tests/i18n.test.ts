import { describe, expect, it } from 'vitest';

import { localeFromPath, t } from '@/lib/i18n';

describe('i18n catalog', () => {
    it('resolves Chinese and English route locales', () => {
        expect(localeFromPath('/')).toBe('zh-CN');
        expect(localeFromPath('/account')).toBe('zh-CN');
        expect(localeFromPath('/en')).toBe('en');
        expect(localeFromPath('/en/account')).toBe('en');
    });

    it('returns typed messages for both locales', () => {
        expect(t('zh-CN', 'nav.home')).toBe('首页');
        expect(t('en', 'nav.home')).toBe('Home');
    });
});
