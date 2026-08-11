import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Router } from 'vue-router';

const { getUserMock, fetchMeMock } = vi.hoisted(() => ({
    getUserMock: vi.fn(),
    fetchMeMock: vi.fn()
}));

vi.mock('@/auth/oidc', () => ({
    userManager: { getUser: getUserMock },
    signOutRedirect: vi.fn()
}));

vi.mock('@/api/auth', () => ({
    fetchMe: fetchMeMock
}));

import router from '@/router';
import { clearSession, sessionState } from '@/auth/session';
import { APP_NAME } from '@/env';

function resetSession(): void {
    clearSession();
    sessionState.status = 'loading';
}

async function signIn(capabilities: string[] = ['content.read']): Promise<void> {
    getUserMock.mockResolvedValue({ access_token: 'token-1', expired: false });
    fetchMeMock.mockResolvedValue({ id: 'u1', display_name: 'Admin', capabilities });
    resetSession();
    const target = capabilities.includes('content.read') ? '/content' : '/identity/users';
    const expected = capabilities.includes('content.read') ? 'content-list' : 'identity-users';
    await router.push(target);
    expect(router.currentRoute.value.name).toBe(expected);
}

function registerProtectedRoute(routerInstance: Router): () => void {
    const remove = routerInstance.addRoute({
        path: '/test-guard',
        name: 'test-guard',
        component: { template: '<div />' },
        meta: { title: 'Test Guard', requiresAuth: true, requiredCapability: 'identity.users.read', shell: 'app' }
    });
    return remove;
}

describe('router guard', () => {
    beforeEach(() => {
        resetSession();
        vi.clearAllMocks();
        getUserMock.mockReset();
        fetchMeMock.mockReset();
        document.title = '';
    });

    it('redirects an anonymous user to login and keeps the same-origin redirect', async () => {
        const remove = registerProtectedRoute(router);
        try {
            getUserMock.mockResolvedValue(null);
            await router.push('/test-guard?page=2');

            expect(router.currentRoute.value.name).toBe('login');
            expect(router.currentRoute.value.query.redirect).toBe('/test-guard?page=2');
        } finally {
            remove();
        }
    });

    it('allows anonymous access to public routes', async () => {
        getUserMock.mockResolvedValue(null);
        await router.push('/auth/login');

        expect(router.currentRoute.value.name).toBe('login');
        expect(router.currentRoute.value.query.redirect).toBeUndefined();
    });

    it('keeps an authenticated deep link stable across refresh-style navigation', async () => {
        await signIn(['content.read']);
        await router.push('/content');

        expect(router.currentRoute.value.name).toBe('content-list');
        expect(document.title).toBe(`Articles · ${APP_NAME}`);
    });

    it('redirects an authenticated user away from login', async () => {
        await signIn();
        await router.push('/auth/login');

        expect(router.currentRoute.value.name).toBe('content-list');
    });

    it('redirects an authenticated user away from the callback route', async () => {
        await signIn();
        await router.push('/callback');

        expect(router.currentRoute.value.name).toBe('content-list');
    });

    it('sends a signed-in user without the capability to access denied', async () => {
        const remove = registerProtectedRoute(router);
        try {
            await signIn(['content.read']);
            await router.push('/test-guard');

            expect(router.currentRoute.value.name).toBe('accessDenied');
        } finally {
            remove();
        }
    });

    it('lets a user with the required capability reach the protected route', async () => {
        const remove = registerProtectedRoute(router);
        try {
            await signIn(['identity.users.read']);
            await router.push('/test-guard');

            expect(router.currentRoute.value.name).toBe('test-guard');
            expect(document.title).toBe(`Test Guard · ${APP_NAME}`);
        } finally {
            remove();
        }
    });

    it('resolves unknown paths to the production 404', async () => {
        getUserMock.mockResolvedValue(null);
        await router.push('/no-such-page');

        expect(router.currentRoute.value.name).toBe('notfound');
    });

    it('does not register blocked routes', () => {
        for (const name of ['operations-payments', 'operations-notifications', 'identity-oidc-clients', 'content-assets']) {
            expect(router.hasRoute(name), `route ${name} must not be registered`).toBe(false);
        }
        for (const path of ['/operations/payments', '/operations/notifications', '/identity/oidc-clients', '/content/assets']) {
            expect(router.resolve(path).name, `path ${path}`).toBe('notfound');
        }
    });

    it('retries session initialization on the next navigation after a failure', async () => {
        getUserMock.mockRejectedValueOnce(new Error('op unavailable'));
        await router.push('/content');

        expect(router.currentRoute.value.name).toBe('login');

        getUserMock.mockResolvedValue(null);
        await router.push('/content');

        expect(getUserMock).toHaveBeenCalledTimes(2);
        expect(router.currentRoute.value.name).toBe('login');
    });
});
