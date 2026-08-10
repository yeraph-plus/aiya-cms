import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getUserMock, signinCallbackMock, signoutRedirectMock, fetchMeMock } = vi.hoisted(() => ({
    getUserMock: vi.fn(),
    signinCallbackMock: vi.fn(),
    signoutRedirectMock: vi.fn(),
    fetchMeMock: vi.fn()
}));

vi.mock('@/auth/oidc', () => ({
    userManager: {
        getUser: getUserMock,
        signinRedirectCallback: signinCallbackMock,
        signoutRedirect: signoutRedirectMock
    },
    signOutRedirect: signoutRedirectMock
}));

vi.mock('@/api/auth', () => ({
    fetchMe: fetchMeMock
}));

import { clearSession, completeAuthentication, initializeSession, sessionState, signOut } from '@/auth/session';

describe('session state machine', () => {
    beforeEach(() => {
        clearSession();
        vi.clearAllMocks();
        fetchMeMock.mockResolvedValue({ id: 'u1', display_name: 'Admin', capabilities: ['content.read'] });
    });

    it('becomes authenticated with an in-memory token when a valid user exists', async () => {
        getUserMock.mockResolvedValue({ access_token: 'token-1', expired: false });
        await initializeSession();

        expect(sessionState.status).toBe('authenticated');
        expect(sessionState.accessToken).toBe('token-1');
        expect(fetchMeMock).toHaveBeenCalledTimes(1);
        expect(sessionState.me?.capabilities).toEqual(['content.read']);
    });

    it('becomes anonymous when there is no restorable user', async () => {
        getUserMock.mockResolvedValue(null);
        await initializeSession();

        expect(sessionState.status).toBe('anonymous');
        expect(sessionState.accessToken).toBeNull();
        expect(fetchMeMock).not.toHaveBeenCalled();
    });

    it('runs initialization only once', async () => {
        getUserMock.mockResolvedValue(null);
        await initializeSession();
        await initializeSession();
        expect(getUserMock).toHaveBeenCalledTimes(1);
    });

    it('completes the authorization callback by exchanging the code', async () => {
        signinCallbackMock.mockResolvedValue({ access_token: 'token-2', expired: false });
        await completeAuthentication();

        expect(sessionState.status).toBe('authenticated');
        expect(sessionState.accessToken).toBe('token-2');
        expect(fetchMeMock).toHaveBeenCalledTimes(1);
    });

    it('clears local state and triggers RP-initiated logout', async () => {
        signinCallbackMock.mockResolvedValue({ access_token: 'token-2', expired: false });
        await completeAuthentication();

        await signOut();

        expect(sessionState.status).toBe('anonymous');
        expect(sessionState.accessToken).toBeNull();
        expect(sessionState.me).toBeNull();
        expect(signoutRedirectMock).toHaveBeenCalledTimes(1);
    });
});
