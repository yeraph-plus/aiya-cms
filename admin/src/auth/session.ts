import { computed, reactive } from 'vue';
import type { components } from '@/api/schema';
import { fetchMe } from '@/api/auth';
import { signOutRedirect, userManager } from './oidc';

export type MeDTO = components['schemas']['MeDTO'];

export type SessionStatus = 'loading' | 'anonymous' | 'authenticated' | 'expired' | 'error';

export interface SessionState {
    status: SessionStatus;
    accessToken: string | null;
    me: MeDTO | null;
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
            const user = await userManager.getUser();
            if (user?.access_token && !user.expired) {
                sessionState.accessToken = user.access_token;
                const me = await fetchMe();
                sessionState.me = me;
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
    sessionState.me = await fetchMe();
}

export async function completeAuthentication(): Promise<void> {
    try {
        const user = await userManager.signinRedirectCallback();
        if (!user.access_token) throw new Error('OIDC callback did not return an access token.');
        sessionState.accessToken = user.access_token;
        const me = await fetchMe();
        sessionState.me = me;
        sessionState.status = 'authenticated';
    } catch (error) {
        clearSession();
        throw error;
    }
}

export function clearSession(): void {
    sessionState.status = 'anonymous';
    sessionState.accessToken = null;
    sessionState.me = null;
    initializePromise = null;
}

export async function signOut(): Promise<void> {
    clearSession();
    await signOutRedirect();
}
