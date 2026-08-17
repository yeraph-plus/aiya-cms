import { describe, expect, it } from 'vitest';

import { isTransactionExpired, publicSessionUser } from '@/lib/auth/session';

describe('OIDC session helpers', () => {
    it('expires authorization transactions after five minutes', () => {
        const createdAt = Date.parse('2026-08-12T00:00:00Z');
        expect(isTransactionExpired({ createdAt }, createdAt + 299_999)).toBe(false);
        expect(isTransactionExpired({ createdAt }, createdAt + 300_001)).toBe(true);
    });

    it('projects only display-safe user fields', () => {
        const projection = publicSessionUser({
            subject: 'subject-1',
            displayName: 'Aiya',
            email: 'aiya@example.test',
            accessToken: 'access-secret',
            refreshToken: 'refresh-secret',
            idToken: 'id-secret',
            expiresAt: 1,
            createdAt: 1,
            lastSeenAt: 1
        });

        expect(projection).toEqual({
            subject: 'subject-1',
            displayName: 'Aiya',
            email: 'aiya@example.test'
        });
        expect(JSON.stringify(projection)).not.toContain('secret');
    });
});
