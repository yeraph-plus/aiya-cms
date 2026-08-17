import { describe, expect, it } from 'vitest';
import { assertAdminSpaApiPath } from '@/api/scope';

describe('administrator API boundary', () => {
    it.each(['/api/v1/admin/users', '/api/v1/admin/session', '/api/v1/auth/register', '/oidc/userinfo'])('allows the administrator and shared authentication surfaces: %s', (path) => {
        expect(() => assertAdminSpaApiPath(path)).not.toThrow();
    });

    it.each(['/api/v1/me', '/api/v1/me/avatar/upload-intents', '/api/v1/content/post', '/api/v1/me/points/ledger', '/api/v1/point-purchase/offers', '/api/v1/membership-purchase/offers'])('rejects ordinary user business endpoints: %s', (path) => {
        expect(() => assertAdminSpaApiPath(path)).toThrow(/administrator SPA API boundary/i);
    });
});
