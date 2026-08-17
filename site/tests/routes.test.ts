import { describe, expect, it } from 'vitest';

import { localizedRoute, routePolicy, safeReturnTo } from '@/lib/routing/routes';

describe('route manifest', () => {
    it('builds localized route paths without prefixing the default locale', () => {
        expect(localizedRoute('home', 'zh-CN')).toBe('/');
        expect(localizedRoute('home', 'en')).toBe('/en');
        expect(localizedRoute('account', 'zh-CN')).toBe('/account');
        expect(localizedRoute('account', 'en')).toBe('/en/account');
    });

    it('marks account pages as authenticated routes', () => {
        expect(routePolicy('/account')).toBe('authenticated');
        expect(routePolicy('/en/account')).toBe('authenticated');
        expect(routePolicy('/')).toBe('public');
    });

    it('rejects external or protocol-relative return paths', () => {
        expect(safeReturnTo('/account?tab=profile')).toBe('/account?tab=profile');
        expect(safeReturnTo('https://attacker.example/account')).toBe('/');
        expect(safeReturnTo('//attacker.example/account')).toBe('/');
        expect(safeReturnTo('/auth/callback')).toBe('/');
    });
});
