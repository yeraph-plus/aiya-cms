import { beforeEach, describe, expect, it, vi } from 'vitest';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('@/router', () => ({
    default: {
        push: pushMock,
        currentRoute: { value: { fullPath: '/content/posts' } }
    }
}));

vi.mock('@/auth/oidc', () => ({
    userManager: { getUser: vi.fn().mockResolvedValue(null) },
    signOutRedirect: vi.fn()
}));

vi.mock('@/api/auth', () => ({
    fetchMe: vi.fn()
}));

import { handleUnauthorized } from '@/auth/unauthorized';
import { sessionState } from '@/auth/session';

describe('401 single-flight reauthentication', () => {
    beforeEach(() => {
        pushMock.mockClear();
    });

    it('expires the session and redirects exactly once for concurrent 401s', async () => {
        handleUnauthorized();
        handleUnauthorized();
        handleUnauthorized();

        expect(sessionState.status).toBe('expired');
        expect(sessionState.accessToken).toBeNull();
        expect(pushMock).toHaveBeenCalledTimes(1);
        expect(pushMock).toHaveBeenCalledWith({
            name: 'login',
            query: { redirect: '/content/posts', reason: 'expired' }
        });
    });

    it('allows a new reauthentication after the first completes', async () => {
        handleUnauthorized();
        await Promise.resolve();
        await Promise.resolve();

        handleUnauthorized();
        expect(pushMock).toHaveBeenCalledTimes(2);
    });
});
