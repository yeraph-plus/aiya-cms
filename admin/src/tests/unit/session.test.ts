import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getUserMock, signinCallbackMock, signoutRedirectMock, fetchAdminSessionMock } = vi.hoisted(() => ({
    getUserMock: vi.fn(),
    signinCallbackMock: vi.fn(),
    signoutRedirectMock: vi.fn(),
    fetchAdminSessionMock: vi.fn()
}));

vi.mock('@/auth/oidc', () => ({
    userManager: {
        getUser: getUserMock,
        signinRedirectCallback: signinCallbackMock,
        signoutRedirect: signoutRedirectMock,
        removeUser: vi.fn()
    },
    signOutRedirect: signoutRedirectMock
}));

vi.mock('@/api/auth', () => ({
    fetchAdminSession: fetchAdminSessionMock
}));

import { clearSession, completeAuthentication, getAccessToken, initializeSession, sessionState, signOut } from '@/auth/session';

describe('session state machine', () => {
    beforeEach(() => {
        clearSession();
        vi.clearAllMocks();
        fetchAdminSessionMock.mockRejectedValueOnce(new Error('no cookie session'));
        fetchAdminSessionMock.mockResolvedValue({
            subject_id: 'u1',
            username: 'admin',
            display_name: 'Admin',
            status: 'active',
            capabilities: ['content.read']
        });
    });

    it('becomes authenticated with an in-memory token when a valid user exists', async () => {
        getUserMock.mockResolvedValue({ access_token: 'token-1', expired: false });
        fetchAdminSessionMock.mockReset();
        fetchAdminSessionMock.mockRejectedValueOnce(new Error('no cookie session'));
        fetchAdminSessionMock.mockImplementationOnce(() => {
            expect(getAccessToken()).toBe('token-1');
            return {
                subject_id: 'u1',
                username: 'admin',
                display_name: 'Admin',
                status: 'active',
                capabilities: ['content.read']
            };
        });
        await initializeSession();

        expect(sessionState.status).toBe('authenticated');
        expect(sessionState.accessToken).toBeNull();
        expect(fetchAdminSessionMock).toHaveBeenCalledTimes(2);
        expect(sessionState.me?.capabilities).toEqual(['content.read']);
    });

    it('becomes anonymous when there is no restorable user', async () => {
        getUserMock.mockResolvedValue(null);
        await initializeSession();

        expect(sessionState.status).toBe('anonymous');
        expect(sessionState.accessToken).toBeNull();
        expect(fetchAdminSessionMock).toHaveBeenCalledTimes(1);
    });

    it('runs initialization only once', async () => {
        getUserMock.mockResolvedValue(null);
        await initializeSession();
        await initializeSession();
        expect(getUserMock).toHaveBeenCalledTimes(1);
    });

    it('does not expose an authenticated session before /me succeeds', async () => {
        getUserMock.mockResolvedValue({ access_token: 'token-1', expired: false });
        fetchAdminSessionMock.mockRejectedValueOnce(new Error('API unavailable'));

        await initializeSession();

        expect(sessionState.status).toBe('error');
        expect(sessionState.accessToken).toBeNull();
        expect(sessionState.me).toBeNull();
    });

    it('completes the authorization callback by exchanging the code', async () => {
        signinCallbackMock.mockResolvedValue({
            access_token: 'token-2',
            expired: false
        });
        fetchAdminSessionMock.mockReset();
        fetchAdminSessionMock.mockResolvedValue({
            subject_id: 'u1',
            username: 'admin',
            display_name: 'Admin',
            status: 'active',
            capabilities: ['content.read']
        });
        await completeAuthentication();

        expect(sessionState.status).toBe('authenticated');
        expect(sessionState.accessToken).toBeNull();
        expect(fetchAdminSessionMock).toHaveBeenCalledTimes(1);
    });

    it('clears callback credentials when /me rejects', async () => {
        signinCallbackMock.mockResolvedValue({
            access_token: 'token-2',
            expired: false
        });
        fetchAdminSessionMock.mockReset();
        fetchAdminSessionMock.mockRejectedValueOnce(new Error('API unavailable'));

        await expect(completeAuthentication()).rejects.toThrow('API unavailable');
        expect(sessionState.status).toBe('anonymous');
        expect(sessionState.accessToken).toBeNull();
        expect(sessionState.me).toBeNull();
    });

    it('clears local state and triggers RP-initiated logout', async () => {
        signinCallbackMock.mockResolvedValue({
            access_token: 'token-2',
            expired: false
        });
        fetchAdminSessionMock.mockReset();
        fetchAdminSessionMock.mockResolvedValue({
            subject_id: 'u1',
            username: 'admin',
            display_name: 'Admin',
            status: 'active',
            capabilities: ['content.read']
        });
        await completeAuthentication();

        await signOut();

        expect(sessionState.status).toBe('anonymous');
        expect(sessionState.accessToken).toBeNull();
        expect(sessionState.me).toBeNull();
        expect(signoutRedirectMock).toHaveBeenCalledTimes(1);
    });
});
