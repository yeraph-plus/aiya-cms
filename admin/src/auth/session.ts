import { computed, reactive } from 'vue';
import type { components } from '@/api/schema';
import { fetchAdminSession, logoutAdminSession } from '@/api/auth';
import { signOutRedirect, userManager } from './oidc';

export type AdminSessionDTO = components['schemas']['AdminSessionDTO'];

export type SessionStatus = 'loading' | 'anonymous' | 'authenticated' | 'expired' | 'error';

export interface SessionState {
    status: SessionStatus;
    accessToken: string | null;
    me: AdminSessionDTO | null;
}

export const sessionState = reactive<SessionState>({
    status: 'loading',
    accessToken: null,
    me: null
});

export const isAuthenticated = computed(() => sessionState.status === 'authenticated');

export const sessionCapabilities = computed(() => new Set(sessionState.me?.capabilities ?? []));

export function hasCapability(capability: string): boolean {
    return sessionCapabilities.value.has(capability);
}

export function getAccessToken(): string | null {
    return sessionState.accessToken;
}

let initializePromise: Promise<void> | null = null;

export function initializeSession(): Promise<void> {
    if (initializePromise === null) {
        initializePromise = (async () => {
            // Cookie-first bootstrap makes a reload independent of the OIDC
            // user store.  The bearer fallback is used only once to upgrade a
            // freshly completed OIDC flow into the HttpOnly admin session.
            try {
                sessionState.accessToken = null;
                const cookieSession = await fetchAdminSession();
                if (!cookieSession || typeof cookieSession.subject_id !== 'string') {
                    throw new Error('administrator cookie session is unavailable');
                }
                sessionState.me = cookieSession;
                sessionState.status = 'authenticated';
                return;
            } catch {
                // No cookie yet; try the one-time in-memory OIDC result.
            }
            const user = await userManager.getUser();
            if (user?.access_token && !user.expired) {
                sessionState.accessToken = user.access_token;
                const upgradedSession = await fetchAdminSession();
                if (!upgradedSession || typeof upgradedSession.subject_id !== 'string') {
                    throw new Error('administrator session exchange returned no session');
                }
                sessionState.me = upgradedSession;
                sessionState.accessToken = null;
                await clearOidcUser();
                sessionState.status = 'authenticated';
            } else {
                sessionState.accessToken = null;
                sessionState.me = null;
                sessionState.status = 'anonymous';
            }
        })().catch(() => {
            sessionState.accessToken = null;
            sessionState.me = null;
            sessionState.status = 'error';
            initializePromise = null;
        });
    }
    return initializePromise;
}

export async function refreshMe(): Promise<void> {
    sessionState.me = await fetchAdminSession();
}

export async function completeAuthentication(): Promise<void> {
    try {
        const user = await userManager.signinRedirectCallback();
        if (!user.access_token) throw new Error('OIDC callback did not return an access token.');
        sessionState.accessToken = user.access_token;
        const me = await fetchAdminSession();
        if (!me || typeof me.subject_id !== 'string') {
            throw new Error('administrator session exchange returned no session');
        }
        sessionState.me = me;
        sessionState.accessToken = null;
        await clearOidcUser();
        sessionState.status = 'authenticated';
    } catch (error) {
        clearSession();
        throw error;
    }
}

async function clearOidcUser(): Promise<void> {
    const removeUser = (userManager as { removeUser?: () => Promise<unknown> }).removeUser;
    if (typeof removeUser === 'function') await removeUser.call(userManager);
}

export function clearSession(): void {
    sessionState.status = 'anonymous';
    sessionState.accessToken = null;
    sessionState.me = null;
    initializePromise = null;
}

export async function signOut(): Promise<void> {
    try {
        await logoutAdminSession();
    } catch {
        // Expired sessions are already logged out server-side.
    }
    clearSession();
    try {
        await signOutRedirect();
    } catch {
        // The browser no longer retains an OIDC user after cookie upgrade.
    }
}
