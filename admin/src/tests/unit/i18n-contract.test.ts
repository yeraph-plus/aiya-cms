import { describe, expect, it } from 'vitest';
import { messages, resolveInitialLocale, type AppLocale } from '@/i18n';

function keys(value: Record<string, unknown>, prefix = ''): string[] {
    return Object.entries(value).flatMap(([key, child]) => {
        const path = prefix ? `${prefix}.${key}` : key;
        return child !== null && typeof child === 'object' && !Array.isArray(child) ? keys(child as Record<string, unknown>, path) : [path];
    });
}

describe('i18n contract', () => {
    it('keeps the Chinese and English dictionaries in exact key parity', () => {
        expect(keys(messages['zh-CN']).sort()).toEqual(keys(messages['en-US']).sort());
    });

    it('resolves saved locale before browser locale and defaults to Chinese', () => {
        expect(resolveInitialLocale('en-US', ['zh-CN'])).toBe<AppLocale>('en-US');
        expect(resolveInitialLocale(null, ['en-US'])).toBe<AppLocale>('en-US');
        expect(resolveInitialLocale(null, ['fr-FR'])).toBe<AppLocale>('zh-CN');
    });

    it('defines route and navigation keys used by the production shell', () => {
        const dictionaryKeys = new Set(keys(messages['zh-CN']));
        for (const key of ['nav.dashboard', 'nav.content.group', 'nav.users.group', 'nav.system.group', 'nav.settings', 'routes.auth.login', 'routes.content.articles', 'routes.users.list']) {
            expect(dictionaryKeys.has(key), `missing ${key}`).toBe(true);
        }
    });
});
