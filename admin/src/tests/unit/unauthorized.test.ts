import { beforeEach, describe, expect, it, vi } from 'vitest';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('@/router', () => ({
    default: {
        push: pushMock,
        currentRoute: { value: { fullPath: '/content' } }
    }
}));

vi.mock('@/auth/oidc', () => ({
    userManager: { getUser: vi.fn().mockResolvedValue(null) },
    signOutRedirect: vi.fn()
}));

vi.mock('@/api/auth', () => ({
    fetchAdminSession: vi.fn()
}));

import { handleUnauthorized } from '@/auth/unauthorized';
import { sessionState } from '@/auth/session';

describe('401 single-flight reauthentication', () => {
    beforeEach(() => {
        pushMock.mockClear();
    });

    it('expires the session and redirects exactly once for concurrent 401s', async () => {
        sessionState.status = 'authenticated';
        handleUnauthorized();
        handleUnauthorized();
        handleUnauthorized();

        expect(sessionState.status).toBe('expired');
        expect(sessionState.accessToken).toBeNull();
        expect(pushMock).toHaveBeenCalledTimes(1);
        expect(pushMock).toHaveBeenCalledWith({
            name: 'login',
            query: { redirect: '/content', reason: 'expired' }
        });
        // Let the single-flight promise settle before the next test starts.
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
        await new Promise((resolve) => setTimeout(resolve, 0));
    });

    it('allows a new reauthentication after the first completes', async () => {
        sessionState.status = 'authenticated';
        handleUnauthorized();
        await Promise.resolve();
        await Promise.resolve();
        await new Promise((resolve) => setTimeout(resolve, 0));

        handleUnauthorized();
        expect(pushMock).toHaveBeenCalledTimes(2);
    });
});
