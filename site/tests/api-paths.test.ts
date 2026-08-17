import { describe, expect, it } from 'vitest';

import { assertUserApiPath } from '@/lib/api/paths';

describe('user API path allowlist', () => {
    it('allows only user product API paths', () => {
        expect(assertUserApiPath('/api/v1/site')).toBe('/api/v1/site');
        expect(assertUserApiPath('/api/v1/me')).toBe('/api/v1/me');
        expect(assertUserApiPath('/api/v1/posts/by-slug/hello')).toBe('/api/v1/posts/by-slug/hello');
    });

    it('rejects admin, webhook, system and OIDC protocol paths', () => {
        for (const path of ['/api/v1/admin/users', '/api/v1/webhooks/payments/dev', '/api/v1/health', '/oidc/token']) {
            expect(() => assertUserApiPath(path)).toThrow(/not part of the user API projection/u);
        }
    });
});
